#!/usr/bin/env python3
"""
Universal local repo deployment agent — optimized v5.

Main goals:
- Accept a local ZIP, local folder, or git URL (GitHub, GitLab, Bitbucket)
- Detect common stacks (Node, Python, Docker, Go, Rust, Ruby, PHP, Java, Make)
- Detect Emergent-style stacks (FastAPI backend + React frontend + MongoDB)
- Detect databases and environment variables from code, not only README/.env.example
- Build a conservative execution plan
- Optionally refine the plan with a local Ollama model
- Execute steps safely with logs, basic repair, port conflict handling, service verification
- Track background services (PIDs) to stop/inspect them later

Recommended local model:
    qwen2.5-coder:14b

Examples:
    python3 universal_repo_agent_v5.py --input ./repo.zip
    python3 universal_repo_agent_v5.py --input https://github.com/user/repo.git --execute
    python3 universal_repo_agent_v5.py --input git@github.com:org/repo.git --execute --approve-all
    python3 universal_repo_agent_v5.py --status
    python3 universal_repo_agent_v5.py --stop my-repo
    python3 universal_repo_agent_v5.py --stop all

GitHub/GitLab/Bitbucket tokens for private repos may be supplied via:
    --github-token / --gitlab-token / --bitbucket-token   (CLI flag)
    GITHUB_TOKEN / GITLAB_TOKEN / BITBUCKET_TOKEN        (env var)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import textwrap
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests


OLLAMA_CHAT_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = "qwen2.5-coder:14b"
DEFAULT_WORKSPACE = Path.home() / "universal-agent-workspace"
LOG_DIRNAME = ".agent_logs"
SERVICES_REGISTRY = ".agent_services.json"
MAX_REPAIR_ATTEMPTS = 2
DEFAULT_VERIFY_TIMEOUT = 120

SAFE_COMMAND_PREFIXES = {
    "ls", "pwd", "cat", "echo", "cp", "mv", "mkdir", "rm", "find", "grep", "sed", "awk", "env", "printenv", "which", "test", "true", "false",
    "sleep", "wait", "kill", "pkill",
    "git", "unzip", "tar", "curl", "wget", "ss", "lsof", "ps", "df", "du",
    "node", "npm", "npx", "yarn", "pnpm", "corepack",
    "python", "python3", "pip", "pip3", "pytest", "uvicorn", "flask", "django-admin", "alembic", "poetry", "streamlit", "gunicorn", "celery", "daphne", "hypercorn",
    "docker", "docker-compose", "compose",
    "make", "go", "cargo", "ruby", "bundle", "rails", "php", "composer", "mvn", "gradle", "java",
    "bash", "sh", "nohup",
}

BLOCKED_PATTERNS = [
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
    r"\bdd\b",
    r"\bmount\b",
    r"\bumount\b",
    r"\bchown\b",
    r"\bchmod\s+777\b",
    r"\buseradd\b",
    r"\bpasswd\b",
    r"\bsudo\b",
    r">\s*/etc/",
    r"rm\s+-rf\s+/",
    r"curl\s+.*\|\s*(bash|sh)",
    r"wget\s+.*\|\s*(bash|sh)",
]

SETUP_SCRIPT_NAMES = [
    "setup.sh", "install.sh", "bootstrap.sh", "init.sh", "start.sh", "run.sh", "dev.sh", "build.sh", "setup.py", "Makefile",
]

SYSTEM_DEPS: Dict[str, Dict[str, str]] = {
    "git": {"check": "git --version", "install": "sudo apt-get install -y git"},
    "node": {"check": "node --version", "install": "sudo apt-get install -y nodejs npm"},
    "npm": {"check": "npm --version", "install": "sudo apt-get install -y npm"},
    "python3": {"check": "python3 --version", "install": "sudo apt-get install -y python3 python3-venv python3-pip"},
    "pip3": {"check": "pip3 --version", "install": "sudo apt-get install -y python3-pip"},
    "docker": {"check": "docker --version", "install": "https://docs.docker.com/engine/install/"},
    "make": {"check": "make --version", "install": "sudo apt-get install -y build-essential"},
    "go": {"check": "go version", "install": "sudo apt-get install -y golang-go"},
    "cargo": {"check": "cargo --version", "install": "curl https://sh.rustup.rs -sSf | sh"},
    "ruby": {"check": "ruby --version", "install": "sudo apt-get install -y ruby"},
    "bundle": {"check": "bundle --version", "install": "gem install bundler"},
    "php": {"check": "php --version", "install": "sudo apt-get install -y php"},
    "composer": {"check": "composer --version", "install": "https://getcomposer.org/download/"},
    "java": {"check": "java -version", "install": "sudo apt-get install -y default-jdk"},
    "mvn": {"check": "mvn --version", "install": "sudo apt-get install -y maven"},
}

DB_DOCKER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "postgresql": {
        "image": "postgres:16-alpine",
        "container": "agent-postgres",
        "port": 5432,
        "env_vars": {"POSTGRES_USER": "agentuser", "POSTGRES_PASSWORD": "agentpass", "POSTGRES_DB": "agentdb"},
        "url_env": "DATABASE_URL",
        "url_template": "postgresql://agentuser:agentpass@localhost:5432/agentdb",
    },
    "mysql": {
        "image": "mysql:8",
        "container": "agent-mysql",
        "port": 3306,
        "env_vars": {"MYSQL_ROOT_PASSWORD": "agentpass", "MYSQL_DATABASE": "agentdb", "MYSQL_USER": "agentuser", "MYSQL_PASSWORD": "agentpass"},
        "url_env": "DATABASE_URL",
        "url_template": "mysql://agentuser:agentpass@localhost:3306/agentdb",
    },
    "mongodb": {
        "image": "mongo:7",
        "container": "agent-mongo",
        "port": 27017,
        "env_vars": {},
        "url_env": "MONGO_URL",
        "url_template": "mongodb://localhost:27017/agentdb",
    },
    "redis": {
        "image": "redis:7-alpine",
        "container": "agent-redis",
        "port": 6379,
        "env_vars": {},
        "url_env": "REDIS_URL",
        "url_template": "redis://localhost:6379",
    },
}

README_NAMES = [
    "README.md", "README.rst", "README.txt", "README", "INSTALL.md", "INSTALL.txt", "GETTING_STARTED.md", "docs/INSTALL.md",
]

ENV_EXAMPLE_NAMES = [
    ".env.example", ".env.sample", ".env.template", ".env.local.example", ".env.development.example", "env.example", "example.env",
]

SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "target", ".agent_logs", ".next", "out",
}

DB_HINT_PATTERNS: Dict[str, Sequence[str]] = {
    "postgresql": [r"DATABASE_URL", r"POSTGRES", r"psycopg", r"asyncpg", r"sqlalchemy.*postgres", r"postgresql://"],
    "mysql": [r"MYSQL", r"pymysql", r"mysqlclient", r"mysql://"],
    "mongodb": [r"MONGO_URL", r"MONGODB_URI", r"pymongo", r"motor\.motor_asyncio", r"mongodb://"],
    "redis": [r"REDIS_URL", r"redis\.Redis", r"import redis", r"redis://"],
    "supabase": [r"SUPABASE", r"supabase"],
}

ENV_VAR_PATTERNS = [
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"process\.env\.([A-Z0-9_]+)"),
]


@dataclass
class ServiceInfo:
    name: str
    path: str
    service_type: str
    framework: Optional[str] = None
    entry_hints: List[str] = field(default_factory=list)
    manifests: List[str] = field(default_factory=list)
    package_manager: Optional[str] = None
    scripts: Dict[str, str] = field(default_factory=dict)
    ports_hint: List[int] = field(default_factory=list)
    confidence: float = 0.0
    run_url: Optional[str] = None
    final_run_cmd: Optional[str] = None


@dataclass
class RepoAnalysis:
    root: str
    repo_name: str
    services: List[ServiceInfo] = field(default_factory=list)
    top_level_manifests: List[str] = field(default_factory=list)
    env_files_present: List[str] = field(default_factory=list)
    env_examples_present: List[str] = field(default_factory=list)
    env_vars_needed: Dict[str, str] = field(default_factory=dict)
    likely_fullstack: bool = False
    likely_db_needed: bool = False
    db_hints: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    host_requirements: List[str] = field(default_factory=list)
    missing_system_deps: List[str] = field(default_factory=list)
    setup_scripts_found: List[str] = field(default_factory=list)
    readme_instructions: List[str] = field(default_factory=list)
    db_provisioned: List[str] = field(default_factory=list)


@dataclass
class CommandStep:
    id: str
    title: str
    cwd: str
    command: str
    expected_outcome: str
    critical: bool = True
    category: str = "run"
    verify_url: Optional[str] = None
    verify_port: Optional[int] = None


@dataclass
class ExecutionPlan:
    summary: str
    steps: List[CommandStep] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class StepError:
    step_id: str
    step_title: str
    command: str
    cwd: str
    returncode: int
    stdout_tail: str
    stderr_tail: str
    diagnosis: str = ""
    repaired: bool = False


@dataclass
class ExecutionResult:
    step_id: str
    command: str
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    started_at: float
    finished_at: float
    repaired: bool = False


class AgentError(Exception):
    pass


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def err(msg: str) -> None:
    print(f"[ERROR] {msg}")


def ensure_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / LOG_DIRNAME).mkdir(parents=True, exist_ok=True)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "project"


def read_text(path: Path, max_chars: int = 60000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""


def safe_json_loads(raw: str) -> Any:
    raw = raw.strip()
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return json.loads(raw)


def shlex_first_token(command: str) -> str:
    import shlex
    parts = shlex.split(command)
    return parts[0] if parts else ""


def _first_real_token(tokens: List[str]) -> Tuple[str, List[str]]:
    """Salta assignacions d'env var a l'inici (p.ex. PORT=3000 FOO=bar yarn start)
    i retorna (primer_token_real, env_assignments)."""
    env_assignments: List[str] = []
    i = 0
    env_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    while i < len(tokens) and env_re.match(tokens[i]):
        env_assignments.append(tokens[i])
        i += 1
    if i >= len(tokens):
        return "", env_assignments
    return tokens[i], env_assignments


def validate_command(command: str, repo_root: Optional[Path] = None) -> None:
    import shlex
    tokens = shlex.split(command)
    if not tokens:
        raise AgentError("Comanda buida")
    # Saltar assignacions d'env var inicials: PORT=3000 yarn start → 'yarn'
    prefix, _env = _first_real_token(tokens)
    if not prefix:
        raise AgentError("Comanda sense binari a executar")
    # Saltar wrappers de process management (setsid, nohup) i buscar el binari real
    while prefix in {"setsid", "nohup"}:
        try:
            idx = tokens.index(prefix) + 1
        except ValueError:
            break
        sub_prefix, _ = _first_real_token(tokens[idx:])
        if not sub_prefix:
            raise AgentError(f"{prefix} sense comanda")
        prefix = sub_prefix
    if prefix in {"bash", "sh"}:
        # Busca el primer argument no-flag que sigui un script
        idx = tokens.index(prefix) + 1
        script_arg = None
        while idx < len(tokens):
            if not tokens[idx].startswith("-"):
                script_arg = tokens[idx]
                break
            idx += 1
        if not script_arg:
            raise AgentError("bash/sh sense argument d'script no permès")
        if repo_root:
            script_path = (repo_root / script_arg).resolve() if not Path(script_arg).is_absolute() else Path(script_arg).resolve()
            if not str(script_path).startswith(str(repo_root.resolve())):
                raise AgentError(f"Script fora del repositori no permès: {script_arg}")
    elif prefix in SAFE_COMMAND_PREFIXES:
        pass
    elif "/" in prefix:
        # Permetre camins a binaris dins del repo o d'un venv del repo (p.ex. .venv/bin/pip, ./scripts/run.sh)
        basename = Path(prefix).name
        if basename not in SAFE_COMMAND_PREFIXES:
            raise AgentError(f"Prefix de comanda no permès: {prefix!r}")
        if repo_root:
            bin_path = (repo_root / prefix).resolve() if not Path(prefix).is_absolute() else Path(prefix).resolve()
            if not str(bin_path).startswith(str(repo_root.resolve())):
                raise AgentError(f"Binari fora del repositori no permès: {prefix}")
    else:
        raise AgentError(f"Prefix de comanda no permès: {prefix!r}")
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            raise AgentError(f"Patró de comanda bloquejat detectat: {command!r}")


def run_shell(command: str, cwd: Path, timeout: int = 1800, repo_root: Optional[Path] = None) -> ExecutionResult:
    validate_command(command, repo_root=repo_root)
    started = time.time()
    try:
        proc = subprocess.run(command, cwd=str(cwd), shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ExecutionResult(step_id="", command=command, cwd=str(cwd), returncode=-1, stdout="", stderr=f"TIMEOUT ({timeout}s)", started_at=started, finished_at=time.time())
    return ExecutionResult(step_id="", command=command, cwd=str(cwd), returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, started_at=started, finished_at=time.time())


def run_check(command: str) -> bool:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except Exception:
        return False


def write_log(log_dir: Path, name: str, content: str) -> Path:
    path = log_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def file_exists_any(root: Path, names: Sequence[str]) -> bool:
    return any((root / n).exists() for n in names)


def tail_lines(text: str, n: int = 12) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:]) if lines else ""


def detect_ports_from_text(text: str) -> List[int]:
    ports: set[int] = set()
    for match in re.finditer(r"\b(?:port|PORT)\D{0,10}(\d{2,5})\b", text):
        try:
            ports.add(int(match.group(1)))
        except ValueError:
            pass
    for match in re.finditer(r'"(\d{2,5}):(\d{2,5})"', text):
        try:
            ports.add(int(match.group(2)))
        except ValueError:
            pass
    return sorted(p for p in ports if 1024 <= p <= 65535)


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def find_free_port(start: int, max_attempts: int = 50) -> int:
    port = start
    for _ in range(max_attempts):
        if not is_port_open(port):
            return port
        port += 1
    raise AgentError(f"No s'ha trobat cap port lliure a partir de {start}")


def verify_http(url: str, timeout: int = DEFAULT_VERIFY_TIMEOUT) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def verify_port(port: int, timeout: int = DEFAULT_VERIFY_TIMEOUT) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if is_port_open(port):
            return True
        time.sleep(1)
    return False


def maybe_background_command(command: str, log_rel: str = ".agent_last_run.log") -> Tuple[str, bool]:
    """Retorna (command_modificat, is_background). Si cal, embolica amb nohup+& i imprimeix el PID.
    Les assignacions d'env var al principi (PORT=3000 ...) es mantenen abans de nohup perquè
    el shell les interpreti correctament."""
    markers = ["npm start", "npm run dev", "yarn start", "yarn dev", "pnpm dev",
               "uvicorn ", "flask ", "python manage.py runserver", "streamlit run",
               "rails server", "php artisan serve", "go run ", "cargo run", "docker compose up"]
    if any(marker in command for marker in markers):
        # Evita re-wrapping si ja ve amb nohup/&
        if "nohup" in command or command.rstrip().endswith("&"):
            return command, True
        # Extreu assignacions d'env var inicials perquè quedin abans de 'nohup'
        import shlex
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        env_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
        env_assigns: List[str] = []
        i = 0
        while i < len(tokens) and env_re.match(tokens[i]):
            env_assigns.append(tokens[i])
            i += 1
        rest = " ".join(shlex.quote(t) if " " in t else t for t in tokens[i:])
        env_prefix = (" ".join(env_assigns) + " ") if env_assigns else ""
        wrapped = f"{env_prefix}setsid nohup {rest} > {log_rel} 2>&1 < /dev/null & echo __AGENT_PID__=$!"
        return wrapped, True
    return command, False


def ollama_chat_json(model: str, messages: List[Dict[str, str]], schema: Optional[Dict[str, Any]] = None, timeout: int = 180) -> Any:
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if schema is not None:
        payload["format"] = schema
    res = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
    res.raise_for_status()
    return safe_json_loads(res.json()["message"]["content"])


def is_git_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://") or value.endswith(".git") or value.startswith("git@")


def inject_git_token(url: str, github_token: str = "", gitlab_token: str = "", bitbucket_token: str = "") -> str:
    """Injecta el token corresponent a la URL HTTPS de GitHub/GitLab/Bitbucket.
    Fallback a variables d'entorn si no s'ha passat per paràmetre."""
    if not url.startswith("https://"):
        return url
    gh = github_token or os.environ.get("GITHUB_TOKEN", "")
    gl = gitlab_token or os.environ.get("GITLAB_TOKEN", "")
    bb = bitbucket_token or os.environ.get("BITBUCKET_TOKEN", "")
    if "github.com" in url and gh:
        return re.sub(r"^https://github\.com", f"https://x-access-token:{gh}@github.com", url)
    if "gitlab.com" in url and gl:
        return re.sub(r"^https://gitlab\.com", f"https://oauth2:{gl}@gitlab.com", url)
    if "bitbucket.org" in url and bb:
        return re.sub(r"^https://bitbucket\.org", f"https://x-token-auth:{bb}@bitbucket.org", url)
    return url


# Backwards compatibility
def inject_github_token(url: str, token: str) -> str:
    return inject_git_token(url, github_token=token)


def acquire_input(input_value: str, workspace: Path, github_token: str = "", gitlab_token: str = "", bitbucket_token: str = "") -> Path:
    ensure_workspace(workspace)
    if not is_git_url(input_value):
        source = Path(os.path.expandvars(os.path.expanduser(input_value))).resolve()
    else:
        source = Path(input_value)
    if not is_git_url(input_value) and source.exists():
        if source.is_dir():
            try:
                if source.is_relative_to(workspace.resolve()):
                    info(f"Carpeta local dins workspace, reutilitzada: {source}")
                    return source
            except AttributeError:
                if str(source).startswith(str(workspace.resolve())):
                    info(f"Carpeta local dins workspace, reutilitzada: {source}")
                    return source
            target = workspace / slugify(source.name)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            info(f"Carpeta local copiada: {target}")
            return target
        if source.is_file() and source.suffix.lower() == ".zip":
            target = workspace / slugify(source.stem)
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source, "r") as zf:
                zf.extractall(target)
            info(f"ZIP descomprimit: {target}")
            return target
        raise AgentError("L'input existeix però no és una carpeta ni un .zip")
    if is_git_url(input_value):
        parsed = urlparse(input_value if not input_value.startswith("git@") else input_value.replace(":", "/", 1))
        repo_name = Path(parsed.path).stem or "repo"
        target = workspace / slugify(repo_name)
        if target.exists():
            shutil.rmtree(target)
        clone_url = inject_git_token(input_value, github_token=github_token, gitlab_token=gitlab_token, bitbucket_token=bitbucket_token)
        info(f"Clonant {input_value} → {target}")
        result = run_shell(f"git clone {clone_url} {target}", cwd=workspace, timeout=300)
        if result.returncode != 0:
            raise AgentError(f"git clone ha fallat (codi {result.returncode}):\n{tail_lines(result.stderr, 10)}")
        info("Repositori clonat ✅")
        return target
    raise AgentError(f"Input '{input_value}' no trobat. Proporciona una carpeta local existent, un .zip o una URL de git.")


def find_readme(root: Path) -> Optional[Path]:
    for name in README_NAMES:
        p = root / name
        if p.exists():
            return p
    return None


def extract_instructions_from_readme(root: Path, model: str) -> List[str]:
    readme_path = find_readme(root)
    if not readme_path:
        return []
    readme_text = read_text(readme_path, max_chars=8000)
    if len(readme_text) < 100:
        return []
    info(f"Llegint instruccions del README: {readme_path.name}")
    schema = {
        "type": "object",
        "properties": {
            "install_commands": {"type": "array", "items": {"type": "string"}},
            "run_commands": {"type": "array", "items": {"type": "string"}},
            "prerequisites": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["install_commands", "run_commands", "prerequisites", "notes", "confidence"],
    }
    system_prompt = textwrap.dedent(
        """
        You are a deployment assistant. Extract ONLY concrete shell commands from README files.
        Rules:
        - Extract commands exactly as written
        - Skip commands requiring secrets not yet available; mention them in notes instead
        - Skip commands requiring sudo; mention them in notes instead
        - Do not invent commands
        - Output valid JSON only
        """
    ).strip()
    try:
        data = ollama_chat_json(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"README content:\n\n{readme_text}"},
            ],
            schema=schema,
            timeout=120,
        )
    except Exception as e:
        warn(f"No s'han pogut extreure instruccions del README: {e}")
        return []
    instructions: List[str] = []
    if data.get("prerequisites"):
        instructions.append("📋 Prerequisits del README: " + ", ".join(data["prerequisites"]))
    for note in data.get("notes", []):
        instructions.append(f"⚠️  {note}")
    for cmd in data.get("install_commands", []) + data.get("run_commands", []):
        cmd = cmd.strip()
        if cmd and not cmd.startswith("#"):
            instructions.append(cmd)
    if instructions:
        info(f"README: {len(instructions)} instruccions extretes")
    return instructions


def find_setup_scripts(root: Path) -> List[Path]:
    found: List[Path] = []
    for name in SETUP_SCRIPT_NAMES:
        p = root / name
        if p.exists() and p.name != "Makefile":
            found.append(p)
    for subdir in root.iterdir():
        if subdir.is_dir() and subdir.name not in SKIP_DIRS:
            for name in ("setup.sh", "install.sh", "bootstrap.sh"):
                p = subdir / name
                if p.exists():
                    found.append(p)
    return found


def build_setup_script_step(script_path: Path, repo_root: Path) -> Optional[CommandStep]:
    rel = script_path.relative_to(repo_root)
    ext = script_path.suffix.lower()
    if ext in {".sh", ""}:
        script_path.chmod(script_path.stat().st_mode | 0o111)
        command = f"bash {rel}"
    elif ext == ".py":
        command = f"python3 {rel}"
    else:
        return None
    return CommandStep(id=f"setup-script-{slugify(script_path.name)}", title=f"Script de setup: {rel}", cwd=str(repo_root), command=command, expected_outcome="Script de setup completat sense errors", critical=False, category="setup")


def is_docker_available() -> bool:
    return run_check("docker info")


def build_db_provision_steps(db_hints: List[str]) -> Tuple[List[CommandStep], Dict[str, str]]:
    steps: List[CommandStep] = []
    env_vars: Dict[str, str] = {}
    for db_key in db_hints:
        cfg = DB_DOCKER_CONFIGS.get(db_key)
        if not cfg:
            continue
        container = cfg["container"]
        image = cfg["image"]
        port = cfg["port"]
        env_flags = " ".join(f'-e {k}="{v}"' for k, v in cfg["env_vars"].items())
        command = f"docker inspect {container} > /dev/null 2>&1 && docker start {container} || docker run -d --name {container} -p {port}:{port} {env_flags} {image}"
        steps.append(CommandStep(id=f"db-provision-{db_key}", title=f"Provisió automàtica de {db_key.upper()} (Docker)", cwd="/tmp", command=command, expected_outcome=f"Contenidor {db_key} en execució al port {port}", critical=False, category="db", verify_port=port))
        env_vars[cfg["url_env"]] = cfg["url_template"]
        env_vars.update(cfg["env_vars"])
    return steps, env_vars


def inject_db_env_vars(root: Path, env_vars: Dict[str, str]) -> None:
    env_file = root / ".env"
    if not env_file.exists():
        lines = ["# Variables de BD generades automàticament per l'agent\n"]
        lines.extend(f"{k}={v}\n" for k, v in env_vars.items())
        env_file.write_text("".join(lines), encoding="utf-8")
        info(f"Creat .env amb variables de BD a {env_file}")
        return
    existing = read_text(env_file)
    additions = [f"{k}={v}" for k, v in env_vars.items() if k not in existing]
    if additions:
        with env_file.open("a", encoding="utf-8") as f:
            f.write("\n# Variables de BD generades automàticament per l'agent\n")
            for line in additions:
                f.write(line + "\n")
        info(f"Afegides {len(additions)} variables de BD al .env existent")


def check_system_dependencies(required: List[str]) -> List[str]:
    missing: List[str] = []
    for dep in required:
        dep_info = SYSTEM_DEPS.get(dep)
        check_cmd = dep_info["check"] if dep_info else f"which {dep}"
        if not run_check(check_cmd):
            missing.append(dep)
    return missing


def report_missing_deps(missing: List[str], auto_approve: bool = False) -> bool:
    if not missing:
        return True
    print("\n⚠️  DEPENDÈNCIES DEL SISTEMA QUE FALTEN:")
    for dep in missing:
        hint = SYSTEM_DEPS.get(dep, {}).get("install", f"sudo apt-get install -y {dep}")
        print(f"  • {dep:20s} -> {hint}")
    if auto_approve:
        warn("auto-approve: continuant tot i que falten deps.")
        return True
    answer = input("Vols continuar igualment? [s/N]: ").strip().lower()
    return answer in {"s", "si", "y", "yes"}


def find_env_examples(root: Path) -> List[Path]:
    found: List[Path] = []
    for name in ENV_EXAMPLE_NAMES:
        found.extend(root.rglob(name))
    return found


_PLACEHOLDER_KEYWORDS = (
    "your_", "change_", "xxx", "canvia", "secret_key",
    "changeme", "change_me", "replace_me", "replace_with",
    "put_your", "add_your", "insert_your", "your-",
)


def is_placeholder_value(value: str) -> bool:
    """Retorna True si el valor és buit o sembla un placeholder, no un valor real."""
    if not value:
        return True
    v = value.lower()
    return any(kw in v for kw in _PLACEHOLDER_KEYWORDS)


def parse_env_example(path: Path) -> Dict[str, str]:
    vars_needed: Dict[str, str] = {}
    last_comment = ""
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line:
            last_comment = ""
            continue
        if line.startswith("#"):
            last_comment = line.lstrip("#").strip()
            continue
        if "=" in line:
            var, _, default = line.partition("=")
            var = var.strip()
            default = default.strip()
            is_secret = any(kw in var.upper() for kw in ["SECRET", "PASSWORD", "TOKEN", "KEY", "API", "DSN", "DATABASE_URL", "DB_", "AUTH", "PRIVATE"])
            has_real_value = bool(default)
            if not has_real_value and (not default or is_secret):
                vars_needed[var] = last_comment or default or "(requerida)"
        last_comment = ""
    return vars_needed


def detect_env_vars_from_code(root: Path) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    code_files = list(root.rglob("*.py")) + list(root.rglob("*.js")) + list(root.rglob("*.jsx")) + list(root.rglob("*.ts")) + list(root.rglob("*.tsx"))
    for path in code_files:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        text = read_text(path, max_chars=20000)
        for pattern in ENV_VAR_PATTERNS:
            for match in pattern.finditer(text):
                var = match.group(1)
                env_vars.setdefault(var, f"detectada a {path.name}")
    return env_vars


def interactive_env_setup(root: Path, env_examples: List[Path], prefilled: Optional[Dict[str, str]] = None, detected_vars: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    prefilled = prefilled or {}
    detected_vars = detected_vars or {}
    all_values: Dict[str, str] = {}
    for example_path in env_examples:
        env_target = example_path.parent / ".env"
        if env_target.exists():
            answer = input(f"{env_target} ja existeix. Sobreescriure? [s/N]: ").strip().lower()
            if answer not in {"s", "si", "y", "yes"}:
                continue
        vars_needed = parse_env_example(example_path)
        if not vars_needed:
            shutil.copy(example_path, env_target)
            info(f"Copiat {example_path} -> {env_target}")
            continue
        env_lines: List[str] = []
        for line in read_text(example_path).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                env_lines.append(line)
                continue
            if "=" not in stripped:
                env_lines.append(line)
                continue
            var, _, default = stripped.partition("=")
            var = var.strip()
            if var in vars_needed:
                if var in prefilled:
                    value = prefilled[var]
                elif default:
                    value = default
                else:
                    label = detected_vars.get(var) or vars_needed[var]
                    value = input(f"{var} ({label}) [{default or ''}]: ").strip() or default
                env_lines.append(f"{var}={value}")
                all_values[var] = value
            else:
                env_lines.append(line)
        env_target.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        info(f"Creat {env_target}")
    if not env_examples and detected_vars:
        env_target = root / ".env"
        existing = read_text(env_target) if env_target.exists() else ""
        additions: List[str] = []
        for var in sorted(detected_vars):
            if var in existing:
                continue
            if var in prefilled:
                additions.append(f"{var}={prefilled[var]}")
            else:
                additions.append(f"{var}=")
        if additions:
            with env_target.open("a", encoding="utf-8") as f:
                f.write("\n# Variables detectades automàticament\n")
                for line in additions:
                    f.write(line + "\n")
            info(f"Creat/actualitzat {env_target} amb variables detectades automàticament")
    return all_values


def maybe_promote_single_nested_root(root: Path) -> Path:
    children = [p for p in root.iterdir() if p.name != LOG_DIRNAME]
    if len(children) == 1 and children[0].is_dir():
        nested = children[0]
        score = sum((nested / n).exists() for n in ["package.json", "requirements.txt", "pyproject.toml", "Dockerfile", "docker-compose.yml", ".gitignore", "README.md"])
        if score >= 2:
            return nested
    return root


def _read_port_from_env_example(path: Path) -> Optional[int]:
    """Llegeix el valor de PORT del .env.example si existeix i és numèric."""
    for name in ENV_EXAMPLE_NAMES:
        example = path / name
        if not example.exists():
            continue
        for line in read_text(example).splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            var, _, val = line.partition("=")
            if var.strip() == "PORT":
                val = val.strip()
                if val.isdigit():
                    return int(val)
    return None


def detect_node_service(path: Path) -> Optional[ServiceInfo]:
    pkg = path / "package.json"
    if not pkg.exists():
        return None
    pkg_raw = read_text(pkg)
    try:
        pkg_data = json.loads(pkg_raw)
    except Exception:
        pkg_data = {}
    if is_node_library(pkg_data):
        return None
    scripts = pkg_data.get("scripts", {})
    all_deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})} if isinstance(pkg_data, dict) else {}
    dep_names = set(all_deps.keys())
    ports_hint = detect_ports_from_text(pkg_raw)
    if "next" in dep_names:
        framework, run_url = "next", "http://localhost:3000"
    elif "vite" in dep_names:
        framework, run_url = "vite", "http://localhost:5173"
    elif "react" in dep_names:
        framework, run_url = "react", "http://localhost:3000"
    elif "express" in dep_names:
        framework, run_url = "express", "http://localhost:3000"
    else:
        framework, run_url = "node", None
    pm = "pnpm" if (path / "pnpm-lock.yaml").exists() else "yarn" if (path / "yarn.lock").exists() else "npm"
    env_port = _read_port_from_env_example(path)
    if env_port:
        run_url = f"http://localhost:{env_port}"
    elif ports_hint and not run_url:
        run_url = f"http://localhost:{ports_hint[0]}"
    confidence = 0.7 + (0.1 if "dev" in scripts else 0) + (0.1 if "start" in scripts else 0)
    return ServiceInfo(name=path.name, path=str(path), service_type="node", framework=framework, entry_hints=list(scripts.keys()), manifests=["package.json"], package_manager=pm, scripts=scripts, ports_hint=sorted(set(ports_hint)), confidence=min(confidence, 0.95), run_url=run_url)


def detect_python_service(path: Path) -> Optional[ServiceInfo]:
    req = path / "requirements.txt"
    pyproject = path / "pyproject.toml"
    candidates = [path / n for n in ("server.py", "main.py", "app.py", "manage.py", "database.py", "config.py", "settings.py")]
    if not req.exists() and not pyproject.exists() and not any(p.exists() for p in candidates):
        return None
    manifests: List[str] = []
    entry_hints: List[str] = []
    text_sources: List[str] = []
    for m in (req, pyproject):
        if m.exists():
            manifests.append(m.name)
            text_sources.append(read_text(m))
    for c in candidates:
        if c.exists():
            entry_hints.append(c.name)
            text_sources.append(read_text(c))
    combined = "\n".join(text_sources).lower()
    ports = detect_ports_from_text(combined)
    if "fastapi" in combined or "uvicorn" in combined:
        fw, url, conf = "fastapi", "http://localhost:8001", 0.8
    elif "flask" in combined:
        fw, url, conf = "flask", "http://localhost:8001", 0.8
    elif "django" in combined:
        fw, url, conf = "django", "http://localhost:8001", 0.8
    elif "streamlit" in combined:
        fw, url, conf = "streamlit", "http://localhost:8501", 0.75
    else:
        fw, url, conf = "python", None, 0.65
    if ports and not url:
        url = f"http://localhost:{ports[0]}"
    return ServiceInfo(name=path.name, path=str(path), service_type="python", framework=fw, entry_hints=entry_hints, manifests=manifests, ports_hint=ports, confidence=min(conf, 0.95), run_url=url)


def detect_docker_service(path: Path) -> Optional[ServiceInfo]:
    compose_candidates = [path / "docker-compose.yml", path / "docker-compose.yaml", path / "compose.yml"]
    compose_path = next((p for p in compose_candidates if p.exists()), None)
    dockerfile = path / "Dockerfile"
    if not compose_path and not dockerfile.exists():
        return None
    manifests: List[str] = []
    entry_hints: List[str] = []
    ports_hint: List[int] = []
    confidence = 0.75
    if compose_path:
        manifests.append(compose_path.name)
        entry_hints.append("docker compose up")
        confidence += 0.1
        ports_hint = detect_ports_from_text(read_text(compose_path))
    if dockerfile.exists():
        manifests.append("Dockerfile")
        entry_hints.append("docker build")
    run_url = f"http://localhost:{ports_hint[0]}" if ports_hint else None
    return ServiceInfo(name=path.name, path=str(path), service_type="docker", framework="docker", entry_hints=entry_hints, manifests=manifests, ports_hint=sorted(set(ports_hint)), confidence=min(confidence, 0.95), run_url=run_url)


def detect_go_service(path: Path) -> Optional[ServiceInfo]:
    return ServiceInfo(name=path.name, path=str(path), service_type="go", framework="go", entry_hints=["go run ./...", "go build"], manifests=["go.mod"], confidence=0.75, run_url="http://localhost:8080") if (path / "go.mod").exists() else None


def detect_rust_service(path: Path) -> Optional[ServiceInfo]:
    return ServiceInfo(name=path.name, path=str(path), service_type="rust", framework="rust", entry_hints=["cargo run", "cargo build --release"], manifests=["Cargo.toml"], confidence=0.75) if (path / "Cargo.toml").exists() else None


def detect_ruby_service(path: Path) -> Optional[ServiceInfo]:
    if not (path / "Gemfile").exists():
        return None
    text = read_text(path / "Gemfile").lower()
    fw = "rails" if "rails" in text else "sinatra" if "sinatra" in text else "ruby"
    url = "http://localhost:3000" if fw in {"rails", "sinatra"} else None
    return ServiceInfo(name=path.name, path=str(path), service_type="ruby", framework=fw, entry_hints=["bundle exec rails server", "bundle exec ruby"], manifests=["Gemfile"], confidence=0.7, run_url=url)


def detect_php_service(path: Path) -> Optional[ServiceInfo]:
    if not (path / "composer.json").exists():
        return None
    text = read_text(path / "composer.json").lower()
    fw = "laravel" if "laravel" in text else "symfony" if "symfony" in text else "php"
    return ServiceInfo(name=path.name, path=str(path), service_type="php", framework=fw, entry_hints=["php artisan serve", "php -S localhost:8000"], manifests=["composer.json"], confidence=0.7, run_url="http://localhost:8000")


def detect_java_service(path: Path) -> Optional[ServiceInfo]:
    pom, gradle, gradk = path / "pom.xml", path / "build.gradle", path / "build.gradle.kts"
    if not pom.exists() and not gradle.exists() and not gradk.exists():
        return None
    manifests = [pom.name] if pom.exists() else [gradle.name if gradle.exists() else gradk.name]
    entry_hint = "mvn spring-boot:run" if pom.exists() else "./gradlew bootRun"
    return ServiceInfo(name=path.name, path=str(path), service_type="java", framework="spring", entry_hints=[entry_hint], manifests=manifests, confidence=0.7, run_url="http://localhost:8080")


def detect_makefile_service(path: Path) -> Optional[ServiceInfo]:
    makefile = path / "Makefile"
    if not makefile.exists():
        return None
    targets = re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]+)\s*:", read_text(makefile), re.MULTILINE)
    useful = [t for t in targets if t in {"run", "start", "dev", "serve", "up", "build", "install", "all", "setup"}]
    return ServiceInfo(name=path.name, path=str(path), service_type="make", framework="make", entry_hints=useful or targets[:5], manifests=["Makefile"], confidence=0.6)


ALL_DETECTORS = [detect_node_service, detect_python_service, detect_docker_service, detect_go_service, detect_rust_service, detect_ruby_service, detect_php_service, detect_java_service, detect_makefile_service]


EXAMPLE_DIRS = {"examples", "example", "demo", "demos", "samples", "sample", "tutorials", "tutorial", "docs", "documentation"}


def is_node_library(pkg_data: dict) -> bool:
    """Detecta si un package.json correspon a una llibreria/tool Node, no una app arrencable.

    Puntuació basada en camps estàtics del manifest (sense llegir codi font):
      +2  "files"          — declara subset npm-publish; apps no necessiten això
      +1  "peerDependencies" no buit — plugins/extensors; apps rarament ho declaren
      +1  "exports"        — mapa ESM explícit; apps rarament el declaren
      +1  "publishConfig"  — configura el registre npm → es publica → és una lib
      +1  cap script runnable (start/dev/serve/preview) → no té punt d'arrencada
      -1  "private": true  → no es publica → probablement app o arrel de monorepo

    Llindar: score >= 2 → és una llibreria (retorna None al detector).
    """
    score = 0
    if "files" in pkg_data:
        score += 2
    if pkg_data.get("peerDependencies"):
        score += 1
    if "exports" in pkg_data:
        score += 1
    if "publishConfig" in pkg_data:
        score += 1
    scripts = pkg_data.get("scripts", {})
    if not any(k in scripts for k in ("start", "dev", "serve", "preview")):
        score += 1
    if pkg_data.get("private"):
        score -= 1
    return score >= 2


def is_library_package_root(root: Path) -> bool:
    """Detecta si el root del repo és una llibreria Python (no una app).
    En aquest cas, els subdirectoris examples/ no s'haurien de tractar com a apps."""
    # Cas 1: setup.py amb setup() (no només config)
    if (root / "setup.py").exists():
        text = read_text(root / "setup.py", max_chars=5000)
        if "setup(" in text and any(kw in text for kw in ["packages=", "find_packages", "name="]):
            return True
    # Cas 2: pyproject.toml amb [project]
    if (root / "pyproject.toml").exists():
        text = read_text(root / "pyproject.toml", max_chars=5000)
        if "[project]" in text or "[tool.poetry]" in text:
            return True
    return False


