#!/usr/bin/env python3
"""
Universal local repo deployment agent — optimized v4.

Main goals:
- Accept a local ZIP, local folder, or git URL
- Detect common stacks (Node, Python, Docker, Go, Rust, Ruby, PHP, Java, Make)
- Detect databases and environment variables from code, not only README/.env.example
- Build a conservative execution plan
- Optionally refine the plan with a local Ollama model
- Execute steps safely with logs, basic repair, port conflict handling, and service verification

Recommended local model:
    qwen2.5-coder:14b

Examples:
    python universal_repo_agent_v4.py --input ./repo.zip
    python universal_repo_agent_v4.py --input https://github.com/user/repo.git --execute
    python universal_repo_agent_v4.py --input git@github.com:org/repo.git --execute --approve-all
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


OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5-coder:14b"
DEFAULT_WORKSPACE = Path.home() / "universal-agent-workspace"
LOG_DIRNAME = ".agent_logs"
MAX_REPAIR_ATTEMPTS = 2
DEFAULT_VERIFY_TIMEOUT = 45

SAFE_COMMAND_PREFIXES = {
    "ls", "pwd", "cat", "echo", "cp", "mv", "mkdir", "rm", "find", "grep", "sed", "awk", "env", "printenv", "which", "test",
    "git", "unzip", "tar", "curl", "wget", "ss",
    "node", "npm", "npx", "yarn", "pnpm", "corepack",
    "python", "python3", "pip", "pip3", "pytest", "uvicorn", "flask", "django-admin", "alembic", "poetry",
    "docker", "docker-compose", "compose",
    "make", "go", "cargo", "ruby", "bundle", "rails", "php", "composer", "mvn", "gradle", "java",
    "bash", "sh",
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


def validate_command(command: str, repo_root: Optional[Path] = None) -> None:
    import shlex
    prefix = shlex_first_token(command)
    if prefix in {"bash", "sh"}:
        parts = shlex.split(command)
        if len(parts) < 2:
            raise AgentError("bash/sh sense argument d'script no permès")
        script_arg = parts[1]
        if repo_root:
            script_path = (repo_root / script_arg).resolve() if not Path(script_arg).is_absolute() else Path(script_arg).resolve()
            if not str(script_path).startswith(str(repo_root.resolve())):
                raise AgentError(f"Script fora del repositori no permès: {script_arg}")
    elif prefix not in SAFE_COMMAND_PREFIXES:
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


def maybe_background_command(command: str) -> str:
    markers = ["npm start", "npm run dev", "yarn start", "yarn dev", "pnpm dev", "uvicorn ", "flask ", "python manage.py runserver", "streamlit run", "rails server", "php artisan serve", "go run ", "cargo run", "docker compose up"]
    if any(marker in command for marker in markers):
        return f"nohup {command} > .agent_last_run.log 2>&1 &"
    return command


def ollama_chat_json(model: str, messages: List[Dict[str, str]], schema: Optional[Dict[str, Any]] = None, timeout: int = 180) -> Any:
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if schema is not None:
        payload["format"] = schema
    res = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
    res.raise_for_status()
    return safe_json_loads(res.json()["message"]["content"])


def is_git_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://") or value.endswith(".git") or value.startswith("git@")


def inject_github_token(url: str, token: str) -> str:
    if "github.com" in url and token and url.startswith("https://"):
        return re.sub(r"^https://github\.com", f"https://x-access-token:{token}@github.com", url)
    return url


def acquire_input(input_value: str, workspace: Path, github_token: str = "") -> Path:
    ensure_workspace(workspace)
    source = Path(input_value)
    if source.exists():
        if source.is_dir():
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
        clone_url = inject_github_token(input_value, github_token)
        info(f"Clonant {input_value} → {target}")
        result = run_shell(f"git clone {clone_url} {target}", cwd=workspace, timeout=300)
        if result.returncode != 0:
            raise AgentError(f"git clone ha fallat (codi {result.returncode}):\n{tail_lines(result.stderr, 10)}")
        info("Repositori clonat ✅")
        return target
    raise AgentError("Input no trobat. Proporciona una carpeta local, un .zip o una URL de git.")


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


def report_missing_deps(missing: List[str]) -> bool:
    if not missing:
        return True
    print("\n⚠️  DEPENDÈNCIES DEL SISTEMA QUE FALTEN:")
    for dep in missing:
        hint = SYSTEM_DEPS.get(dep, {}).get("install", f"sudo apt-get install -y {dep}")
        print(f"  • {dep:20s} -> {hint}")
    answer = input("Vols continuar igualment? [s/N]: ").strip().lower()
    return answer in {"s", "si", "y", "yes"}


def find_env_examples(root: Path) -> List[Path]:
    found: List[Path] = []
    for name in ENV_EXAMPLE_NAMES:
        found.extend(root.rglob(name))
    return found


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
            if not default or is_secret:
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


def detect_node_service(path: Path) -> Optional[ServiceInfo]:
    pkg = path / "package.json"
    if not pkg.exists():
        return None
    pkg_raw = read_text(pkg)
    try:
        pkg_data = json.loads(pkg_raw)
    except Exception:
        pkg_data = {}
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
    if ports_hint and not run_url:
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


def discover_candidate_dirs(root: Path) -> List[Path]:
    manifest_files = {"package.json", "requirements.txt", "pyproject.toml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "Makefile", "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts"}
    candidates = [root]
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
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
    if (path / "requirements.txt").exists():
        cmds.append(".venv/bin/pip install -r requirements.txt")
    elif (path / "pyproject.toml").exists():
        cmds.append(".venv/bin/pip install .")
    return cmds


def choose_python_run_cmd(svc: ServiceInfo) -> Optional[str]:
    path = Path(svc.path)
    port = svc.ports_hint[0] if svc.ports_hint else 8001
    if svc.framework == "fastapi":
        for e in ["server.py", "main.py", "app.py"]:
            if (path / e).exists():
                return f".venv/bin/uvicorn {e[:-3]}:app --host 0.0.0.0 --port {port} --reload"
    if svc.framework == "flask" and (path / "app.py").exists():
        return f".venv/bin/flask --app app run --host=0.0.0.0 --port={port}"
    if svc.framework == "django" and (path / "manage.py").exists():
        return f".venv/bin/python manage.py runserver 0.0.0.0:{port}"
    if svc.framework == "streamlit":
        for e in ["app.py", "main.py", "streamlit_app.py"]:
            if (path / e).exists():
                return f".venv/bin/streamlit run {e} --server.port {port}"
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
                elif svc.service_type == "python" and "--port " in step_command:
                    command = re.sub(r"--port\s+\d+", f"--port {free_port}", step_command)
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


def diagnose_error_with_model(model: str, step: CommandStep, result: ExecutionResult) -> str:
    schema = {"type": "object", "properties": {"diagnosis": {"type": "string"}, "likely_cause": {"type": "string", "enum": ["missing_dependency", "wrong_config", "missing_env_var", "network_error", "permission_error", "broken_repo", "wrong_version", "port_conflict", "other"]}, "can_be_fixed_automatically": {"type": "boolean"}}, "required": ["diagnosis", "likely_cause", "can_be_fixed_automatically"]}
    try:
        data = ollama_chat_json(model=model, messages=[{"role": "system", "content": "Diagnose this failed deployment command. Be concise and specific. Output JSON only."}, {"role": "user", "content": json.dumps({"command": result.command, "cwd": result.cwd, "returncode": result.returncode, "stdout": tail_lines(result.stdout, 20), "stderr": tail_lines(result.stderr, 20)}, ensure_ascii=False)}], schema=schema, timeout=60)
        return f"[{data.get('likely_cause', 'other')}] {data.get('diagnosis', 'Error desconegut')}"
    except Exception:
        return "No s'ha pogut diagnosticar l'error automàticament."


def ask_model_for_repair(model: str, analysis: RepoAnalysis, step: CommandStep, result: ExecutionResult) -> Optional[str]:
    schema = {"type": "object", "properties": {"command": {"type": "string"}, "reason": {"type": "string"}}, "required": ["command", "reason"]}
    try:
        data = ollama_chat_json(model=model, messages=[{"role": "system", "content": "Suggest ONE replacement shell command to fix this failed deployment step. Constraints: no sudo, no destructive changes, Linux only, must run in given cwd. Output JSON only."}, {"role": "user", "content": json.dumps({"failed_command": step.command, "cwd": step.cwd, "returncode": result.returncode, "stderr": tail_lines(result.stderr, 15), "stdout": tail_lines(result.stdout, 10)}, ensure_ascii=False)}], schema=schema, timeout=90)
        command = data["command"].strip().splitlines()[0]
        validate_command(command, repo_root=Path(analysis.root))
        return command
    except Exception as e:
        warn(f"Suggeriment de reparació ha fallat: {e}")
        return None


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
        command_to_run = maybe_background_command(step.command) if step.category == "run" else step.command
        current_result = run_shell(command_to_run, cwd=Path(step.cwd), repo_root=repo_root)
        current_result.step_id = step.id
        results.append(current_result)
        write_log(log_dir, f"{idx:02d}_{slugify(step.id)}.log", f"COMMAND: {command_to_run}\nCWD: {current_result.cwd}\nRETURNCODE: {current_result.returncode}\n\nSTDOUT:\n{current_result.stdout}\n\nSTDERR:\n{current_result.stderr}\n")
        success = current_result.returncode == 0
        if success and step.category == "run":
            success = verify_step(step)
            if not success:
                current_result.returncode = 1
                current_result.stderr += "\nVerification failed: service did not become reachable.\n"
        if success:
            info("Step succeeded.")
            continue
        warn(f"Step failed with code {current_result.returncode}.")
        diagnosis = diagnose_error_with_model(model, step, current_result)
        repaired = False
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            fix_cmd = ask_model_for_repair(model, analysis, step, current_result)
            if not fix_cmd:
                break
            warn(f"Repair attempt {attempt}: {fix_cmd}")
            if not approve_all:
                answer = input("Execute repair command? [y/N]: ").strip().lower()
                if answer not in {"y", "yes", "s", "si"}:
                    warn("Repair skipped by user.")
                    break
            fix_to_run = maybe_background_command(fix_cmd) if step.category == "run" else fix_cmd
            repair_result = run_shell(fix_to_run, cwd=Path(step.cwd), repo_root=repo_root)
            repair_result.step_id = step.id
            repair_result.repaired = True
            results.append(repair_result)
            write_log(log_dir, f"{idx:02d}_{slugify(step.id)}_repair{attempt}.log", f"REPAIR COMMAND: {fix_to_run}\nCWD: {repair_result.cwd}\nRETURNCODE: {repair_result.returncode}\n\nSTDOUT:\n{repair_result.stdout}\n\nSTDERR:\n{repair_result.stderr}\n")
            success = repair_result.returncode == 0
            if success and step.category == "run":
                success = verify_step(step)
                if not success:
                    repair_result.returncode = 1
                    repair_result.stderr += "\nVerification failed after repair: service did not become reachable.\n"
            if success:
                info("Repair succeeded.")
                repaired = True
                break
            current_result = repair_result
        errors.append(StepError(step_id=step.id, step_title=step.title, command=step.command, cwd=step.cwd, returncode=current_result.returncode, stdout_tail=tail_lines(current_result.stdout, 8), stderr_tail=tail_lines(current_result.stderr, 8), diagnosis=diagnosis, repaired=repaired))
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
    parser = argparse.ArgumentParser(description="Agent universal de desplegament local de repositoris v4")
    parser.add_argument("--input", required=True, help="URL git, carpeta local o .zip")
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--github-token", default="", help="Token GitHub per a repos privats (HTTPS)")
    parser.add_argument("--no-model-refine", action="store_true")
    parser.add_argument("--no-readme", action="store_true")
    parser.add_argument("--no-db-provision", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approve-all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-env", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    log_dir = workspace / LOG_DIRNAME
    try:
        ensure_workspace(workspace)
        acquired = acquire_input(args.input, workspace, github_token=args.github_token)
        analysis = analyze_repo(acquired, model=args.model, extract_readme=not args.no_readme)
        print_analysis(analysis)
        if analysis.missing_system_deps:
            if not report_missing_deps(analysis.missing_system_deps):
                err("Instal·la les dependències que falten i torna a executar l'agent.")
                return 1
        db_env_vars: Dict[str, str] = {}
        if analysis.likely_db_needed and not args.no_db_provision and is_docker_available():
            _, db_env_vars = build_db_provision_steps(analysis.db_hints)
            inject_db_env_vars(Path(analysis.root), db_env_vars)
            analysis.db_provisioned = analysis.db_hints[:]
        if not args.skip_env:
            env_examples = find_env_examples(Path(analysis.root))
            if env_examples or analysis.env_vars_needed:
                interactive_env_setup(Path(analysis.root), env_examples, prefilled=db_env_vars, detected_vars=analysis.env_vars_needed)
        plan = build_deterministic_plan(analysis)
        if analysis.readme_instructions and not args.no_readme:
            plan = merge_readme_instructions(plan, analysis.readme_instructions, Path(analysis.root))
        if not args.no_model_refine:
            plan = refine_plan_with_model(analysis, plan, args.model)
        print_plan(plan)
        if args.dry_run or not args.execute:
            info("Pla generat. Afegeix --execute per instal·lar i arrencar.")
            return 0
        results, errors = execute_plan(analysis=analysis, plan=plan, model=args.model, workspace=workspace, approve_all=args.approve_all, dry_run=False)
        print_final_summary(analysis, plan, results, errors, log_dir)
        return 0 if not any(e for e in errors if not e.repaired) else 1
    except KeyboardInterrupt:
        err("Interromput per l'usuari.")
        return 130
    except Exception as e:
        err(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