def discover_candidate_dirs(root: Path) -> List[Path]:
    manifest_files = {"package.json", "requirements.txt", "pyproject.toml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "Makefile", "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts"}
    # Si el root és una llibreria Python, no mirem subdirectoris d'exemples
    is_library = is_library_package_root(root)
    candidates = [root]
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        # Si és llibreria: salta subcarpetes d'exemples/docs
        if is_library:
            rel = Path(current_root).relative_to(root)
            if rel.parts and rel.parts[0] in EXAMPLE_DIRS:
                dirs[:] = []
                continue
        if set(files) & manifest_files:
            candidates.append(Path(current_root))
    seen: set[str] = set()
    result: List[Path] = []
    for p in sorted(candidates, key=lambda x: len(str(x))):
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


def detect_db_hints_from_code(root: Path) -> List[str]:
    hints: set[str] = set()
    files = list(root.rglob("*.py")) + list(root.rglob("*.js")) + list(root.rglob("*.ts")) + list(root.rglob("*.tsx")) + list(root.rglob("*.jsx")) + list(root.rglob("*.env"))
    for path in files:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        text = read_text(path, max_chars=25000)
        for db_name, patterns in DB_HINT_PATTERNS.items():
            if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
                hints.add(db_name)
    return sorted(hints)


def detect_emergent_stack(root: Path) -> Optional[Dict[str, Any]]:
    """Detecta l'estructura típica d'un repositori Emergent:
       /backend/server.py  (FastAPI)
       /backend/requirements.txt
       /frontend/package.json (React)
       /frontend/.env  o  frontend referències a REACT_APP_BACKEND_URL
       MongoDB (MONGO_URL, motor, pymongo)

    Retorna un dict amb 'backend' i 'frontend' paths si coincideix, o None."""
    backend = root / "backend"
    frontend = root / "frontend"
    if not backend.is_dir() or not frontend.is_dir():
        return None
    server_py = backend / "server.py"
    pkg_json = frontend / "package.json"
    if not server_py.exists() or not pkg_json.exists():
        return None
    server_text = read_text(server_py).lower()
    pkg_text = read_text(pkg_json).lower()
    is_fastapi = "fastapi" in server_text
    is_react = '"react"' in pkg_text or "react-scripts" in pkg_text or '"next"' in pkg_text
    if not (is_fastapi and is_react):
        return None
    # Mongo: busca a TOTS els .py del backend, no només server.py
    mongo_re = re.compile(r"mongo_url|motor\.motor_asyncio|pymongo|mongoclient", re.IGNORECASE)
    uses_mongo = False
    for py_file in backend.rglob("*.py"):
        if any(part in SKIP_DIRS for part in py_file.parts):
            continue
        if mongo_re.search(read_text(py_file, max_chars=15000)):
            uses_mongo = True
            break
    # Dependències addicionals detectades al requirements.txt
    req_text = read_text(backend / "requirements.txt").lower()
    if not uses_mongo and ("pymongo" in req_text or "motor" in req_text):
        uses_mongo = True
    # Detecta requisits d'autenticació JWT (molts repos Emergent en tenen)
    uses_jwt = bool(re.search(r"jwt_secret|pyjwt|python-jose", req_text + server_text))
    return {
        "backend": str(backend),
        "frontend": str(frontend),
        "uses_mongo": uses_mongo,
        "uses_jwt": uses_jwt,
        "has_yarn_lock": (frontend / "yarn.lock").exists(),
    }


def _detect_lan_ip() -> str:
    """Detecta la IP LAN del host (per fer accessible el backend des d'altres màquines)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "localhost"


def _inject_cra_proxy(frontend: Path, backend_port: int = 8001) -> bool:
    """DESACTIVAT: proxy CRA no funciona amb IP LAN. Neteja proxy antics si n'hi ha."""
    pkg = frontend / "package.json"
    if not pkg.exists():
        return False
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except Exception:
        return False
    if "proxy" in data:
        del data["proxy"]
        pkg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        info("Frontend package.json: proxy antic eliminat (usarem REACT_APP_BACKEND_URL)")
    return False

def prepare_emergent_env_files(root: Path, emergent: Dict[str, Any], backend_port: int = 8001) -> None:
    """Crea/actualitza els .env típics d'un stack Emergent."""
    backend = Path(emergent["backend"])
    frontend = Path(emergent["frontend"])
    lan_ip = _detect_lan_ip()
    # Injecta proxy CRA si és possible (fa REACT_APP_BACKEND_URL irrellevant)
    cra_proxy_ok = _inject_cra_proxy(frontend, backend_port=backend_port)
    # Backend .env
    be_env = backend / ".env"
    be_existing = read_text(be_env) if be_env.exists() else ""
    be_lines: List[str] = []
    if emergent.get("uses_mongo"):
        if "MONGO_URL" not in be_existing:
            be_lines.append('MONGO_URL="mongodb://localhost:27017"')
        if "DB_NAME" not in be_existing:
            be_lines.append(f'DB_NAME="{slugify(root.name).replace("-", "_")}_db"')
    if "CORS_ORIGINS" not in be_existing:
        # Amb proxy CRA, el navegador veu les peticions com a same-origin, així que
        # en teoria CORS no es necessita. Però posem valors permissius per si el
        # repo fa crides des d'un client extern.
        cors = ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"]
        if lan_ip and lan_ip != "localhost":
            cors += [f"http://{lan_ip}:{p}" for p in (3000, 3001, 3002)]
        cors.append("*")  # fallback permissiu per a dev local
        be_lines.append(f'CORS_ORIGINS="{",".join(cors)}"')
    if emergent.get("uses_jwt"):
        if "JWT_SECRET" not in be_existing:
            import secrets as _secrets
            be_lines.append(f'JWT_SECRET="{_secrets.token_urlsafe(32)}"')
        if "JWT_ALGORITHM" not in be_existing:
            be_lines.append('JWT_ALGORITHM="HS256"')
    if be_lines:
        with be_env.open("a", encoding="utf-8") as f:
            if be_existing and not be_existing.endswith("\n"):
                f.write("\n")
            f.write("# Variables generades automàticament per l'agent\n")
            f.write("\n".join(be_lines) + "\n")
        info(f"Backend .env actualitzat: {be_env}")
    # Frontend .env
    fe_env = frontend / ".env"
    fe_existing = read_text(fe_env) if fe_env.exists() else ""
    fe_lines: List[str] = []
    if "REACT_APP_BACKEND_URL" not in fe_existing:
        if cra_proxy_ok:
            # Amb proxy CRA, URL buit → rutes relatives → immune a canvis d'IP
            fe_lines.append('REACT_APP_BACKEND_URL=""')
        else:
            be_host = lan_ip if lan_ip and lan_ip != "localhost" else "localhost"
            fe_lines.append(f"REACT_APP_BACKEND_URL=http://{be_host}:{backend_port}")
    if "WDS_SOCKET_PORT" not in fe_existing:
        fe_lines.append("WDS_SOCKET_PORT=0")  # 0 = auto
    if fe_lines:
        with fe_env.open("a", encoding="utf-8") as f:
            if fe_existing and not fe_existing.endswith("\n"):
                f.write("\n")
            f.write("# Variables generades automàticament per l'agent\n")
            f.write("\n".join(fe_lines) + "\n")
        info(f"Frontend .env actualitzat: {fe_env}")


# =============================================================================
# MILLORA C — Secrets cache (EMERGENT_LLM_KEY, OPENAI_API_KEY, STRIPE_*, etc.)
# =============================================================================

SECRETS_DIR = Path.home() / ".universal-agent"
SECRETS_FILE = SECRETS_DIR / "secrets.json"

KNOWN_SECRET_KEYS = {
    "EMERGENT_LLM_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "STRIPE_SECRET_KEY", "STRIPE_API_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET",
    "SENDGRID_API_KEY", "RESEND_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
    "JWT_SECRET", "SECRET_KEY", "DJANGO_SECRET_KEY", "NEXTAUTH_SECRET",
    "MONGODB_URI_ATLAS", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "HUGGINGFACE_API_KEY", "FAL_KEY",
}


def load_secrets_cache() -> Dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}
    try:
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_secrets_cache(data: Dict[str, str]) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        SECRETS_FILE.chmod(0o600)
    except Exception:
        pass


def prompt_and_cache_secrets(detected_vars: Dict[str, str], existing_env: str, non_interactive: bool = False, example_real_values: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Per cada secret conegut detectat i que no estigui ja al .env,
    el busca a la caché i si no hi és el demana a l'usuari i el guarda.
    Si example_real_values conté un valor real (no placeholder) per a la variable, se salta."""
    cache = load_secrets_cache()
    resolved: Dict[str, str] = {}
    secrets_needed = [
        v for v in detected_vars
        if v in KNOWN_SECRET_KEYS
        and v not in existing_env
        and not (example_real_values and example_real_values.get(v))
    ]
    if not secrets_needed:
        return resolved
    info(f"Detectats {len(secrets_needed)} secrets requerits: {', '.join(secrets_needed)}")
    for var in secrets_needed:
        if var in cache and cache[var]:
            resolved[var] = cache[var]
            info(f"  · {var} reutilitzat de la caché ~/.universal-agent/secrets.json")
            continue
        if non_interactive:
            warn(f"  · {var} no trobat a la caché i mode no-interactiu: deixat buit")
            continue
        print(f"\n  Introdueix el valor per {var} (deixa buit per saltar):")
        if var == "EMERGENT_LLM_KEY":
            print("    (Obteniu-la al vostre Profile → Universal Key a emergent.sh)")
        value = input(f"  {var} = ").strip()
        if value:
            resolved[var] = value
            cache[var] = value
            save_secrets_cache(cache)
            info(f"  · {var} desat a ~/.universal-agent/secrets.json (chmod 600)")
    return resolved


def inject_secrets_into_env(env_file: Path, secrets: Dict[str, str]) -> None:
    if not secrets:
        return
    existing = read_text(env_file) if env_file.exists() else ""
    additions = {k: v for k, v in secrets.items() if k not in existing}
    if not additions:
        return
    with env_file.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("# Secrets afegits per l'agent (de la caché o interactiu)\n")
        for k, v in additions.items():
            f.write(f'{k}="{v}"\n')
    info(f"Afegits {len(additions)} secrets a {env_file}")


# =============================================================================
# MILLORA — Dependències del sistema per paquets Python/Node natius
# =============================================================================

PIP_SYSTEM_DEPS: Dict[str, List[str]] = {
    "psycopg2": ["libpq-dev", "postgresql-client"],
    "psycopg": ["libpq-dev"],
    "pillow": ["libjpeg-dev", "zlib1g-dev", "libpng-dev"],
    "lxml": ["libxml2-dev", "libxslt1-dev"],
    "cryptography": ["libssl-dev", "libffi-dev"],
    "mysqlclient": ["default-libmysqlclient-dev", "pkg-config"],
    "pymssql": ["freetds-dev", "freetds-bin"],
    "python-magic": ["libmagic1"],
    "python-magic-bin": [],
    "cairosvg": ["libcairo2-dev"],
    "weasyprint": ["libpango-1.0-0", "libpangoft2-1.0-0", "libcairo2"],
    "pyaudio": ["portaudio19-dev"],
    "pycairo": ["libcairo2-dev"],
    "pygobject": ["libgirepository1.0-dev", "libcairo2-dev"],
    "dbus-python": ["libdbus-1-dev", "libglib2.0-dev"],
    "python-ldap": ["libldap2-dev", "libsasl2-dev"],
    "pdfminer": ["poppler-utils"],
    "pyicu": ["libicu-dev"],
    "pycurl": ["libcurl4-openssl-dev", "libssl-dev"],
    "reportlab": ["libfreetype6-dev"],
    "mecab-python3": ["libmecab-dev"],
    "h5py": ["libhdf5-dev"],
    "pyodbc": ["unixodbc-dev"],
}

NPM_SYSTEM_DEPS: Dict[str, List[str]] = {
    "sharp": ["libvips-dev"],
    "canvas": ["libcairo2-dev", "libjpeg-dev", "libgif-dev", "librsvg2-dev", "libpango1.0-dev"],
    "sqlite3": ["libsqlite3-dev"],
    "bcrypt": [],  # normalment build-essential és suficient
    "node-gyp": ["build-essential"],
    "node-sass": ["build-essential"],
    "better-sqlite3": ["libsqlite3-dev"],
    "robotjs": ["libxtst-dev", "libpng-dev"],
    "sodium-native": ["libsodium-dev"],
    "grpc": ["build-essential"],
}


def scan_pip_system_deps(requirements_text: str) -> List[str]:
    """Llegeix un requirements.txt i retorna deps OS necessàries."""
    deps: set[str] = set()
    for line in requirements_text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        # treu operadors, marcadors de versió, extras
        pkg = re.split(r"[=<>!~;\[ ]", line, 1)[0].strip()
        if pkg in PIP_SYSTEM_DEPS:
            deps.update(PIP_SYSTEM_DEPS[pkg])
    return sorted(deps)


def scan_npm_system_deps(package_json_text: str) -> List[str]:
    """Llegeix un package.json i retorna deps OS necessàries."""
    deps: set[str] = set()
    try:
        data = json.loads(package_json_text)
    except Exception:
        return []
    all_pkgs = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    for pkg in all_pkgs:
        name = pkg.split("/")[-1]  # trau @scope/
        if name in NPM_SYSTEM_DEPS:
            deps.update(NPM_SYSTEM_DEPS[name])
    return sorted(deps)


def check_and_warn_native_deps(root: Path) -> List[str]:
    """Escaneja tot el repo a la recerca de deps OS necessàries i retorna les que falten."""
    missing_os: set[str] = set()
    for req in root.rglob("requirements*.txt"):
        if any(part in SKIP_DIRS for part in req.parts):
            continue
        for dep in scan_pip_system_deps(read_text(req)):
            if not run_check(f"dpkg -s {dep} > /dev/null 2>&1") and not run_check(f"pkg-config --exists {dep} > /dev/null 2>&1"):
                missing_os.add(dep)
    for pj in root.rglob("package.json"):
        if any(part in SKIP_DIRS for part in pj.parts):
            continue
        for dep in scan_npm_system_deps(read_text(pj)):
            if not run_check(f"dpkg -s {dep} > /dev/null 2>&1"):
                missing_os.add(dep)
    return sorted(missing_os)


# =============================================================================
# MILLORA — Detector de serveis 3rd-party (Supabase, Firebase, Auth0, etc.)
# =============================================================================

THIRD_PARTY_SERVICES: Dict[str, Dict[str, Any]] = {
    "supabase": {
        "patterns": [r"supabase(-js)?", r"@supabase/supabase-js", r"from\s+supabase", r"create_client"],
        "secrets": ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"],
        "help_url": "https://app.supabase.com/project/_/settings/api",
        "label": "Supabase",
    },
    "firebase": {
        "patterns": [r"firebase(-admin)?", r"firebase/app", r"firebase_admin"],
        "secrets": ["FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN", "FIREBASE_PROJECT_ID", "FIREBASE_PRIVATE_KEY"],
        "help_url": "https://console.firebase.google.com/project/_/settings/general",
        "label": "Firebase",
    },
    "auth0": {
        "patterns": [r"@auth0/", r"python-auth0", r"AUTH0_DOMAIN"],
        "secrets": ["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"],
        "help_url": "https://manage.auth0.com/dashboard/",
        "label": "Auth0",
    },
    "clerk": {
        "patterns": [r"@clerk/", r"clerk-sdk"],
        "secrets": ["CLERK_PUBLISHABLE_KEY", "CLERK_SECRET_KEY"],
        "help_url": "https://dashboard.clerk.com",
        "label": "Clerk",
    },
    "stripe": {
        "patterns": [r"stripe", r"@stripe/"],
        "secrets": ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"],
        "help_url": "https://dashboard.stripe.com/apikeys",
        "label": "Stripe",
    },
    "openai": {
        "patterns": [r"\bopenai\b", r"from\s+openai"],
        "secrets": ["OPENAI_API_KEY"],
        "help_url": "https://platform.openai.com/api-keys",
        "label": "OpenAI",
    },
    "anthropic": {
        "patterns": [r"anthropic", r"from\s+anthropic"],
        "secrets": ["ANTHROPIC_API_KEY"],
        "help_url": "https://console.anthropic.com/settings/keys",
        "label": "Anthropic Claude",
    },
    "sendgrid": {
        "patterns": [r"sendgrid", r"@sendgrid/"],
        "secrets": ["SENDGRID_API_KEY"],
        "help_url": "https://app.sendgrid.com/settings/api_keys",
        "label": "SendGrid",
    },
    "twilio": {
        "patterns": [r"twilio"],
        "secrets": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
        "help_url": "https://console.twilio.com",
        "label": "Twilio",
    },
    "aws": {
        "patterns": [r"boto3", r"@aws-sdk/", r"aws-sdk"],
        "secrets": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"],
        "help_url": "https://console.aws.amazon.com/iam/home#/security_credentials",
        "label": "AWS",
    },
}


def detect_third_party_services(root: Path) -> Dict[str, Dict[str, Any]]:
    """Escaneja codi i manifests per detectar serveis 3a part usats."""
    detected: Dict[str, Dict[str, Any]] = {}
    text_blobs: List[str] = []
    for pj in root.rglob("package.json"):
        if any(part in SKIP_DIRS for part in pj.parts):
            continue
        text_blobs.append(read_text(pj))
    for req in root.rglob("requirements*.txt"):
        if any(part in SKIP_DIRS for part in req.parts):
            continue
        text_blobs.append(read_text(req))
    for py in list(root.rglob("*.py"))[:50]:
        if any(part in SKIP_DIRS for part in py.parts):
            continue
        text_blobs.append(read_text(py, max_chars=5000))
    for js in list(root.rglob("*.js"))[:30] + list(root.rglob("*.ts"))[:30]:
        if any(part in SKIP_DIRS for part in js.parts):
            continue
        text_blobs.append(read_text(js, max_chars=5000))
    combined = "\n".join(text_blobs)
    for svc_key, cfg in THIRD_PARTY_SERVICES.items():
        for pattern in cfg["patterns"]:
            if re.search(pattern, combined, flags=re.IGNORECASE):
                detected[svc_key] = cfg
                break
    return detected


def prompt_third_party_secrets(detected: Dict[str, Dict[str, Any]], existing_env: str, non_interactive: bool = False, example_real_values: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Per cada servei 3a part, avisa i demana claus (amb caché).
    Si example_real_values conté un valor real (no placeholder) per a la variable, se salta."""
    if not detected:
        return {}
    print("\n🔌 SERVEIS 3A PART DETECTATS:")
    cache = load_secrets_cache()
    resolved: Dict[str, str] = {}
    for svc_key, cfg in detected.items():
        secrets_needed = [
            s for s in cfg["secrets"]
            if s not in existing_env
            and (s not in resolved)
            and not (example_real_values and example_real_values.get(s))
        ]
        if not secrets_needed:
            print(f"   · {cfg['label']}: totes les claus ja estan al .env ✅")
            continue
        print(f"   · {cfg['label']}: necessita {', '.join(secrets_needed)}")
        print(f"     On obtenir-les: {cfg['help_url']}")
        for var in secrets_needed:
            if var in cache and cache[var]:
                resolved[var] = cache[var]
                info(f"     {var} reutilitzat de la caché")
                continue
            if non_interactive:
                warn(f"     {var} deixat buit (mode no-interactiu)")
                continue
            value = input(f"     {var} = ").strip()
            if value:
                resolved[var] = value
                cache[var] = value
                save_secrets_cache(cache)
                info(f"     {var} desat a la caché")
    return resolved




def generate_docker_compose_for_emergent(root: Path, emergent: Dict[str, Any]) -> Path:
    """Genera un docker-compose.yml unificat amb backend + frontend + mongo
    que permet arrencar tot el stack sense instal·lar res al host."""
    backend = Path(emergent["backend"])
    frontend = Path(emergent["frontend"])
    # Dockerfile backend
    be_dockerfile = backend / "Dockerfile.agent"
    be_dockerfile.write_text(textwrap.dedent("""\
        FROM python:3.11-slim
        WORKDIR /app
        RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
        COPY requirements.txt .
        RUN pip install --no-cache-dir -r requirements.txt
        COPY . .
        EXPOSE 8001
        CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
    """), encoding="utf-8")
    # Dockerfile frontend
    fe_dockerfile = frontend / "Dockerfile.agent"
    fe_dockerfile.write_text(textwrap.dedent("""\
        FROM node:20-slim
        WORKDIR /app
        RUN corepack enable && corepack prepare yarn@stable --activate
        COPY package.json ./
        COPY yarn.lock* ./
        RUN yarn install || npm install --legacy-peer-deps
        COPY . .
        EXPOSE 3000
        ENV PORT=3000
        CMD ["sh", "-c", "yarn start || npm start"]
    """), encoding="utf-8")
    # docker-compose
    services = {
        "backend": {
            "build": {"context": "./backend", "dockerfile": "Dockerfile.agent"},
            "ports": ["8001:8001"],
            "env_file": ["./backend/.env"],
            "volumes": ["./backend:/app"],
        },
        "frontend": {
            "build": {"context": "./frontend", "dockerfile": "Dockerfile.agent"},
            "ports": ["3000:3000"],
            "env_file": ["./frontend/.env"],
            "volumes": ["./frontend:/app", "/app/node_modules"],
            "depends_on": ["backend"],
        },
    }
    if emergent.get("uses_mongo"):
        services["mongo"] = {
            "image": "mongo:7",
            "ports": ["27017:27017"],
            "volumes": ["agent-mongo-data:/data/db"],
        }
        services["backend"]["depends_on"] = ["mongo"]
    compose = {
        "services": services,
        "volumes": {"agent-mongo-data": {}} if emergent.get("uses_mongo") else {},
    }
    # yaml senzill sense dependències externes
    compose_path = root / "docker-compose.agent.yml"
    compose_path.write_text(_dict_to_yaml(compose), encoding="utf-8")
    info(f"docker-compose.agent.yml generat: {compose_path}")
    # També ajustem .env backend perquè MONGO_URL apunti al servei 'mongo'
    if emergent.get("uses_mongo"):
        be_env = backend / ".env"
        existing = read_text(be_env)
        if "mongodb://localhost" in existing:
            new = existing.replace("mongodb://localhost:27017", "mongodb://mongo:27017")
            be_env.write_text(new, encoding="utf-8")
            info("MONGO_URL ajustat a mongodb://mongo:27017 per Docker")
    return compose_path


def _dict_to_yaml(data: Any, indent: int = 0) -> str:
    """YAML minimalista sense pyyaml (suficient per docker-compose)."""
    lines: List[str] = []
    pad = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(_dict_to_yaml(v, indent + 1))
            elif isinstance(v, dict):
                lines.append(f"{pad}{k}: {{}}")
            elif isinstance(v, list):
                lines.append(f"{pad}{k}: []")
            else:
                lines.append(f"{pad}{k}: {json.dumps(v) if isinstance(v, str) and any(c in v for c in ': #') else v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_dict_to_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}- {json.dumps(item) if isinstance(item, str) and any(c in item for c in ': #') else item}")
    return "\n".join(lines)


def build_dockerize_plan(root: Path, emergent: Dict[str, Any]) -> ExecutionPlan:
    compose_path = generate_docker_compose_for_emergent(root, emergent)
    notes = ["🐳 Mode --dockerize: tot en contenidors, zero instal·lació al host.",
             f"Compose file: {compose_path.name}",
             "Backend : http://localhost:8001/api/",
             "Frontend: http://localhost:3000"]
    steps = [
        CommandStep(id="dockerize-build", title="Construir imatges (backend + frontend)",
                    cwd=str(root), command=f"docker compose -f {compose_path.name} build",
                    expected_outcome="Imatges construïdes", category="install"),
        CommandStep(id="dockerize-up", title="Aixecar stack complet (backend + frontend + mongo)",
                    cwd=str(root), command=f"docker compose -f {compose_path.name} up -d",
                    expected_outcome="Contenidors en marxa", category="run", critical=False,
                    verify_port=8001, verify_url="http://localhost:8001/api/"),
    ]
    return ExecutionPlan(summary="Pla Dockerize (tot aïllat en contenidors).", steps=steps, notes=notes)


# =============================================================================
# MILLORA B — Smoke tests automàtics post-arrencada
# =============================================================================

@dataclass
class SmokeResult:
    name: str
    success: bool
    detail: str


def run_smoke_tests(emergent: Optional[Dict[str, Any]], analysis: RepoAnalysis, timeout: int = 10) -> List[SmokeResult]:
    """Executa tests mínims contra els serveis arrencats."""
    results: List[SmokeResult] = []
    urls_to_test: List[Tuple[str, str]] = []
    if emergent:
        urls_to_test.extend([
            ("Backend root /api/", "http://localhost:8001/api/"),
            ("Backend /api/health", "http://localhost:8001/api/health"),
            ("Frontend /", "http://localhost:3000/"),
        ])
    for svc in analysis.services:
        if svc.run_url and not any(svc.run_url == u for _, u in urls_to_test):
            urls_to_test.append((f"{svc.name} ({svc.framework})", svc.run_url))
    for name, url in urls_to_test:
        try:
            r = requests.get(url, timeout=timeout)
            ok = r.status_code < 500
            results.append(SmokeResult(name=name, success=ok, detail=f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(SmokeResult(name=name, success=False, detail=str(e)[:80]))
    # Optional: pytest si el backend en té
    if emergent:
        backend = Path(emergent["backend"])
        pytest_bin = backend / ".venv" / "bin" / "pytest"
        has_tests = any(backend.rglob("test_*.py")) or (backend / "tests").is_dir()
        if pytest_bin.exists() and has_tests:
            info("Executant pytest del backend (5 tests màx)...")
            proc = subprocess.run(
                f"{pytest_bin} --maxfail=1 --tb=no -q --co 2>&1 | head -20",
                shell=True, cwd=str(backend), capture_output=True, text=True, timeout=30,
            )
            results.append(SmokeResult(name="pytest collect", success=proc.returncode == 0,
                                       detail=tail_lines(proc.stdout, 5) or proc.stderr[:80]))
    return results


def print_smoke_report(results: List[SmokeResult]) -> None:
    if not results:
        return
    print("\n=== SMOKE TESTS ===")
    ok = sum(1 for r in results if r.success)
    for r in results:
        mark = "✅" if r.success else "❌"
        print(f"  {mark} {r.name:35s} · {r.detail}")
    print(f"\n  Total: {ok}/{len(results)} OK")


# =============================================================================
# END millores A / B / C
# =============================================================================


def build_emergent_plan(root: Path, emergent: Dict[str, Any]) -> ExecutionPlan:
    """Genera un pla específic per stacks Emergent (FastAPI + React + Mongo)."""
    backend = Path(emergent["backend"])
    frontend = Path(emergent["frontend"])
    steps: List[CommandStep] = []
    notes: List[str] = ["🟢 Detectat stack Emergent (FastAPI + React + MongoDB)."]
    # MongoDB via Docker (si cal)
    if emergent["uses_mongo"] and is_docker_available():
        cfg = DB_DOCKER_CONFIGS["mongodb"]
        container, image, port = cfg["container"], cfg["image"], cfg["port"]
        cmd = f"docker inspect {container} > /dev/null 2>&1 && docker start {container} || docker run -d --name {container} -p {port}:{port} {image}"
        steps.append(CommandStep(id="emergent-db-mongo", title="MongoDB (Docker)", cwd="/tmp",
                                 command=cmd, expected_outcome="Contenidor mongo en execució",
                                 category="db", critical=False, verify_port=port))
    elif emergent["uses_mongo"]:
        notes.append("⚠️  Cal MongoDB però Docker no disponible. Instal·la mongodb-server o Docker.")
    # Backend: venv + install + run
    steps.append(CommandStep(id="emergent-be-venv", title="Backend: venv",
                             cwd=str(backend), command="python3 -m venv .venv",
                             expected_outcome="Venv creat", category="install"))
    # Detect emergentintegrations (private package on CloudFront index)
    be_extra_index = ""
    be_req = backend / "requirements.txt"
    if be_req.exists():
        try:
            if "emergentintegrations" in be_req.read_text(errors="ignore").lower():
                be_extra_index = " --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/"
        except Exception:
            pass
    steps.append(CommandStep(id="emergent-be-install", title="Backend: pip install",
                             cwd=str(backend), command=f".venv/bin/pip install -r requirements.txt{be_extra_index}",
                             expected_outcome="Dependències backend instal·lades", category="install"))
    # Detect port conflicts: OpenWebUI on host often uses :3000, so React frontend
    # must shift to the next free port. Same for backend if something uses :8001.
    be_port = find_free_port(8001)
    fe_port = find_free_port(3000)
    if be_port != 8001:
        notes.append(f"ℹ️  Port 8001 ocupat, backend reassignat a :{be_port}.")
    if fe_port != 3000:
        notes.append(f"ℹ️  Port 3000 ocupat (probablement per OpenWebUI), frontend reassignat a :{fe_port}.")
    steps.append(CommandStep(id="emergent-be-run", title=f"Backend: uvicorn (port {be_port})",
                             cwd=str(backend),
                             command=f".venv/bin/uvicorn server:app --host 0.0.0.0 --port {be_port} --reload",
                             expected_outcome=f"FastAPI servint a :{be_port}", category="run", critical=False,
                             verify_port=be_port, verify_url=f"http://localhost:{be_port}/api/"))
    # Frontend: install + run
    # NODE_OPTIONS=--openssl-legacy-provider és necessari per a react-scripts < 5.0.2
    # i craco antic amb Node 17+ (OpenSSL 3.x incompatible amb webpack 4).
    # És un no-op per a react-scripts moderns → segur aplicar-ho sempre.
    # BROWSER=none evita que CRA intenti obrir el navegador (fallback en servidors headless).
    fe_env = f"NODE_OPTIONS=--openssl-legacy-provider BROWSER=none"
    # Si el backend s'ha mogut de port, cal que React apunti al nou port via REACT_APP_BACKEND_URL.
    if be_port != 8001:
        fe_env = f"REACT_APP_BACKEND_URL=http://localhost:{be_port} {fe_env}"
    has_yarn = run_check("yarn --version")
    if has_yarn:
        steps.append(CommandStep(id="emergent-fe-install", title="Frontend: yarn install",
                                 cwd=str(frontend), command="yarn install",
                                 expected_outcome="node_modules instal·lats", category="install"))
        steps.append(CommandStep(id="emergent-fe-run", title=f"Frontend: yarn start (port {fe_port})",
                                 cwd=str(frontend), command=f"{fe_env} PORT={fe_port} yarn start",
                                 expected_outcome=f"React servint a :{fe_port}", category="run", critical=False,
                                 verify_port=fe_port, verify_url=f"http://localhost:{fe_port}"))
    else:
        steps.append(CommandStep(id="emergent-fe-install", title="Frontend: npm install (legacy peer deps)",
                                 cwd=str(frontend), command="npm install --legacy-peer-deps",
                                 expected_outcome="node_modules instal·lats", category="install"))
        steps.append(CommandStep(id="emergent-fe-run", title=f"Frontend: npm start (port {fe_port})",
                                 cwd=str(frontend), command=f"{fe_env} PORT={fe_port} npm start",
                                 expected_outcome=f"React servint a :{fe_port}", category="run", critical=False,
                                 verify_port=fe_port, verify_url=f"http://localhost:{fe_port}"))
        notes.append("⚠️  Yarn no trobat. Instal·la'l (sudo npm install -g yarn) per evitar conflictes de peer deps.")
    notes.append(f"Backend: http://localhost:{be_port}  ·  Frontend: http://localhost:{fe_port}")
    notes.append("Totes les rutes backend han d'estar prefixades amb /api (ingress Emergent).")
    return ExecutionPlan(summary="Pla Emergent stack (FastAPI + React + MongoDB).", steps=steps, notes=notes)


# =============================================================================
# Registry de serveis en background (per --stop / --status)
# =============================================================================

def _registry_path(workspace: Path) -> Path:
    return workspace / SERVICES_REGISTRY


def load_services_registry(workspace: Path) -> Dict[str, Any]:
    path = _registry_path(workspace)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Neteja claus amb llista buida (herència de stops anteriors amb codi antic)
        return {k: v for k, v in data.items() if v}
    except Exception:
        return {}


def save_services_registry(workspace: Path, data: Dict[str, Any]) -> None:
    _registry_path(workspace).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def register_service(workspace: Path, repo_name: str, step_id: str, cwd: str, command: str, pid: Optional[int], log_file: str) -> None:
    data = load_services_registry(workspace)
    services = data.setdefault(repo_name, [])
    services.append({
        "step_id": step_id,
        "cwd": cwd,
        "command": command,
        "pid": pid,
        "log_file": log_file,
        "started_at": time.time(),
    })
    save_services_registry(workspace, data)


def stop_services(workspace: Path, repo_name: str = "all") -> None:
    data = load_services_registry(workspace)
    if not data:
        info("No hi ha serveis registrats.")
        return
    targets = list(data.keys()) if repo_name == "all" else [repo_name]
    stopped = 0
    for name in targets:
        for svc in data.get(name, []):
            pid = svc.get("pid")
            if not pid:
                continue
            try:
                # Intenta matar tot el process group (inclou webpack fills de yarn, etc.)
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, 15)  # SIGTERM al grup
                except Exception:
                    os.kill(pid, 15)  # fallback
                stopped += 1
                info(f"Aturat PID {pid} ({name}::{svc['step_id']})")
            except ProcessLookupError:
                pass
            except Exception as e:
                warn(f"No s'ha pogut aturar PID {pid}: {e}")
        if name in data:
            del data[name]
    save_services_registry(workspace, data)
    info(f"Total serveis aturats: {stopped}")


def show_status(workspace: Path) -> None:
    data = load_services_registry(workspace)
    if not data:
        info("Cap servei registrat.")
        return
    print("\n=== SERVEIS EN MARXA (registrats) ===")
    for repo_name, services in data.items():
        if not services:
            continue
        print(f"\n[{repo_name}]")
        for svc in services:
            pid = svc.get("pid")
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except Exception:
                    alive = False
            status = "🟢 RUNNING" if alive else "🔴 STOPPED"
            print(f"  {status}  PID={pid}  step={svc['step_id']}")
            print(f"    cmd: {svc['command']}")
            print(f"    log: {svc['log_file']}")


def analyze_repo(root: Path, model: str = DEFAULT_MODEL, extract_readme: bool = True) -> RepoAnalysis:
    real_root = maybe_promote_single_nested_root(root)
    info(f"Analitzant: {real_root}")
    analysis = RepoAnalysis(root=str(real_root), repo_name=real_root.name, top_level_manifests=[p.name for p in real_root.iterdir() if p.is_file()])
    services: List[ServiceInfo] = []
    for path in discover_candidate_dirs(real_root):
        for detector in ALL_DETECTORS:
            svc = detector(path)
            if svc:
                services.append(svc)
    unique: Dict[Tuple[str, str], ServiceInfo] = {(svc.path, svc.service_type): svc for svc in services}
    analysis.services = list(unique.values())
    analysis.env_files_present = [str(p.relative_to(real_root)) for p in real_root.rglob("*.env*") if p.is_file()]
    analysis.env_examples_present = [str(p.relative_to(real_root)) for p in find_env_examples(real_root)]
    analysis.setup_scripts_found = [str(p.relative_to(real_root)) for p in find_setup_scripts(real_root)]
    analysis.env_vars_needed = detect_env_vars_from_code(real_root)
    if extract_readme:
        analysis.readme_instructions = extract_instructions_from_readme(real_root, model)
    svc_types = {s.service_type for s in analysis.services}
    analysis.likely_fullstack = "node" in svc_types and bool(svc_types - {"node", "make", "docker"})
    db_hints = set(detect_db_hints_from_code(real_root))
    readme_low = (read_text(real_root / "README.md") + "\n" + read_text(real_root / "README_Linux.md")).lower()
    for db, kw in [("postgresql", "postgres"), ("supabase", "supabase"), ("mysql", "mysql"), ("mongodb", "mongodb"), ("redis", "redis")]:
        if kw in readme_low:
            db_hints.add(db)
    analysis.db_hints = sorted(db_hints)
    analysis.likely_db_needed = bool(analysis.db_hints)
    req_map = {"node": ["node", "npm"], "python": ["python3", "pip3"], "docker": ["docker"], "go": ["go"], "rust": ["cargo"], "ruby": ["ruby", "bundle"], "php": ["php", "composer"], "java": ["java", "mvn"], "make": ["make"]}
    needed: List[str] = ["git"]
    for svc in analysis.services:
        needed.extend(req_map.get(svc.service_type, []))
    if analysis.likely_db_needed:
        needed.append("docker")
    analysis.host_requirements = sorted(set(needed))
    analysis.missing_system_deps = check_system_dependencies(analysis.host_requirements)
    if not analysis.services:
        analysis.warnings.append("No s'ha detectat cap manifest de servei conegut.")
    return analysis


def choose_node_install_cmd(svc: ServiceInfo) -> str:
    return {"pnpm": "pnpm install", "yarn": "yarn install"}.get(svc.package_manager or "", "npm install")


def choose_node_run_cmd(svc: ServiceInfo) -> Optional[str]:
    pm = svc.package_manager or "npm"
    scripts = svc.scripts or {}
    def fmt(name: str) -> str:
        if pm == "pnpm":
            return f"pnpm {name}"
        if pm == "yarn":
            return f"yarn {name}"
        return "npm start" if name == "start" else f"npm run {name}"
    for name in ["dev", "start", "serve", "preview"]:
        if name in scripts:
            return fmt(name)
    for fallback in ["server.js", "index.js", "app.js"]:
        if (Path(svc.path) / fallback).exists():
            return f"node {fallback}"
    return None


def choose_python_install_cmds(svc: ServiceInfo) -> List[str]:
    path = Path(svc.path)
    cmds = ["python3 -m venv .venv"]
    # Emergent internal package lives on a CloudFront-hosted index. If detected,
    # add --extra-index-url so `pip install` can resolve it.
    extra_index = ""
    req_file = path / "requirements.txt"
    if req_file.exists():
        try:
            req_content = req_file.read_text(errors="ignore").lower()
            if "emergentintegrations" in req_content:
                extra_index = " --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/"
        except Exception:
            pass
        cmds.append(f".venv/bin/pip install -r requirements.txt{extra_index}")
    elif (path / "pyproject.toml").exists():
        try:
            py_content = (path / "pyproject.toml").read_text(errors="ignore").lower()
            if "emergentintegrations" in py_content:
                extra_index = " --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/"
        except Exception:
            pass
        cmds.append(f".venv/bin/pip install .{extra_index}")
    return cmds


FRAMEWORK_DEFAULT_PORTS = {
    "fastapi": 8001,
    "flask": 5000,
    "django": 8000,
    "streamlit": 8501,
    "express": 3000,
    "next": 3000,
    "vite": 5173,
    "nest": 3000,
    "react-scripts": 3000,
}


def choose_python_run_cmd(svc: ServiceInfo) -> Optional[str]:
    path = Path(svc.path)
    # Prioritat del port: (1) ports_hint detectat al codi, (2) port del run_url detectat,
    # (3) port per defecte del framework, (4) fallback 8001.
    port = None
    if svc.ports_hint:
        port = svc.ports_hint[0]
    elif svc.run_url:
        from urllib.parse import urlparse
        parsed = urlparse(svc.run_url)
        if parsed.port:
            port = parsed.port
    if port is None:
        port = FRAMEWORK_DEFAULT_PORTS.get(svc.framework or "", 8001)
    if svc.framework == "fastapi":
        for e in ["server.py", "main.py", "app.py"]:
            if (path / e).exists():
                return f".venv/bin/uvicorn {e[:-3]}:app --host 0.0.0.0 --port {port} --reload"
    if svc.framework == "flask" and (path / "app.py").exists():
        return f".venv/bin/flask --app app run --host=0.0.0.0 --port={port}"
    if svc.framework == "django" and (path / "manage.py").exists():
        return f".venv/bin/python manage.py runserver 0.0.0.0:{port}"
    if svc.framework == "streamlit":
        # v2.4 streamlit fix: ampliada llista d'entries + fallback *.py arrel
        candidates = [
            "streamlit_app.py", "Hello.py", "Home.py", "app.py", "main.py",
            "Main.py", "App.py", "streamlit_main.py", "streamlit.py",
        ]
        chosen = None
        for e in candidates:
            if (path / e).exists():
                chosen = e
                break
        if not chosen:
            roots = sorted([
                p.name for p in path.glob("*.py")
                if not p.name.lower().startswith(("test_", "conftest", "setup"))
                and p.name.lower() != "__init__.py"
            ])
            if roots:
                chosen = roots[0]
        if chosen:
            return f".venv/bin/streamlit run {chosen} --server.port {port} --server.address 0.0.0.0 --server.headless true"
    for e in ["main.py", "server.py", "app.py"]:
        if (path / e).exists():
            return f".venv/bin/python {e}"
    return None


def choose_docker_cmd(svc: ServiceInfo) -> Optional[str]:
    path = Path(svc.path)
    for compose in ["docker-compose.yml", "docker-compose.yaml", "compose.yml"]:
        if (path / compose).exists():
            return "docker compose up --build"
    if (path / "Dockerfile").exists():
        tag = slugify(path.name)
        port = svc.ports_hint[0] if svc.ports_hint else 8080
        return f"docker build -t {tag}:local . && docker run --rm -p {port}:{port} {tag}:local"
    return None


def choose_service_verify(step_command: str, svc: ServiceInfo) -> Tuple[str, Optional[int], Optional[str]]:
    verify_port = None
    verify_url = None
    command = step_command
    if svc.run_url:
        parsed = urlparse(svc.run_url)
        if parsed.port:
            free_port = find_free_port(parsed.port)
            if free_port != parsed.port:
                if svc.service_type == "node":
                    command = f"PORT={free_port} {step_command}"
                elif svc.service_type == "python":
                    # Handle multiple port flag variants used by Python web frameworks
                    new_cmd = step_command
                    # Streamlit: --server.port NNN
                    new_cmd = re.sub(r"--server\.port[=\s]+\d+", f"--server.port {free_port}", new_cmd)
                    # uvicorn / FastAPI / Flask / Django: --port NNN or -p NNN
                    new_cmd = re.sub(r"(--port|-p)[=\s]+\d+", lambda m: f"{m.group(1)} {free_port}", new_cmd)
                    # Gunicorn / generic: --bind HOST:NNN or -b HOST:NNN
                    new_cmd = re.sub(r"(--bind|-b)[=\s]+([^\s:]+):\d+", lambda m: f"{m.group(1)} {m.group(2)}:{free_port}", new_cmd)
                    if new_cmd == step_command:
                        # No known flag matched: prepend PORT env var as fallback
                        command = f"PORT={free_port} {step_command}"
                    else:
                        command = new_cmd
                svc.run_url = f"{parsed.scheme}://{parsed.hostname}:{free_port}"
            verify_url = svc.run_url
            verify_port = free_port
    return command, verify_port, verify_url


def build_deterministic_plan(analysis: RepoAnalysis) -> ExecutionPlan:
    steps: List[CommandStep] = []
    notes: List[str] = []
    root = Path(analysis.root)
    if analysis.likely_db_needed and analysis.db_hints and is_docker_available():
        db_steps, _ = build_db_provision_steps(analysis.db_hints)
        steps.extend(db_steps)
        notes.append(f"BD provisionada automàticament via Docker: {', '.join(analysis.db_hints)}.")
    elif analysis.likely_db_needed and not is_docker_available():
        notes.append("⚠️  Cal una BD però Docker no està disponible. Instal·la Docker o configura les credencials manualment al .env.")
    for script_rel in analysis.setup_scripts_found:
        step = build_setup_script_step(root / script_rel, root)
        if step:
            steps.append(step)
    root_docker = detect_docker_service(root)
    if root_docker and file_exists_any(root, ["docker-compose.yml", "docker-compose.yaml", "compose.yml"]):
        cmd = choose_docker_cmd(root_docker)
        if cmd:
            command, verify_port_num, verify_url = choose_service_verify(cmd, root_docker)
            steps.append(CommandStep(id="docker-up", title="Inicia el stack amb docker compose", cwd=str(root), command=command, expected_outcome="Tots els serveis arrenquen correctament", category="run", verify_port=verify_port_num, verify_url=verify_url))
            return ExecutionPlan(summary="Docker Compose detectat al root del repositori.", steps=steps, notes=notes)
    for svc in analysis.services:
        svc_path = Path(svc.path)
        st = svc.service_type
        if st == "node":
            steps.append(CommandStep(id=f"node-install-{slugify(svc.name)}", title=f"Instal·la dependències Node — {svc.name}", cwd=svc.path, command=choose_node_install_cmd(svc), expected_outcome="node_modules instal·lats", category="install"))
            run_cmd = choose_node_run_cmd(svc)
            if run_cmd:
                command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
                steps.append(CommandStep(id=f"node-run-{slugify(svc.name)}", title=f"Arrenca {svc.name} ({svc.framework})", cwd=svc.path, command=command, expected_outcome="Servidor Node disponible", category="run", critical=False, verify_port=verify_port_num, verify_url=verify_url))
        elif st == "python":
            for i, cmd in enumerate(choose_python_install_cmds(svc), start=1):
                steps.append(CommandStep(id=f"py-install-{slugify(svc.name)}-{i}", title=f"Prepara entorn Python — {svc.name}", cwd=svc.path, command=cmd, expected_outcome="Venv i dependències instal·lades", category="install"))
            if (svc_path / "alembic.ini").exists() or (svc_path / "alembic").exists():
                steps.append(CommandStep(id=f"py-migrate-{slugify(svc.name)}", title=f"Migracions BD — {svc.name}", cwd=svc.path, command=".venv/bin/alembic upgrade head", expected_outcome="Esquema migrat", category="migrate", critical=False))
            if (svc_path / "manage.py").exists() and svc.framework == "django":
                steps.append(CommandStep(id=f"django-migrate-{slugify(svc.name)}", title=f"Migracions Django — {svc.name}", cwd=svc.path, command=".venv/bin/python manage.py migrate", expected_outcome="BD Django migrada", category="migrate", critical=False))
            run_cmd = choose_python_run_cmd(svc)
            if run_cmd:
                command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
                steps.append(CommandStep(id=f"py-run-{slugify(svc.name)}", title=f"Arrenca {svc.name} ({svc.framework})", cwd=svc.path, command=command, expected_outcome="Servidor Python disponible", category="run", critical=False, verify_port=verify_port_num, verify_url=verify_url))
        elif st == "docker":
            run_cmd = choose_docker_cmd(svc)
            if run_cmd:
                command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
                steps.append(CommandStep(id=f"docker-run-{slugify(svc.name)}", title=f"Docker — {svc.name}", cwd=svc.path, command=command, expected_outcome="Contenidor en execució", category="run", critical=False, verify_port=verify_port_num, verify_url=verify_url))
        elif st == "go":
            # Afegir instal·lació si no hi ha go.sum
            if not (svc_path / "go.sum").exists() and (svc_path / "go.mod").exists():
                steps.append(CommandStep(id=f"go-install-{slugify(svc.name)}", title=f"Go mod download — {svc.name}", cwd=svc.path, command="go mod download", expected_outcome="Dependències Go descarregades", category="install"))
            # Entrada: main.go al root, sinó './...'
            entry = "main.go" if (svc_path / "main.go").exists() else "./..."
            run_cmd = f"go run {entry}"
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(id=f"go-run-{slugify(svc.name)}", title=f"Arrenca {svc.name} (Go)", cwd=svc.path, command=command, expected_outcome="Servidor Go disponible", category="run", critical=False, verify_port=verify_port_num, verify_url=verify_url))
        elif st == "rust":
            steps.append(CommandStep(id=f"rust-build-{slugify(svc.name)}", title=f"Cargo build — {svc.name}", cwd=svc.path, command="cargo build --release", expected_outcome="Binari compilat", category="install"))
            steps.append(CommandStep(id=f"rust-run-{slugify(svc.name)}", title=f"Cargo run — {svc.name}", cwd=svc.path, command="cargo run --release", expected_outcome="Binari en execució", category="run", critical=False))
        elif st == "ruby":
            if (svc_path / "Gemfile").exists():
                steps.append(CommandStep(id=f"ruby-install-{slugify(svc.name)}", title=f"Bundle install — {svc.name}", cwd=svc.path, command="bundle install", expected_outcome="Gemfile installed", category="install"))
            if svc.framework == "rails":
                steps.append(CommandStep(id=f"rails-db-{slugify(svc.name)}", title=f"Rails db:migrate — {svc.name}", cwd=svc.path, command="bundle exec rails db:migrate", expected_outcome="DB migrada", category="migrate", critical=False))
                steps.append(CommandStep(id=f"rails-run-{slugify(svc.name)}", title=f"Rails server — {svc.name}", cwd=svc.path, command="bundle exec rails server -b 0.0.0.0", expected_outcome="Rails a :3000", category="run", critical=False, verify_port=3000, verify_url="http://localhost:3000"))
            else:
                steps.append(CommandStep(id=f"ruby-run-{slugify(svc.name)}", title=f"Ruby run — {svc.name}", cwd=svc.path, command="bundle exec ruby main.rb" if (svc_path / "main.rb").exists() else "bundle exec ruby app.rb", expected_outcome="Script Ruby en execució", category="run", critical=False))
        elif st == "php":
            steps.append(CommandStep(id=f"php-install-{slugify(svc.name)}", title=f"Composer install — {svc.name}", cwd=svc.path, command="composer install", expected_outcome="Composer deps instal·lades", category="install"))
            if svc.framework == "laravel":
                steps.append(CommandStep(id=f"php-run-{slugify(svc.name)}", title=f"Laravel serve — {svc.name}", cwd=svc.path, command="php artisan serve --host=0.0.0.0 --port=8000", expected_outcome="Laravel a :8000", category="run", critical=False, verify_port=8000, verify_url="http://localhost:8000"))
            else:
                steps.append(CommandStep(id=f"php-run-{slugify(svc.name)}", title=f"PHP built-in server — {svc.name}", cwd=svc.path, command="php -S 0.0.0.0:8000", expected_outcome="PHP a :8000", category="run", critical=False, verify_port=8000))
        elif st == "java":
            pom = svc_path / "pom.xml"
            if pom.exists():
                steps.append(CommandStep(id=f"java-build-{slugify(svc.name)}", title=f"Maven package — {svc.name}", cwd=svc.path, command="mvn -q -DskipTests package", expected_outcome="JAR construït", category="install"))
                steps.append(CommandStep(id=f"java-run-{slugify(svc.name)}", title=f"Spring Boot run — {svc.name}", cwd=svc.path, command="mvn spring-boot:run", expected_outcome="Spring a :8080", category="run", critical=False, verify_port=8080, verify_url="http://localhost:8080"))
            else:
                steps.append(CommandStep(id=f"java-build-{slugify(svc.name)}", title=f"Gradle build — {svc.name}", cwd=svc.path, command="./gradlew build -x test", expected_outcome="Build Gradle OK", category="install"))
                steps.append(CommandStep(id=f"java-run-{slugify(svc.name)}", title=f"Gradle bootRun — {svc.name}", cwd=svc.path, command="./gradlew bootRun", expected_outcome="Spring a :8080", category="run", critical=False, verify_port=8080, verify_url="http://localhost:8080"))
        elif st == "make":
            # Intenta usar make per defecte si té un target útil
            targets = svc.entry_hints or []
            preferred = next((t for t in ["run", "start", "serve", "dev", "up"] if t in targets), None)
            if preferred:
                steps.append(CommandStep(id=f"make-{slugify(svc.name)}-{preferred}", title=f"make {preferred} — {svc.name}", cwd=svc.path, command=f"make {preferred}", expected_outcome=f"make {preferred} completat", category="run", critical=False))
    if not steps:
        notes.append("⚠️  No s'ha pogut derivar cap pla d'execució automàticament.")
    return ExecutionPlan(summary="Pla generat automàticament a partir dels manifests del repositori.", steps=steps, notes=notes)


def merge_readme_instructions(plan: ExecutionPlan, instructions: List[str], repo_root: Path) -> ExecutionPlan:
    existing_cmds = {s.command for s in plan.steps}
    for i, instr in enumerate(instructions):
        if instr.startswith(("⚠️", "📋")):
            if instr not in plan.notes:
                plan.notes.append(instr)
            continue
        try:
            validate_command(instr, repo_root=repo_root)
        except AgentError:
            plan.notes.append(f"⚠️  Instrucció del README (no automatitzable): {instr}")
            continue
        if instr in existing_cmds:
            continue
        if any(kw in instr for kw in ["install", "npm i", "pip install", "bundle install", "composer install", "go mod"]):
            cat = "install"
        elif any(kw in instr for kw in ["migrate", "alembic", "manage.py migrate"]):
            cat = "migrate"
        elif any(kw in instr for kw in ["run", "start", "dev", "serve", "up", "uvicorn", "flask run", "rails s"]):
            cat = "run"
        else:
            cat = "prepare"
        plan.steps.append(CommandStep(id=f"readme-step-{i}", title=f"Del README: {instr[:60]}", cwd=str(repo_root), command=instr, expected_outcome="Pas del README completat", critical=False, category=cat))
        existing_cmds.add(instr)
    return plan


# =============================================================================
# MILLORA V6 — LLM com a planner primari (en comptes de només refinador)
# =============================================================================

def gather_repo_context_for_llm(root: Path, max_files_per_type: int = 3, max_chars_per_file: int = 2500) -> Dict[str, Any]:
    """Recopila contingut clau del repo perquè l'LLM pugui proposar un pla intel·ligent."""
    context: Dict[str, Any] = {"root_name": root.name, "files": {}}
    readme = find_readme(root)
    if readme:
        context["files"][str(readme.relative_to(root))] = read_text(readme, max_chars=4000)
    key_files = [
        "package.json", "yarn.lock", "requirements.txt", "requirements-dev.txt",
        "pyproject.toml", "setup.py", "Pipfile", "poetry.lock",
        "Dockerfile", "Dockerfile.dev", "docker-compose.yml", "docker-compose.yaml", "compose.yml",
        "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts",
        "Makefile", "makefile", ".env.example", ".env.sample", "env.example",
        "setup.sh", "install.sh", "bootstrap.sh", "start.sh", "run.sh",
        "tsconfig.json", "next.config.js", "vite.config.js", "vite.config.ts", "turbo.json", "nx.json",
        "alembic.ini", "manage.py",
    ]
    for name in key_files:
        matches = list(root.rglob(name))[:2]
        for p in matches:
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            try:
                rel = str(p.relative_to(root))
            except ValueError:
                continue
            context["files"][rel] = read_text(p, max_chars=max_chars_per_file)
    code_patterns = {
        "python": ["server.py", "main.py", "app.py", "wsgi.py", "asgi.py"],
        "node": ["index.js", "index.ts", "server.js", "server.ts", "app.js", "app.ts"],
        "go": ["main.go"],
        "rust": ["src/main.rs"],
    }
    for lang, names in code_patterns.items():
        count = 0
        for name in names:
            for p in root.rglob(name):
                if any(part in SKIP_DIRS for part in p.parts):
                    continue
                try:
                    rel = str(p.relative_to(root))
                except ValueError:
                    continue
                if rel in context["files"]:
                    continue
                context["files"][rel] = read_text(p, max_chars=max_chars_per_file)
                count += 1
                if count >= max_files_per_type:
                    break
            if count >= max_files_per_type:
                break
    all_files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.parts):
            try:
                all_files.append(str(p.relative_to(root)))
            except ValueError:
                pass
        if len(all_files) >= 200:
            break
    context["tree_sample"] = all_files
    return context


def build_llm_primary_plan(analysis: RepoAnalysis, model: str) -> Optional[ExecutionPlan]:
    """Usa l'LLM com a planner PRIMARI. Retorna None si falla (per fallback determinista)."""
    root = Path(analysis.root)
    info(f"🤖 LLM primari llegint el repo (model: {model})...")
    context = gather_repo_context_for_llm(root)
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "notes": {"type": "array", "items": {"type": "string"}},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "cwd": {"type": "string"},
                        "command": {"type": "string"},
                        "expected_outcome": {"type": "string"},
                        "critical": {"type": "boolean"},
                        "category": {"type": "string", "enum": ["install", "migrate", "db", "run", "setup", "prepare"]},
                        "verify_url": {"type": ["string", "null"]},
                        "verify_port": {"type": ["integer", "null"]},
                    },
                    "required": ["id", "title", "cwd", "command", "expected_outcome", "critical", "category"],
                },
            },
        },
        "required": ["summary", "notes", "steps"],
    }
    system = textwrap.dedent(
        f"""
        You are an expert deployment planner for Ubuntu Linux. Given the full context of a
        repository (README, manifests, sample code, file tree), produce a complete execution
        plan that will BUILD and RUN the project locally.

        CRITICAL RULES:
        - Ubuntu 22.04 bash only. No macOS/Windows paths.
        - NEVER use: sudo, chmod 777, rm -rf /, shutdown, reboot, mkfs, curl|bash, wget|bash.
        - Python: create .venv and use .venv/bin/pip and .venv/bin/<tool> (uvicorn, flask, streamlit, pytest, ...).
        - Node: prefer 'yarn' if yarn.lock exists, else 'npm install --legacy-peer-deps'.
        - Docker Compose projects: a single 'docker compose up -d' step is usually enough.
        - 'cwd' MUST be a path RELATIVE to the repo root (like 'backend' or '.') or an absolute path.
        - Runtime commands (servers) use category 'run'. The agent will wrap them with nohup/setsid.
        - Default ports: Python backend 8001, Node frontend 3000. Only override if the repo says so.
        - If DB needed (Mongo/Postgres/MySQL/Redis): add 'db' step that 'docker run' or 'docker start' a container.
        - Set 'verify_url' or 'verify_port' on the main 'run' step.
        - If the README has concrete shell commands, prefer those.
        - Do NOT invent files. Only reference files that appear in the context.
        - Return valid JSON matching the schema. No markdown, no commentary.

        Repo root name: {context['root_name']}
        """
    ).strip()
    user_payload = {
        "analysis_summary": {
            "services_detected": [{"name": s.name, "type": s.service_type, "framework": s.framework, "path": s.path} for s in analysis.services],
            "db_hints": analysis.db_hints,
            "env_vars_needed": list(analysis.env_vars_needed.keys()),
            "likely_fullstack": analysis.likely_fullstack,
        },
        "files": context["files"],
        "tree_sample": context["tree_sample"],
    }
    try:
        proposed = ollama_chat_json(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)[:30000]},
            ],
            schema=schema,
            timeout=300,
        )
    except Exception as e:
        warn(f"LLM primari ha fallat: {e}")
        return None
    safe_steps: List[CommandStep] = []
    rejected = 0
    for raw in proposed.get("steps", []):
        cwd_val = raw.get("cwd", ".") or "."
        if not Path(cwd_val).is_absolute():
            cwd_val = str((root / cwd_val).resolve())
        raw["cwd"] = cwd_val
        try:
            validate_command(raw["command"], repo_root=root)
            valid_keys = {"id", "title", "cwd", "command", "expected_outcome", "critical", "category", "verify_url", "verify_port"}
            filtered = {k: v for k, v in raw.items() if k in valid_keys}
            safe_steps.append(CommandStep(**filtered))
        except Exception as e:
            warn(f"Descartant pas LLM insegur ({raw.get('id','?')}): {e}")
            rejected += 1
    if not safe_steps:
        warn(f"LLM primari ha proposat 0 passos vàlids ({rejected} rebutjats). Fallback determinista.")
        return None
    info(f"🤖 LLM ha proposat {len(safe_steps)} passos ({rejected} descartats per seguretat).")
    return ExecutionPlan(
        summary=proposed.get("summary", "Pla proposat per LLM primari"),
        notes=proposed.get("notes", []) + [f"🤖 Generat per {model}"],
        steps=safe_steps,
    )




def refine_plan_with_model(analysis: RepoAnalysis, plan: ExecutionPlan, model: str) -> ExecutionPlan:
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "notes": {"type": "array", "items": {"type": "string"}},
            "steps": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "cwd": {"type": "string"}, "command": {"type": "string"}, "expected_outcome": {"type": "string"}, "critical": {"type": "boolean"}, "category": {"type": "string"}, "verify_url": {"type": ["string", "null"]}, "verify_port": {"type": ["integer", "null"]}}, "required": ["id", "title", "cwd", "command", "expected_outcome", "critical", "category"]}},
        },
        "required": ["summary", "notes", "steps"],
    }
    system = textwrap.dedent(
        """
        You are a local deployment planner for Ubuntu Linux.
        Given a repo analysis and an initial execution plan, improve it conservatively:
        - keep DB provisioning, setup scripts, and verification if already present
        - prefer deterministic startup commands
        - do not use sudo and do not invent files
        - do not remove necessary backend or frontend startup steps
        - return valid JSON only following the schema
        """
    ).strip()
    try:
        refined = ollama_chat_json(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps({"analysis": asdict(analysis), "initial_plan": {"summary": plan.summary, "notes": plan.notes, "steps": [asdict(s) for s in plan.steps]}}, ensure_ascii=False, indent=2)}], schema=schema, timeout=240)
        safe_steps: List[CommandStep] = []
        for raw in refined.get("steps", []):
            try:
                validate_command(raw["command"], repo_root=Path(analysis.root))
                safe_steps.append(CommandStep(**raw))
            except Exception as e:
                warn(f"Descartant pas insegur del model ({raw.get('id', '?')}): {e}")
        if safe_steps:
            return ExecutionPlan(summary=refined.get("summary", plan.summary), notes=refined.get("notes", plan.notes), steps=safe_steps)
    except Exception as e:
        warn(f"Refinament del model ha fallat, usant pla determinista: {e}")
    return plan


def print_analysis(analysis: RepoAnalysis) -> None:
    print("\n=== ANÀLISI DEL REPOSITORI ===")
    print(f"Arrel: {analysis.root}")
    print(f"Nom: {analysis.repo_name}")
    print(f"Full-stack: {analysis.likely_fullstack}")
    print(f"Cal BD: {analysis.likely_db_needed}" + (f" ({', '.join(analysis.db_hints)})" if analysis.db_hints else ""))
    if analysis.missing_system_deps:
        print(f"⚠️  Falten: {', '.join(analysis.missing_system_deps)}")
    else:
        print("✅ Totes les dependències del sistema presents.")
    if analysis.env_vars_needed:
        print("Variables d'entorn detectades al codi:")
        for var, where in sorted(analysis.env_vars_needed.items()):
            print(f"- {var} ({where})")
    print(f"Serveis detectats ({len(analysis.services)}):")
    for svc in analysis.services:
        print(f"- {svc.name} ({svc.service_type}/{svc.framework})")
        if svc.run_url:
            print(f"  URL: {svc.run_url}")


def print_plan(plan: ExecutionPlan) -> None:
    print("\n=== PLA D'EXECUCIÓ ===")
    print(plan.summary)
    if plan.notes:
        print("Notes:")
        for note in plan.notes:
            print(f"- {note}")
    print(f"Passos ({len(plan.steps)}):")
    for i, step in enumerate(plan.steps, 1):
        print(f"{i}. [{step.category}] {step.title}")
        print(f"   cwd: {step.cwd}")
        print(f"   cmd: {step.command}")
        if step.verify_url:
            print(f"   verify: {step.verify_url}")
        elif step.verify_port:
            print(f"   verify port: {step.verify_port}")


def verify_step(step: CommandStep) -> bool:
    if step.verify_url:
        return verify_http(step.verify_url)
    if step.verify_port:
        return verify_port(step.verify_port)
    return True


def _extract_agent_pid(stdout: str) -> Optional[int]:
    match = re.search(r"__AGENT_PID__=(\d+)", stdout)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def execute_plan(analysis: RepoAnalysis, plan: ExecutionPlan, model: str, workspace: Path, approve_all: bool, dry_run: bool) -> Tuple[List[ExecutionResult], List[StepError]]:
    log_dir = workspace / LOG_DIRNAME
    results: List[ExecutionResult] = []
    errors: List[StepError] = []
    repo_root = Path(analysis.root)
    for idx, step in enumerate(plan.steps, 1):
        print(f"\n--- Step {idx}/{len(plan.steps)}: {step.title} ---")
        print(f"cwd: {step.cwd}")
        print(f"cmd: {step.command}")
        if dry_run:
            info("Dry run enabled, skipping execution.")
            continue
        if step.category == "setup" and not approve_all:
            ans = input("Aquest és un script del repo. L'executes? [s/N]: ").strip().lower()
            if ans not in {"s", "si", "y", "yes"}:
                warn("Pas omès per l'usuari.")
                continue
        elif not approve_all:
            ans = input("Execute this step? [y/N]: ").strip().lower()
            if ans not in {"y", "yes", "s", "si"}:
                warn("Step skipped by user.")
                continue
        is_background = False
        if step.category == "run":
            command_to_run, is_background = maybe_background_command(step.command)
        else:
            command_to_run = step.command
        current_result = run_shell(command_to_run, cwd=Path(step.cwd), repo_root=repo_root)
        current_result.step_id = step.id
        results.append(current_result)
        write_log(log_dir, f"{idx:02d}_{slugify(step.id)}.log", f"COMMAND: {command_to_run}\nCWD: {current_result.cwd}\nRETURNCODE: {current_result.returncode}\n\nSTDOUT:\n{current_result.stdout}\n\nSTDERR:\n{current_result.stderr}\n")
        success = current_result.returncode == 0
        # Registrar PID si és background
        if success and is_background:
            pid = _extract_agent_pid(current_result.stdout)
            register_service(
                workspace=workspace,
                repo_name=analysis.repo_name,
                step_id=step.id,
                cwd=step.cwd,
                command=step.command,
                pid=pid,
                log_file=str(Path(step.cwd) / ".agent_last_run.log"),
            )
            if pid:
                info(f"Servei en background registrat (PID={pid}).")
        if success and step.category == "run":
            success = verify_step(step)
            if not success:
                current_result.returncode = 1
                current_result.stderr += "\nVerification failed: service did not become reachable.\n"
        if success:
            info("Step succeeded.")
            continue
        warn(f"Step failed with code {current_result.returncode}.")
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from agents.debugger import IntelligentDebugger
        _debugger = IntelligentDebugger(
            model=model,
            analysis=analysis,
            workspace=workspace,
            max_repair_attempts=MAX_REPAIR_ATTEMPTS,
        )
        _repair = _debugger.repair(step, current_result, approve_all=approve_all)
        results.extend(r for r in _repair.execution_results if r is not current_result)
        errors.append(_repair.to_step_error(step))
        repaired = _repair.repaired
        if step.critical and not repaired:
            raise AgentError(f"Critical step failed: {step.title}")
    return results, errors


def print_final_summary(analysis: RepoAnalysis, plan: ExecutionPlan, results: List[ExecutionResult], errors: List[StepError], log_dir: Path) -> None:
    unrepaired = [e for e in errors if not e.repaired]
    print("\n=== RESUM FINAL ===")
    print(f"Passos totals: {len(results)}")
    print(f"Errors no reparats: {len(unrepaired)}")
    urls = sorted({svc.run_url for svc in analysis.services if svc.run_url})
    if urls:
        print("URLs:")
        for url in urls:
            print(f"- {url}")
    if analysis.db_provisioned or analysis.db_hints:
        print("BD local:")
        for db in analysis.db_provisioned or analysis.db_hints:
            cfg = DB_DOCKER_CONFIGS.get(db, {})
            if cfg:
                print(f"- {db}: {cfg.get('url_template', '')}")
    print(f"Logs: {log_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent universal de desplegament local de repositoris v5")
    parser.add_argument("--input", help="URL git, carpeta local o .zip")
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--github-token", default="", help="Token GitHub per a repos privats (HTTPS). També via env GITHUB_TOKEN")
    parser.add_argument("--gitlab-token", default="", help="Token GitLab per a repos privats (HTTPS). També via env GITLAB_TOKEN")
    parser.add_argument("--bitbucket-token", default="", help="Token Bitbucket per a repos privats (HTTPS). També via env BITBUCKET_TOKEN")
    parser.add_argument("--no-model-refine", action="store_true")
    parser.add_argument("--no-readme", action="store_true")
    parser.add_argument("--no-db-provision", action="store_true")
    parser.add_argument("--no-emergent-detect", action="store_true", help="Desactiva el detector Emergent stack (FastAPI+React+Mongo)")
    parser.add_argument("--llm-primary", action="store_true", help="v6: L'LLM llegeix el repo i proposa el pla des de zero (millor per repos desordenats, requereix Ollama). Si falla, fallback al pla determinista.")
    parser.add_argument("--dockerize", action="store_true", help="Usa Docker Compose per aïllar tot el stack (cap instal·lació al host)")
    parser.add_argument("--no-smoke", action="store_true", help="No executis smoke tests després d'arrencar")
    parser.add_argument("--non-interactive", action="store_true", help="No demanis mai inputs (secrets no trobats a la caché queden buits)")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approve-all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-env", action="store_true")
    # Gestió de serveis
    parser.add_argument("--status", action="store_true", help="Mostra els serveis registrats i el seu estat")
    parser.add_argument("--stop", default="", help="Atura serveis registrats. Ús: --stop all | --stop <repo-name>")
    parser.add_argument("--logs", default="", help="Mostra els últims logs d'un repo: --logs <repo-name>")
    parser.add_argument("--refresh", default="", help="Regenera els .env d'un repo ja clonat (útil després d'un canvi d'IP). Ús: --refresh <repo-name>")
    return parser.parse_args()


def show_logs(workspace: Path, repo_name: str, lines: int = 50) -> None:
    log_dir = workspace / LOG_DIRNAME
    repo_dir = workspace / slugify(repo_name)
    print(f"\n=== Últims {lines} logs per '{repo_name}' ===")
    # Agent logs
    if log_dir.exists():
        files = sorted(log_dir.glob(f"*{slugify(repo_name)}*"))[-5:]
        for f in files:
            print(f"\n--- {f.name} ---")
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                print("\n".join(text.splitlines()[-lines:]))
            except Exception as e:
                print(f"(error llegint: {e})")
    # .agent_last_run.log al propi repo (output dels serveis en background)
    for sub in ("", "backend", "frontend"):
        candidate = (repo_dir / sub / ".agent_last_run.log") if sub else (repo_dir / ".agent_last_run.log")
        if candidate.exists():
            print(f"\n--- {candidate} ---")
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
                print("\n".join(text.splitlines()[-lines:]))
            except Exception as e:
                print(f"(error llegint: {e})")


def refresh_repo_config(workspace: Path, repo_name: str) -> int:
    """
    Regenera els fitxers .env d'un repositori ja clonat (útil després d'un canvi d'IP
    o de configuració de xarxa). També injecta proxy CRA al package.json si és React.
    No toca dependències ni re-executa serveis — només refresca la configuració.
    L'usuari haurà de reiniciar els serveis perquè es carregui la nova configuració.
    """
    slug = slugify(repo_name)
    repo_root = workspace / slug
    if not repo_root.exists():
        # Potser el repo té un subfolder (cas típic de ZIPs): prova a baixar un nivell
        candidates = [p for p in repo_root.parent.glob(f"{slug}*") if p.is_dir()]
        if not candidates:
            err(f"No s'ha trobat el repositori '{repo_name}' a {workspace}")
            return 1
        repo_root = candidates[0]
        # Si té exactament un subdir que sembla el repo, baixem-hi
        subdirs = [p for p in repo_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if len(subdirs) == 1 and (subdirs[0] / "backend").exists():
            repo_root = subdirs[0]
    if not (repo_root / "backend").exists():
        for sub in repo_root.iterdir():
            if sub.is_dir() and not sub.name.startswith(".") and (sub / "backend").exists():
                repo_root = sub
                break
    print(f"\n🔄 Refrescant configuració de: {repo_root}")
    emergent = detect_emergent_stack(repo_root)
    if not emergent:
        err(f"El repositori no sembla un stack Emergent (no té backend/ + frontend/).")
        print(f"   Path: {repo_root}")
        return 1
    # Purgem els valors antics perquè es regenerin
    be_env = Path(emergent["backend"]) / ".env"
    fe_env = Path(emergent["frontend"]) / ".env"
    for env_file in (be_env, fe_env):
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            keep = []
            strip_keys = {"CORS_ORIGINS", "REACT_APP_BACKEND_URL", "WDS_SOCKET_PORT"}
            for line in lines:
                key = line.split("=", 1)[0].strip() if "=" in line else ""
                if key in strip_keys:
                    continue
                keep.append(line)
            env_file.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
            info(f"Netejats CORS_ORIGINS / REACT_APP_BACKEND_URL / WDS_SOCKET_PORT de {env_file}")
    prepare_emergent_env_files(repo_root, emergent, backend_port=8001)
    lan_ip = _detect_lan_ip()
    print(f"\n✅ Configuració refrescada. IP LAN detectada: {lan_ip}")
    print(f"   Backend  : {emergent['backend']}/.env")
    print(f"   Frontend : {emergent['frontend']}/.env")
    print(f"\n⚠️  Cal reiniciar els serveis perquè carreguin la nova configuració:")
    print(f"   python3 {__file__} --workspace {workspace} --stop {repo_name}")
    print(f"   python3 {__file__} --input {repo_root} --execute --approve-all --non-interactive --no-readme --no-model-refine")
    return 0


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    log_dir = workspace / LOG_DIRNAME

    # Subcomandes que no necessiten --input
    if args.status:
        ensure_workspace(workspace)
        show_status(workspace)
        return 0
    if args.stop:
        ensure_workspace(workspace)
        stop_services(workspace, repo_name=args.stop)
        return 0
    if args.logs:
        ensure_workspace(workspace)
        show_logs(workspace, args.logs)
        return 0
    if args.refresh:
        ensure_workspace(workspace)
        return refresh_repo_config(workspace, args.refresh)
    if not args.input:
        err("Cal --input (o bé --status / --stop / --logs / --refresh).")
        return 1

    try:
        ensure_workspace(workspace)
        acquired = acquire_input(
            args.input, workspace,
            github_token=args.github_token,
            gitlab_token=args.gitlab_token,
            bitbucket_token=args.bitbucket_token,
        )
        analysis = analyze_repo(acquired, model=args.model, extract_readme=not args.no_readme)
        print_analysis(analysis)

        # --- Detector Emergent prioritari ---
        emergent = None if args.no_emergent_detect else detect_emergent_stack(Path(analysis.root))
        if emergent:
            info("🟢 Emergent stack detectat — s'usarà pla específic.")
            analysis.likely_fullstack = True
            analysis.likely_db_needed = emergent["uses_mongo"]
            if emergent["uses_mongo"] and "mongodb" not in analysis.db_hints:
                analysis.db_hints.append("mongodb")

        if analysis.missing_system_deps:
            if not report_missing_deps(analysis.missing_system_deps, auto_approve=args.approve_all):
                err("Instal·la les dependències que falten i torna a executar l'agent.")
                return 1

        db_env_vars: Dict[str, str] = {}
        if analysis.likely_db_needed and not args.no_db_provision and is_docker_available():
            _, db_env_vars = build_db_provision_steps(analysis.db_hints)
            if not emergent:
                inject_db_env_vars(Path(analysis.root), db_env_vars)
            analysis.db_provisioned = analysis.db_hints[:]

        if emergent:
            prepare_emergent_env_files(Path(analysis.root), emergent)

        # === Millores universals: apliquen a TOTS els stacks, no només Emergent ===
        # 1) Avís de deps OS que falten segons requirements.txt / package.json
        missing_os = check_and_warn_native_deps(Path(analysis.root))
        if missing_os:
            print("\n⚠️  DEPENDÈNCIES DEL SISTEMA (per paquets natius):")
            for d in missing_os:
                print(f"   · {d}  → sudo apt-get install -y {d}")
            print("   Continuo igualment, però pot fallar el pip/npm install. Instal·la-les en una altra finestra si cal.")

        # 2) Detector de serveis 3a part (Supabase, Firebase, Auth0, etc.)
        third_party = detect_third_party_services(Path(analysis.root))

        # 3) Busca fitxer .env principal (per Emergent és backend/.env; altrament root/.env)
        primary_env_file = (Path(emergent["backend"]) / ".env") if emergent else (Path(analysis.root) / ".env")
        existing_env = read_text(primary_env_file) if primary_env_file.exists() else ""

        # 4) Carrega valors reals (no placeholder) del .env.example per no demanar-los per stdin
        _example_real_values: Dict[str, str] = {}
        for _ex_path in find_env_examples(Path(analysis.root)):
            for _line in read_text(_ex_path).splitlines():
                _stripped = _line.strip()
                if not _stripped or _stripped.startswith("#") or "=" not in _stripped:
                    continue
                _var, _, _val = _stripped.partition("=")
                _val = _val.strip()
                if _val:
                    _example_real_values[_var.strip()] = _val

        # 4b) Secrets coneguts detectats al codi (sempre, no només Emergent)
        secrets = prompt_and_cache_secrets(
            detected_vars=analysis.env_vars_needed,
            existing_env=existing_env,
            non_interactive=args.non_interactive or args.approve_all,
            example_real_values=_example_real_values,
        )
        # 5) Secrets de serveis 3a part (Supabase, Firebase, ...)
        tp_secrets = prompt_third_party_secrets(
            detected=third_party,
            existing_env=existing_env + "\n" + "\n".join(secrets.keys()),
            non_interactive=args.non_interactive or args.approve_all,
            example_real_values=_example_real_values,
        )
        secrets.update(tp_secrets)
        if secrets:
            inject_secrets_into_env(primary_env_file, secrets)

        if not args.skip_env and not emergent:
            env_examples = find_env_examples(Path(analysis.root))
            if env_examples or analysis.env_vars_needed:
                interactive_env_setup(Path(analysis.root), env_examples, prefilled=db_env_vars, detected_vars=analysis.env_vars_needed)

        # Plan
        if emergent and args.dockerize:
            plan = build_dockerize_plan(Path(analysis.root), emergent)
        elif args.llm_primary:
            # v6: LLM com a planner primari
            plan = build_llm_primary_plan(analysis, args.model)
            if plan is None:
                warn("LLM primari ha fallat, usant pla determinista com a fallback.")
                if emergent:
                    plan = build_emergent_plan(Path(analysis.root), emergent)
                else:
                    plan = build_deterministic_plan(analysis)
                    if analysis.readme_instructions and not args.no_readme:
                        plan = merge_readme_instructions(plan, analysis.readme_instructions, Path(analysis.root))
        elif emergent:
            plan = build_emergent_plan(Path(analysis.root), emergent)
        else:
            plan = build_deterministic_plan(analysis)
            if analysis.readme_instructions and not args.no_readme:
                plan = merge_readme_instructions(plan, analysis.readme_instructions, Path(analysis.root))
            if not args.no_model_refine:
                plan = refine_plan_with_model(analysis, plan, args.model)

        print_plan(plan)
        if args.dry_run or not args.execute:
            info("Pla generat. Afegeix --execute per instal·lar i arrencar.")
            return 0
        results, errors = execute_plan(
            analysis=analysis, plan=plan, model=args.model, workspace=workspace,
            approve_all=args.approve_all, dry_run=False,
        )
        print_final_summary(analysis, plan, results, errors, log_dir)
        # Millora B: smoke tests
        if not args.no_smoke:
            time.sleep(3)  # petita espera perquè els serveis s'estabilitzin
            smoke = run_smoke_tests(emergent, analysis)
            print_smoke_report(smoke)
        if emergent:
            print("\n🟢 Emergent stack iniciat:")
            print("   Backend : http://localhost:8001/api/")
            print("   Frontend: http://localhost:3000")
            print(f"   Per aturar: python3 {Path(__file__).name} --stop {analysis.repo_name}")
        return 0 if not any(e for e in errors if not e.repaired) else 1
    except KeyboardInterrupt:
        err("Interromput per l'usuari.")
        return 130
    except Exception as e:
        err(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
