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
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import textwrap
import time
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests

from agents.success_kb import lookup_plan, record_success

# Bartolo v6 foundation imports (Phase 1)
from bartolo.types import (
    ServiceInfo, RepoAnalysis, CommandStep, ExecutionPlan,
    StepError, ExecutionResult, SmokeResult,
)
from bartolo.exceptions import (
    AgentError, DetectorError, StepExecutionError,
    ProvisionerError, PreflightError, ValidationError,
)
from bartolo.validator import (
    validate_command, SAFE_COMMAND_PREFIXES, BLOCKED_PATTERNS,
    PROTECTED_CONTAINERS, ShellCommand,
)
from bartolo.shell import run_shell, run_check, run_check_version, maybe_background_command


OLLAMA_CHAT_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = "qwen2.5:14b"  # model instal·lat (tool calling ✅). NOT coder:14b (no suporta tools, no instal·lat)
DEFAULT_WORKSPACE = Path.home() / "universal-agent-workspace"
LOG_DIRNAME = ".agent_logs"
SERVICES_REGISTRY = ".agent_services.json"
MAX_REPAIR_ATTEMPTS = 2
DEFAULT_VERIFY_TIMEOUT = 120

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
    "docker-compose-plugin": {"check": "docker compose version", "install": "sudo apt-get install -y docker-compose-plugin"},
    "docker-compose": {"check": "docker-compose --version", "install": "sudo apt-get install -y docker-compose"},
    "make": {"check": "make --version", "install": "sudo apt-get install -y build-essential"},
    "go": {"check": "go version", "install": "sudo apt-get install -y golang-go"},
    "pnpm": {"check": "pnpm --version", "install": "npm install -g pnpm --prefix ~/.local 2>/dev/null; export PATH=$HOME/.local/bin:$PATH; pnpm --version"},
    "yarn": {"check": "yarn --version", "install": "npm install -g yarn --prefix ~/.local 2>/dev/null; export PATH=$HOME/.local/bin:$PATH; yarn --version"},
    "cargo": {"check": "PATH=$HOME/.cargo/bin:$PATH cargo --version", "install": "curl https://sh.rustup.rs -sSf | sh"},
    "ruby": {"check": "ruby --version", "install": "sudo apt-get install -y ruby"},
    "bundle": {"check": "bundle --version", "install": "gem install bundler"},
    "php": {"check": "php --version", "install": "sudo apt-get install -y php"},
    "composer": {"check": "composer --version", "install": "https://getcomposer.org/download/"},
    "java": {"check": "java -version", "install": "sudo apt-get install -y default-jdk"},
    "mvn": {"check": "mvn --version", "install": "sudo apt-get install -y maven"},
    "deno": {"check": "PATH=$HOME/.deno/bin:$PATH deno --version", "install": "curl -fsSL https://deno.land/install.sh | sh && echo 'Deno instal·lat. Afegeix ~/.deno/bin al PATH si no hi és.'"},
    "dotnet": {"check": "dotnet --version", "install": "sudo apt-get install -y dotnet-sdk-8.0"},
    "elixir": {"check": "elixir --version", "install": "sudo apt-get install -y elixir"},
    "mix": {"check": "mix --version", "install": "sudo apt-get install -y elixir"},
}

DB_DOCKER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "postgresql": {
        "image": "postgres:16-alpine",
        "container": "agent-postgres",
        "port": 5432,
        "env_vars": {"POSTGRES_USER": "agentuser", "POSTGRES_PASSWORD": "agentpass", "POSTGRES_DB": "agentdb"},
        "url_env": "DATABASE_URL",
        "alt_url_envs": ["POSTGRES_URL", "POSTGRESQL_URL", "PG_URL", "SQLALCHEMY_DATABASE_URI", "DATABASE_URI"],
        "url_template": "postgresql://agentuser:agentpass@localhost:5432/agentdb",
    },
    "mysql": {
        "image": "mysql:8",
        "container": "agent-mysql",
        "port": 3306,
        "env_vars": {"MYSQL_ROOT_PASSWORD": "agentpass", "MYSQL_DATABASE": "agentdb", "MYSQL_USER": "agentuser", "MYSQL_PASSWORD": "agentpass"},
        "url_env": "DATABASE_URL",
        "alt_url_envs": ["MYSQL_URL", "MYSQL_URI", "SQLALCHEMY_DATABASE_URI", "DATABASE_URI"],
        "url_template": "mysql://agentuser:agentpass@localhost:3306/agentdb",
    },
    "mongodb": {
        "image": "mongo:7",
        "container": "agent-mongo",
        "port": 27017,
        "env_vars": {},
        "url_env": "MONGO_URL",
        "alt_url_envs": ["MONGODB_URL", "MONGODB_URI", "MONGO_URI", "MONGODB_CONNECTION_STRING"],
        "url_template": "mongodb://localhost:27017/agentdb",
    },
    "redis": {
        "image": "redis:7-alpine",
        "container": "agent-redis",
        "port": 6379,
        "env_vars": {},
        "url_env": "REDIS_URL",
        "alt_url_envs": ["REDIS_URI", "REDISCLOUD_URL", "REDIS_TLS_URL"],
        "url_template": "redis://localhost:6379",
    },
}

# Cloud → local fallback: quan un repo necessita un servei cloud,
# provisionem l'alternativa local automàticament.
CLOUD_TO_LOCAL: Dict[str, str] = {
    "supabase": "postgresql",
    "mongodb_atlas": "mongodb",
}

README_NAMES = [
    "README.md", "README.rst", "README.txt", "README", "INSTALL.md", "INSTALL.txt", "GETTING_STARTED.md", "docs/INSTALL.md",
]

ENV_EXAMPLE_NAMES = [
    ".env.example", ".env.sample", ".env.template", ".env.local.example", ".env.development.example", "env.example", "example.env",
]

SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "target", ".agent_logs", ".next", "out",
    "__tests__", "__mocks__", "__fixtures__",
    "tests", "test", "spec", "specs",
    "fixtures", "mocks", "__snapshots__",
    "e2e", "cypress", "playwright",
}

DB_HINT_PATTERNS: Dict[str, Sequence[str]] = {
    "postgresql": [r"DATABASE_URL", r"POSTGRES", r"psycopg", r"asyncpg", r"sqlalchemy.*postgres", r"postgresql://"],
    "mysql": [r"MYSQL", r"pymysql", r"mysqlclient", r"mysql://"],
    "mongodb": [r"MONGO_URL", r"MONGODB_URL", r"MONGODB_URI", r"MONGO_URI", r"pymongo", r"motor\.motor_asyncio", r"mongodb://"],
    "redis": [r"REDIS_URL", r"redis\.Redis", r"import redis", r"redis://"],
    "supabase": [r"SUPABASE", r"supabase"],
}

ENV_VAR_PATTERNS = [
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"process\.env\.([A-Z0-9_]+)"),
]


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


_DOCKER_COMPOSE_CMD: Optional[str] = None  # cache: "docker compose" o "docker-compose"


def get_docker_compose_cmd() -> Optional[str]:
    """Detecta quin comandament Docker Compose està disponible.
    Prefereix 'docker compose' (plugin) sobre 'docker-compose' (standalone).
    El resultat es cacheja."""
    global _DOCKER_COMPOSE_CMD
    if _DOCKER_COMPOSE_CMD is not None:
        return _DOCKER_COMPOSE_CMD
    # Comprova docker compose (plugin)
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            _DOCKER_COMPOSE_CMD = "docker compose"
            return _DOCKER_COMPOSE_CMD
    except Exception:
        pass
    # Comprova docker-compose (standalone)
    try:
        r = subprocess.run(
            ["docker-compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            _DOCKER_COMPOSE_CMD = "docker-compose"
            return _DOCKER_COMPOSE_CMD
    except Exception:
        pass
    # Si no hi ha cap, usa docker compose (plugin modern) però avisa
    warn("Ni 'docker compose' ni 'docker-compose' trobats. Instal·la Docker Compose: sudo apt-get install -y docker-compose-plugin")
    _DOCKER_COMPOSE_CMD = "docker compose"
    return _DOCKER_COMPOSE_CMD


def parse_version(version_str: str) -> Tuple[int, ...]:
    """Parseja una cadena de versio a tupla d'enters. 'v20.5.1' → (20,5,1), '>=1.21' → (1,21)."""
    v = version_str.strip().lstrip("vV").lstrip("go").strip()
    v = v.lstrip("^~>=<").strip()
    parts = v.replace("-", ".").replace("_", ".").split(".")[:3]
    nums: List[int] = []
    for p in parts:
        try:
            nums.append(int(p.split("+")[0]))
        except ValueError:
            break
    return tuple(nums) if nums else ()


_RUNTIME_VERSION_FILES = {
    ".python-version": "python3",
    ".nvmrc": "node",
    ".node-version": "node",
}


def read_runtime_versions(root: Path) -> Dict[str, str]:
    """Llegeix restriccions de versio des de fitxers estandard del repo.
    Retorna dict tool_name → constraint (ex: {'python3': '3.11', 'node': '>=20'})."""
    constraints: Dict[str, str] = {}
    for filename, tool in _RUNTIME_VERSION_FILES.items():
        f = root / filename
        if f.is_file():
            v = f.read_text().strip().split("\n")[0].split("#")[0].strip()
            if v:
                constraints[tool] = v
    for f in (root / ".go-version",):
        if f.is_file():
            v = f.read_text().strip().split("\n")[0].strip()
            if v:
                constraints["go"] = v
    go_mod = root / "go.mod"
    if go_mod.is_file():
        first = go_mod.read_text().split("\n")[0].strip()
        if first.startswith("module ") or first.startswith("go "):
            for line in go_mod.read_text().split("\n")[:5]:
                line = line.strip()
                if line.startswith("go "):
                    constraints["go"] = line[3:].strip()
                    break
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            engines = data.get("engines", {})
            if isinstance(engines, dict):
                if engines.get("node"):
                    constraints["node"] = str(engines["node"])
                if engines.get("pnpm"):
                    constraints["pnpm"] = str(engines["pnpm"])
        except Exception:
            pass
    asdf = root / ".tool-versions"
    if asdf.is_file():
        for line in asdf.read_text().splitlines()[:20]:
            parts = line.strip().split()
            if len(parts) >= 2:
                tool = parts[0]
                version = parts[1]
                if tool in ("python", "python3"):
                    constraints.setdefault("python3", version)
                elif tool == "nodejs":
                    constraints.setdefault("node", version)
                elif tool in ("golang", "go"):
                    constraints.setdefault("go", version)
                elif tool not in constraints:
                    constraints[tool] = version
    return constraints


_RUNTIME_CHECK_TOOLS = {
    "python3": SYSTEM_DEPS["python3"]["check"] if "python3" in SYSTEM_DEPS else "python3 --version",
    "node": SYSTEM_DEPS.get("node", {}).get("check", "node --version"),
    "go": SYSTEM_DEPS.get("go", {}).get("check", "go version"),
    "pnpm": SYSTEM_DEPS.get("pnpm", {}).get("check", "pnpm --version"),
    "ruby": SYSTEM_DEPS.get("ruby", {}).get("check", "ruby --version"),
}


def check_runtime_versions(constraints: Dict[str, str]) -> List[str]:
    """Compara les versions requerides amb les instal·lades. Retorna warnings."""
    warnings: List[str] = []
    for tool, constraint in constraints.items():
        check_cmd = _RUNTIME_CHECK_TOOLS.get(tool)
        if not check_cmd:
            continue
        actual = run_check_version(check_cmd)
        if not actual:
            warnings.append(f"{tool}: requereix {constraint}, pero no s'ha pogut detectar la versio instal·lada")
            continue
        req = parse_version(constraint)
        cur = parse_version(actual)
        if not req or not cur:
            continue
        if cur < req:
            warnings.append(f"{tool}: requereix {constraint}, instal·lat {actual}")
    return warnings


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
            # Atura serveis en background (docker compose, uvicorn, yarn...) ABANS d'esborrar el directori.
            # Sense això, setsid+nohup fa que els builds anteriors continuïn corrents simultàniament
            # amb els nous → OOM → reinici de màquina.
            stop_services(workspace, repo_name=target.name)
            shutil.rmtree(target)
        clone_url = inject_git_token(input_value, github_token=github_token, gitlab_token=gitlab_token, bitbucket_token=bitbucket_token)
        info(f"Clonant {input_value} → {target}")
        result = run_shell(f"git clone --recurse-submodules {clone_url} {target}", cwd=workspace, timeout=300)
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


_PG_URL_RE = re.compile(
    r'DATABASE_URL\s*=\s*["\']?(postgresql|postgres)://([^:@\s]+):([^@\s]+)@(localhost|127\.0\.0\.1)[:/]?\d*/([^\s"\'?]+)'
)


def _build_pg_credentials_step(root: Path) -> Optional["CommandStep"]:
    """
    Escaneja TOTS els fitxers .env del repo (root + subdirectoris).
    Si troba un DATABASE_URL postgresql amb user/BD diferent de l'agent,
    afegeix un pas que crea aquell usuari i BD a agent-postgres.
    """
    # Cerca a root i un nivell de subdirectoris (evita node_modules, .venv, etc.)
    candidates: List[Path] = []
    for name in (".env", ".env.example", ".env.sample", ".env.template"):
        candidates.append(root / name)
        for subdir in root.iterdir():
            if subdir.is_dir() and subdir.name not in SKIP_DIRS:
                candidates.append(subdir / name)

    for env_path in candidates:
        env_text = read_text(env_path, max_chars=2000)
        m = _PG_URL_RE.search(env_text)
        if not m:
            continue
        user, password, db = m.group(2), m.group(3), m.group(5).rstrip("/")
        if user == "agentuser" and db == "agentdb":
            continue  # ja coincideix amb les de l'agent, seguim buscant
        cmd = (
            f'docker exec agent-postgres psql -U agentuser -d agentdb '
            f'-c "CREATE USER {user} WITH PASSWORD \'{password}\'" 2>/dev/null; '
            f'docker exec agent-postgres psql -U agentuser -d agentdb '
            f'-c "CREATE DATABASE {db} OWNER {user}" 2>/dev/null; true'
        )
        return CommandStep(
            id="db-create-repo-user",
            title=f"Crea l'usuari '{user}' i BD '{db}' a agent-postgres per al repo",
            cwd="/tmp",
            command=cmd,
            expected_outcome=f"Usuari {user} i BD {db} existents a agent-postgres",
            category="db",
            critical=False,
        )
    return None


def build_db_provision_steps(db_hints: List[str]) -> Tuple[List[CommandStep], Dict[str, str]]:
    steps: List[CommandStep] = []
    env_vars: Dict[str, str] = {}
    provisioned: set[str] = set()
    for db_key in db_hints:
        # Si és un servei cloud, usem el fallback local
        actual_db = CLOUD_TO_LOCAL.get(db_key, db_key)
        if actual_db in provisioned:
            continue
        cfg = DB_DOCKER_CONFIGS.get(actual_db)
        if not cfg:
            continue
        provisioned.add(actual_db)
        container = cfg["container"]
        image = cfg["image"]
        port = cfg["port"]
        env_flags = " ".join(f'-e {k}="{v}"' for k, v in cfg["env_vars"].items())
        command = f"docker inspect {container} > /dev/null 2>&1 && docker start {container} || (docker run -d --name {container} -p {port}:{port} {env_flags} {image} && sleep 3 && for i in $(seq 1 90); do nc -z localhost {port} 2>/dev/null && break; sleep 2; done)"
        display_name = f"{db_key} → {actual_db}" if db_key != actual_db else db_key
        steps.append(CommandStep(id=f"db-provision-{db_key}", title=f"Provisió automàtica de {display_name.upper()} (Docker)", cwd="/tmp", command=command, expected_outcome=f"Contenidor {actual_db} en execució al port {port}", critical=False, category="db", verify_port=port))
        env_vars[cfg["url_env"]] = cfg["url_template"]
        for alt_name in cfg.get("alt_url_envs", []):
            env_vars[alt_name] = cfg["url_template"]
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


def _install_system_dep(dep: str, non_interactive: bool = False) -> bool:
    """Intenta instal·lar una dependència del sistema amb la comanda de SYSTEM_DEPS.
    Si la comanda requereix sudo, demana la contrasenya a l'usuari (excepte non_interactive)."""
    dep_info = SYSTEM_DEPS.get(dep)
    if not dep_info:
        return False
    install_cmd = dep_info.get("install", "")
    if not install_cmd or install_cmd.startswith("http"):
        warn(f"No es pot instal·lar {dep} automàticament. Consulta: {install_cmd}")
        return False

    needs_sudo = install_cmd.strip().startswith("sudo ")
    if needs_sudo and non_interactive:
        warn(f"{dep} requereix sudo però estem en mode no-interactiu. Instal·la'l manualment: {install_cmd}")
        return False

    if needs_sudo:
        print(f"\n🔐 {dep} requereix permisos de superusuari.")
        try:
            password = getpass.getpass(f"   Contrasenya sudo per instal·lar {dep}: ")
        except (EOFError, KeyboardInterrupt):
            warn(f"No s'ha pogut llegir la contrasenya. Salta instal·lació de {dep}.")
            return False
        if not password:
            warn(f"Contrasenya buida. Salta instal·lació de {dep}.")
            return False
        # Converteix 'sudo X' a 'sudo -S X' per rebre la contrasenya per stdin
        install_cmd = install_cmd.replace("sudo ", "sudo -S ", 1)
        info(f"Instal·lant {dep} amb sudo ({install_cmd})...")
        try:
            result = subprocess.run(
                install_cmd, shell=True, timeout=120,
                input=password + "\n", text=True, capture_output=True,
            )
            if result.returncode != 0:
                stderr_tail = (result.stderr or "")[-200:]
                warn(f"Instal·lació de {dep} ha fallat (rc={result.returncode}): {stderr_tail}")
                return False
        except subprocess.TimeoutExpired:
            warn(f"Instal·lació de {dep} ha excedit el timeout (120s)")
            return False
    else:
        info(f"Instal·lant {dep} automàticament ({install_cmd})...")
        try:
            result = subprocess.run(
                install_cmd, shell=True, timeout=120,
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                warn(f"Instal·lació de {dep} ha fallat (rc={result.returncode})")
                return False
        except subprocess.TimeoutExpired:
            warn(f"Instal·lació de {dep} ha excedit el timeout (120s)")
            return False
    check_cmd = dep_info.get("check", f"which {dep}")
    if not run_check(check_cmd):
        warn(f"{dep} instal·lat però no es detecta amb '{check_cmd}'")
        return False
    info(f"{dep} instal·lat correctament")
    return True


def preflight_check(missing_deps: List[str], ports_hint: Optional[List[int]] = None,
                    auto_approve: bool = False, non_interactive: bool = False) -> bool:
    """Pre-flight check ràpid abans de generar el pla. Retorna True si OK per continuar."""
    import shutil as _shutil
    all_ok = True
    lines: List[str] = []

    # 1. Dependències del sistema
    if missing_deps:
        all_ok = False
        installed: List[str] = []
        for dep in missing_deps:
            hint = SYSTEM_DEPS.get(dep, {}).get("install", f"sudo apt-get install -y {dep}")
            if auto_approve:
                ok_result = _install_system_dep(dep, non_interactive=non_interactive)
                if ok_result:
                    installed.append(dep)
                    lines.append(f"  ✅ {dep} instal·lat automàticament")
                else:
                    lines.append(f"  ⚠️  {dep} NO s'ha pogut instal·lar → {hint}")
            else:
                lines.append(f"  ⚠️  {dep} NO instal·lat → {hint}")
        if installed and set(installed) == set(missing_deps):
            all_ok = True
    else:
        lines.append("  ✅ Dependències del sistema OK")

    # 2. Espai disc (>500MB lliures al home)
    try:
        home = Path.home()
        usage = _shutil.disk_usage(home)
        free_gb = usage.free / (1024**3)
        if free_gb < 0.5:
            all_ok = False
            lines.append(f"  ⚠️  Espai disc crític: {free_gb:.1f} GB lliures a {home}")
        else:
            lines.append(f"  ✅ Espai disc: {free_gb:.1f} GB lliures")
    except Exception:
        pass

    # 3. Ports
    if ports_hint:
        conflicts = []
        for p in ports_hint[:5]:
            if is_port_open(p):
                conflicts.append(p)
        if conflicts:
            all_ok = False
            lines.append(f"  ⚠️  Ports ocupats: {', '.join(map(str, conflicts))}")
        else:
            lines.append(f"  ✅ Ports lliures: {', '.join(map(str, ports_hint[:5]))}")

    print("\n🔍 Pre-flight check:")
    for line in lines:
        print(line)

    if not all_ok:
        print()
        if auto_approve:
            warn("auto-approve: continuant tot i els avisos.")
            return True
        answer = input("Vols continuar igualment? [S/n]: ").strip().lower()
        if answer and answer not in {"s", "si", "y", "yes"}:
            return False
    return True


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


def interactive_env_setup(root: Path, env_examples: List[Path], prefilled: Optional[Dict[str, str]] = None, detected_vars: Optional[Dict[str, str]] = None, non_interactive: bool = False) -> Dict[str, str]:
    prefilled = prefilled or {}
    detected_vars = detected_vars or {}
    all_values: Dict[str, str] = {}
    for example_path in env_examples:
        env_target = example_path.parent / ".env"
        if env_target.exists():
            if non_interactive:
                # En mode no-interactiu: no sobreescriure un .env existent
                continue
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
                elif non_interactive:
                    value = default or ""
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
    candidates = [path / n for n in ("server.py", "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "index.py", "run.py", "api.py", "database.py", "config.py", "settings.py")]
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
        entry_hints.append(f"{get_docker_compose_cmd()} up")
        confidence += 0.1
        ports_hint = detect_ports_from_text(read_text(compose_path))
    if dockerfile.exists():
        manifests.append("Dockerfile")
        entry_hints.append("docker build")
    run_url = f"http://localhost:{ports_hint[0]}" if ports_hint else None
    return ServiceInfo(name=path.name, path=str(path), service_type="docker", framework="docker", entry_hints=entry_hints, manifests=manifests, ports_hint=sorted(set(ports_hint)), confidence=min(confidence, 0.95), run_url=run_url)


def detect_go_service(path: Path) -> Optional[ServiceInfo]:
    go_mod = path / "go.mod"
    if not go_mod.exists():
        return None
    port = 8080
    # Escaneja fitxers .go propers per trobar el port real
    go_files = list(path.glob("*.go")) + list(path.glob("*/*.go"))[:5]
    for gf in go_files:
        try:
            text = gf.read_text(errors="ignore")[:4000]
            ports = detect_ports_from_text(text)
            if ports:
                port = ports[0]
                break
        except Exception:
            pass
    # També revisa .env.example si existeix
    for env_name in (".env.example", ".env.sample", ".env"):
        env_file = path / env_name
        if env_file.exists():
            try:
                ports = detect_ports_from_text(env_file.read_text(errors="ignore")[:2000])
                if ports:
                    port = ports[0]
                    break
            except Exception:
                pass
    return ServiceInfo(name=path.name, path=str(path), service_type="go", framework="go",
                       entry_hints=["go run ./...", "go build"], manifests=["go.mod"],
                       ports_hint=[port], confidence=0.75, run_url=f"http://localhost:{port}")



def detect_rust_service(path: Path) -> Optional[ServiceInfo]:
    return ServiceInfo(name=path.name, path=str(path), service_type="rust", framework="rust", entry_hints=["cargo run", "cargo build --release"], manifests=["Cargo.toml"], ports_hint=[8080], confidence=0.75) if (path / "Cargo.toml").exists() else None


def detect_ruby_service(path: Path) -> Optional[ServiceInfo]:
    if not (path / "Gemfile").exists():
        return None
    text = read_text(path / "Gemfile").lower()
    fw = "rails" if "rails" in text else "sinatra" if "sinatra" in text else "ruby"
    url = "http://localhost:3000" if fw in {"rails", "sinatra"} else None
    ports_hint = [3000] if fw in {"rails", "sinatra"} else []
    return ServiceInfo(name=path.name, path=str(path), service_type="ruby", framework=fw, entry_hints=["bundle exec rails server", "bundle exec ruby"], manifests=["Gemfile"], ports_hint=ports_hint, confidence=0.7, run_url=url)


def detect_php_service(path: Path) -> Optional[ServiceInfo]:
    if not (path / "composer.json").exists():
        return None
    text = read_text(path / "composer.json").lower()
    fw = "laravel" if "laravel" in text else "symfony" if "symfony" in text else "php"
    return ServiceInfo(name=path.name, path=str(path), service_type="php", framework=fw, entry_hints=["php artisan serve", "php -S localhost:8000"], manifests=["composer.json"], ports_hint=[8000], confidence=0.7, run_url="http://localhost:8000")


def detect_java_service(path: Path) -> Optional[ServiceInfo]:
    pom, gradle, gradk = path / "pom.xml", path / "build.gradle", path / "build.gradle.kts"
    if not pom.exists() and not gradle.exists() and not gradk.exists():
        return None
    manifests = [pom.name] if pom.exists() else [gradle.name if gradle.exists() else gradk.name]
    entry_hint = "mvn spring-boot:run" if pom.exists() else "./gradlew bootRun"
    return ServiceInfo(name=path.name, path=str(path), service_type="java", framework="spring", entry_hints=[entry_hint], manifests=manifests, ports_hint=[8080], confidence=0.7, run_url="http://localhost:8080")


def detect_makefile_service(path: Path) -> Optional[ServiceInfo]:
    makefile = path / "Makefile"
    if not makefile.exists():
        return None
    targets = re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]+)\s*:", read_text(makefile), re.MULTILINE)
    useful = [t for t in targets if t in {"run", "start", "dev", "serve", "up", "build", "install", "all", "setup"}]
    return ServiceInfo(name=path.name, path=str(path), service_type="make", framework="make", entry_hints=useful or targets[:5], manifests=["Makefile"], ports_hint=[], confidence=0.6)


def detect_monorepo_tool(path: Path) -> Optional[str]:
    """Detecta si el repo usa eines de monorepo (turbo, nx, workspaces, lerna)."""
    if (path / "turbo.json").exists():
        return "turborepo"
    if (path / "nx.json").exists():
        return "nx"
    if (path / "pnpm-workspace.yaml").exists():
        return "pnpm-workspace"
    if (path / "lerna.json").exists():
        return "lerna"
    pkg = path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            if isinstance(data.get("workspaces"), list) and data["workspaces"]:
                return "npm-workspaces"
        except Exception:
            pass
    return None


def detect_deno_service(path: Path) -> Optional[ServiceInfo]:
    """Detecta projectes Deno (deno.json, deno.jsonc, import_map.json, o .ts amb imports Deno)."""
    deno_json = path / "deno.json"
    deno_jsonc = path / "deno.jsonc"
    import_map = path / "import_map.json"
    has_manifest = deno_json.exists() or deno_jsonc.exists()
    manifests: List[str] = []
    if deno_json.exists():
        manifests.append("deno.json")
    if deno_jsonc.exists():
        manifests.append("deno.jsonc")
    if import_map.exists():
        manifests.append("import_map.json")
    # Fallback: detecta .ts/.js amb imports Deno (npm:, jsr:, https://deno.land/)
    if not has_manifest:
        ts_files = list(path.glob("*.ts")) + list(path.glob("*.js"))
        deno_imports = False
        for f in ts_files[:10]:
            try:
                content = f.read_text(errors="ignore")[:2000]
                if re.search(r'\bfrom\s+["\'](?:npm:|jsr:|https?://deno\.land/)', content):
                    deno_imports = True
                    break
            except Exception:
                pass
        if not deno_imports:
            return None
    text = ""
    try:
        if has_manifest:
            text = read_text(deno_json if deno_json.exists() else deno_jsonc)
        else:
            # Sense manifest: escaneja .ts/.js per trobar el port real
            for f in ts_files[:5]:
                try:
                    text = f.read_text(errors="ignore")[:3000]
                    if re.search(r'\b(?:PORT|port|listen)\s*[:=]\s*\d{4,5}', text):
                        break
                except Exception:
                    pass
    except Exception:
        pass
    ports = detect_ports_from_text(text)
    run_url = f"http://localhost:{ports[0]}" if ports else "http://localhost:8001"
    # Si no té manifest, busca el millor entry point per als hints
    entry_hints = ["deno run -A main.ts", "deno task start"]
    if not has_manifest:
        for candidate in ("server.ts", "main.ts", "index.ts", "app.ts", "mod.ts"):
            if (path / candidate).exists():
                entry_hints[0] = f"deno run -A {candidate}"
                break
    return ServiceInfo(name=path.name, path=str(path), service_type="deno", framework="deno",
                       entry_hints=entry_hints, manifests=manifests,
                       ports_hint=ports, confidence=0.65 if has_manifest else 0.4,
                       run_url=run_url)


def detect_elixir_service(path: Path) -> Optional[ServiceInfo]:
    """Detecta projectes Elixir/Phoenix (mix.exs)."""
    mix_exs = path / "mix.exs"
    if not mix_exs.exists():
        return None
    try:
        text = read_text(mix_exs).lower()
    except Exception:
        text = ""
    fw = "phoenix" if "phoenix" in text else "elixir"
    ports = detect_ports_from_text(text)
    run_url = f"http://localhost:{ports[0]}" if ports else "http://localhost:4000" if fw == "phoenix" else None
    return ServiceInfo(name=path.name, path=str(path), service_type="elixir", framework=fw,
                       entry_hints=["mix phx.server" if fw == "phoenix" else "mix run --no-halt"],
                       manifests=["mix.exs"], ports_hint=ports, confidence=0.75, run_url=run_url)


def detect_dotnet_service(path: Path) -> Optional[ServiceInfo]:
    """Detecta projectes .NET (*.csproj, *.fsproj, *.sln)."""
    csproj = list(path.glob("*.csproj"))
    fsproj = list(path.glob("*.fsproj"))
    sln = list(path.glob("*.sln"))
    if not csproj and not fsproj and not sln:
        return None
    manifests = [p.name for p in csproj + fsproj + sln]
    project_file = (csproj or fsproj)[0] if (csproj or fsproj) else None
    text = ""
    if project_file:
        try:
            text = read_text(project_file).lower()
        except Exception:
            pass
    is_web = any(kw in text for kw in ("microsoft.aspnetcore", "web", 'sdk="microsoft.net.sdk.web"'))
    fw = "aspnet" if is_web else "dotnet"
    ports = detect_ports_from_text(text)
    run_url = f"http://localhost:{ports[0]}" if ports else "http://localhost:5000" if is_web else None
    return ServiceInfo(name=path.name, path=str(path), service_type="dotnet", framework=fw,
                       entry_hints=["dotnet run", "dotnet watch run"],
                       manifests=manifests, ports_hint=ports, confidence=0.7, run_url=run_url)


ALL_DETECTORS = [detect_node_service, detect_python_service, detect_docker_service, detect_go_service, detect_rust_service, detect_ruby_service, detect_php_service, detect_java_service, detect_makefile_service, detect_deno_service, detect_elixir_service, detect_dotnet_service]


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


_COLLECTION_README_PATTERNS = re.compile(
    r"^#\s*Awesome\s|A curated list of|##\s*Table of Contents|##\s*Contents",
    re.IGNORECASE | re.MULTILINE,
)

_TOOL_REPO_NAMES: set[str] = {
    "turborepo", "turbo", "lerna", "nx", "deno", "phoenix",
}

_TOOL_MARKER_FILES: set[str] = {
    "turbo.json", "pnpm-workspace.yaml", "lerna.json",
}

_RUNNABLE_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "go.mod",
    "Cargo.toml", "mix.exs", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "Gemfile", "Makefile", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "compose.yml",
    "deno.json", "deno.jsonc",
}


def classify_repo_type(root: Path) -> str:
    """Classifica el repositori abans d'escanejar serveis.

    Retorna: 'collection', 'documentation', 'tool', 'library', 'monorepo', 'unknown', 'application'
    """
    name = root.name.lower()
    readme = root / "README.md"
    readme_text = read_text(readme, max_chars=3000) if readme.exists() else ""

    # 1. Collection / awesome-list
    if name.startswith("awesome-") or (readme_text and _COLLECTION_README_PATTERNS.search(readme_text)):
        return "collection"

    # 2. Documentation: pocs manifests, molts .md. Mirem fins a 2 nivells de profunditat
    # (monorepos multi-servei tipus microservices-demo tenen manifests a src/*/package.json)
    top_files = list(root.glob("*"))
    top_manifests = [m for m in _RUNNABLE_MANIFESTS if (root / m).exists()]
    sub_manifests: List[Path] = []
    for d in root.iterdir():
        if d.is_dir() and d.name not in SKIP_DIRS:
            for m in _RUNNABLE_MANIFESTS:
                if (d / m).exists():
                    sub_manifests.append(d / m)
            for sd in d.iterdir():
                if sd.is_dir() and sd.name not in SKIP_DIRS:
                    for m in _RUNNABLE_MANIFESTS:
                        if (sd / m).exists():
                            sub_manifests.append(sd / m)
    has_runnable = bool(top_manifests) or bool(sub_manifests)
    md_count = sum(1 for f in top_files if f.suffix == ".md")
    if not has_runnable and md_count >= 5:
        return "documentation"

    # 2.5. Tool/runtime/framework repo (abans de library check)
    if name in _TOOL_REPO_NAMES:
        return "tool"
    tool_markers = any((root / m).exists() for m in _TOOL_MARKER_FILES)
    other_markers = any((root / m).exists() for m in _RUNNABLE_MANIFESTS if m not in _TOOL_MARKER_FILES)
    if tool_markers and not other_markers:
        return "tool"

    # 3. Library (només si el manifest principal NO és runnable)
    if is_library_package_root(root):
        return "library"
    pkg = root / "package.json"
    other_runnable = any((root / m).exists() for m in _RUNNABLE_MANIFESTS if m != "package.json")
    if pkg.exists() and not other_runnable:
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            if is_node_library(data):
                return "library"
        except Exception:
            pass

    # 4. Monorepo
    if detect_monorepo_tool(root):
        return "monorepo"

    # 5. Unknown: cap manifest executable a root ni subdirectoris
    if not has_runnable:
        return "unknown"

    return "application"


MAX_CANDIDATES = 60


def _parse_pnpm_workspace_packages(root: Path) -> List[str]:
    """Extreu la llista de globs de packages d'un pnpm-workspace.yaml."""
    ws = root / "pnpm-workspace.yaml"
    if not ws.exists():
        return []
    globs: List[str] = []
    in_packages = False
    for line in ws.read_text().splitlines():
        stripped = line.strip()
        if re.match(r'^packages\s*:', stripped):
            in_packages = True
            continue
        if in_packages:
            m = re.match(r'\s*[-*]\s+["\']?([^"\'\s#]+)', line)
            if m:
                globs.append(m.group(1))
            elif stripped and not stripped.startswith('#') and not stripped.startswith('-'):
                if not line.startswith('  ') and not line.startswith('\t'):
                    break
    return globs


def _expand_workspace_globs(root: Path, globs: List[str]) -> Set[Path]:
    """Expandeix globs de workspace a un set de directoris concrets existents."""
    dirs: Set[Path] = set()
    for g in globs:
        if g.startswith('!'):
            continue
        if '/' not in g:
            p = root / g
            if p.is_dir():
                dirs.add(p)
        elif g.endswith('/*'):
            parent = root / g[:-2]
            if parent.is_dir():
                dirs.add(parent)
                for child in parent.iterdir():
                    if child.is_dir() and child.name not in SKIP_DIRS:
                        dirs.add(child)
        elif '*' in g:
            # Cas: "crates/*/js"
            idx = g.index('*')
            prefix = g[:idx].rstrip('/')
            suffix = g[idx+1:].lstrip('/')
            parent = root / prefix
            if parent.is_dir():
                for child in parent.iterdir():
                    if child.is_dir() and child.name not in SKIP_DIRS:
                        target = child / suffix if suffix else child
                        if target.is_dir():
                            dirs.add(target)
        elif '/' in g:
            p = root / g
            if p.is_dir():
                dirs.add(p)
    return dirs


def _get_monorepo_workspace_dirs(root: Path) -> Optional[Set[Path]]:
    """Calcula el set de directoris permesos per a un monorepo.
    Retorna None si no es pot determinar (s'usa depth limit com a fallback)."""
    globs = _parse_pnpm_workspace_packages(root)
    if not globs:
        pkg = root / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(errors="ignore"))
                ws = data.get("workspaces")
                if isinstance(ws, list) and ws:
                    globs = [str(w) for w in ws]
            except Exception:
                pass
    if not globs:
        lerna = root / "lerna.json"
        if lerna.exists():
            try:
                data = json.loads(lerna.read_text(errors="ignore"))
                pkgs = data.get("packages")
                if isinstance(pkgs, list) and pkgs:
                    globs = [str(p) for p in pkgs]
            except Exception:
                pass
    if not globs:
        return None
    dirs = _expand_workspace_globs(root, globs)
    dirs.add(root)
    return dirs


_TEST_FILE_PATTERNS = (
    ".test.", ".spec.", "_test.", "_spec.", "test.", "spec.",
    ".fixture.", ".mock.", ".snap.",
)


def _is_test_or_fixture_file(filename: str) -> bool:
    return any(pat in filename for pat in _TEST_FILE_PATTERNS)


def discover_candidate_dirs(root: Path) -> List[Path]:
    manifest_files = {"package.json", "requirements.txt", "pyproject.toml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "Makefile", "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts", "turbo.json", "nx.json", "pnpm-workspace.yaml", "lerna.json", "deno.json", "deno.jsonc", "mix.exs"}
    is_library = is_library_package_root(root)
    is_monorepo = detect_monorepo_tool(root) is not None
    allowed_dirs = _get_monorepo_workspace_dirs(root) if is_monorepo else None
    candidates: List[Path] = [root]
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if is_library:
            rel = Path(current_root).relative_to(root)
            if rel.parts and rel.parts[0] in EXAMPLE_DIRS:
                dirs[:] = []
                continue
        if is_monorepo:
            cur = Path(current_root)
            if allowed_dirs is not None:
                if cur not in allowed_dirs:
                    # No és workspace. Comprovem si és ancestre d'algun workspace.
                    is_ancestor = False
                    cur_s = str(cur) + os.sep
                    for ad in allowed_dirs:
                        if str(ad).startswith(cur_s):
                            is_ancestor = True
                            break
                    if not is_ancestor:
                        dirs[:] = []
                elif cur != root:
                    # És workspace. Si no té fills workspace, és fulla → no descendim.
                    cur_s = str(cur) + os.sep
                    has_children = any(str(ad).startswith(cur_s) for ad in allowed_dirs if ad != cur)
                    if not has_children:
                        dirs[:] = []
            else:
                # Fallback: límit de profunditat 2
                depth = len(Path(current_root).relative_to(root).parts)
                if depth >= 2:
                    dirs[:] = []
        effective_files = {f for f in files if not _is_test_or_fixture_file(f)}
        if effective_files & manifest_files:
            candidates.append(Path(current_root))
            if len(candidates) >= MAX_CANDIDATES:
                break
    if len(candidates) >= MAX_CANDIDATES:
        warn(f"discover_candidate_dirs: {len(candidates)}+ candidats trobats, limitant a {MAX_CANDIDATES} (monorepo={is_monorepo})")
    seen: set[str] = set()
    result: List[Path] = []
    for p in sorted(candidates, key=lambda x: len(str(x))):
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result[:MAX_CANDIDATES]


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
    _dc = get_docker_compose_cmd()
    steps = [
        CommandStep(id="dockerize-build", title="Construir imatges (backend + frontend)",
                    cwd=str(root), command=f"{_dc} -f {compose_path.name} build",
                    expected_outcome="Imatges construïdes", category="install"),
        CommandStep(id="dockerize-up", title="Aixecar stack complet (backend + frontend + mongo)",
                    cwd=str(root), command=f"{_dc} -f {compose_path.name} up -d",
                    expected_outcome="Contenidors en marxa", category="run", critical=False,
                    verify_port=8001, verify_url="http://localhost:8001/api/"),
    ]
    return ExecutionPlan(summary="Pla Dockerize (tot aïllat en contenidors).", steps=steps, notes=notes)


# =============================================================================
# MILLORA B — Smoke tests automàtics post-arrencada
# =============================================================================

def _framework_endpoints(svc) -> List[str]:
    """Retorna endpoints canònics segons el framework del servei."""
    fw = (svc.framework or "").lower()
    if fw == "fastapi":
        return ["/", "/api/", "/api/health", "/docs", "/health"]
    if fw == "flask":
        return ["/", "/health", "/api/health"]
    if fw in ("express", "next"):
        return ["/", "/api/", "/api/health"]
    if fw == "spring":
        return ["/", "/health", "/actuator/health"]
    if fw in ("aspnet", "dotnet"):
        return ["/", "/health"]
    return ["/"]


def run_smoke_tests(emergent: Optional[Dict[str, Any]], analysis: RepoAnalysis, timeout: int = 10) -> List[SmokeResult]:
    """Executa tests mínims contra els serveis arrencats, adaptant endpoints al framework."""
    results: List[SmokeResult] = []
    tested_urls: set = set()

    if emergent:
        for name, url in [("Backend root /api/", "http://localhost:8001/api/"),
                           ("Backend /api/health", "http://localhost:8001/api/health"),
                           ("Frontend /", "http://localhost:3000/")]:
            tested_urls.add(url)
            try:
                r = requests.get(url, timeout=timeout)
                results.append(SmokeResult(name=name, success=r.status_code < 500, detail=f"HTTP {r.status_code}"))
            except Exception as e:
                results.append(SmokeResult(name=name, success=False, detail=str(e)[:80]))

    for svc in analysis.services:
        if not svc.run_url:
            continue
        endpoints = _framework_endpoints(svc)[:3]
        for ep in endpoints:
            url = f"{svc.run_url.rstrip('/')}{ep}" if ep.startswith("/") else f"{svc.run_url.rstrip('/')}/{ep}"
            if url in tested_urls:
                continue
            tested_urls.add(url)
            try:
                r = requests.get(url, timeout=timeout)
                ok = r.status_code < 500
                results.append(SmokeResult(name=f"{svc.name} {ep}", success=ok, detail=f"HTTP {r.status_code}"))
                if r.status_code < 400:
                    break  # primer OK ja valida el servei
            except Exception as e:
                results.append(SmokeResult(name=f"{svc.name} {ep}", success=False, detail=str(e)[:80]))

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
    # Also create .logs/<step_id>.pid for bridge visibility
    if pid:
        repo_path = Path(cwd)
        logs_dir = repo_path / ".logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        pid_file = logs_dir / f"{step_id}.pid"
        pid_file.write_text(str(pid))


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
            # Clean up .logs/<step_id>.pid file
            if svc.get("step_id") and svc.get("cwd"):
                pid_file = Path(svc["cwd"]) / ".logs" / f"{svc['step_id']}.pid"
                try:
                    pid_file.unlink(missing_ok=True)
                except Exception:
                    pass
        if name in data:
            del data[name]
    save_services_registry(workspace, data)
    info(f"Total serveis aturats: {stopped}")


def _backup_env_files(root: Path) -> Dict[str, str]:
    """Còpia .env → .env.agent-backup per poder restaurar en cas d'error."""
    backups: Dict[str, str] = {}
    for env_file in root.rglob(".env"):
        env_path = str(env_file)
        backup_path = str(env_file) + ".agent-backup"
        try:
            shutil.copy2(env_path, backup_path)
            backups[env_path] = backup_path
        except Exception:
            pass
    return backups


def _execute_rollback(analysis, workspace: Path) -> List[str]:
    """Orquestra neteja en cas d'error: atura processos, contenidors BD, restaura .env."""
    cleaned: List[str] = []
    # 1) Atura processos del repo
    try:
        stop_services(workspace, analysis.repo_name)
        cleaned.append(f"Processos aturats per {analysis.repo_name}")
    except Exception as e:
        cleaned.append(f"Error aturant processos: {e}")
    # 2) Atura contenidors BD provisionats
    for db_key in getattr(analysis, "db_provisioned", []) or []:
        cfg = DB_DOCKER_CONFIGS.get(db_key, {})
        container = cfg.get("container", "")
        if container:
            try:
                subprocess.run(f"docker stop {container}", shell=True, capture_output=True, timeout=15)
                cleaned.append(f"Contenidor BD aturat: {container}")
            except Exception as e:
                cleaned.append(f"Error aturant contenidor {container}: {e}")
    # 3) Restaura .env des de backups
    root = Path(analysis.root)
    for env_file in root.rglob(".env.agent-backup"):
        original = Path(str(env_file).replace(".agent-backup", ""))
        try:
            shutil.copy2(str(env_file), str(original))
            env_file.unlink()
            cleaned.append(f".env restaurat: {original}")
        except Exception as e:
            cleaned.append(f"Error restaurant {original}: {e}")
    if cleaned:
        info("Rollback executat: " + "; ".join(cleaned))
    return cleaned


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
    analysis.repo_type = classify_repo_type(real_root)
    services: List[ServiceInfo] = []
    if analysis.repo_type in ("collection", "documentation", "tool"):
        if analysis.repo_type == "tool":
            analysis.warnings.append(
                "El repo sembla una eina/runtime/framework, no una aplicació desplegable."
            )
        else:
            analysis.warnings.append(
                f"El repo sembla un recull ({analysis.repo_type}), no una aplicació ejecutable."
            )
    else:
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
    # E1: Detecció de monorepo
    analysis.monorepo_tool = detect_monorepo_tool(real_root)
    if analysis.monorepo_tool:
        analysis.warnings.append(
            f"Monorepo detectat ({analysis.monorepo_tool}) — cada package es tracta com a servei independent."
        )
    db_hints = set(detect_db_hints_from_code(real_root))
    readme_low = (read_text(real_root / "README.md") + "\n" + read_text(real_root / "README_Linux.md")).lower()
    for db, kw in [("postgresql", "postgres"), ("supabase", "supabase"), ("mysql", "mysql"), ("mongodb", "mongodb"), ("redis", "redis")]:
        if kw in readme_low:
            db_hints.add(db)
    analysis.db_hints = sorted(db_hints)
    # Cloud → local: per cada servei cloud detectat, afegim l'alternativa local
    cloud_services = [db for db in analysis.db_hints if db in CLOUD_TO_LOCAL]
    for cloud_db in cloud_services:
        local_db = CLOUD_TO_LOCAL[cloud_db]
        if local_db not in db_hints:
            db_hints.add(local_db)
            analysis.db_hints = sorted(db_hints)
    analysis.cloud_services = cloud_services
    analysis.likely_db_needed = bool(analysis.db_hints)
    req_map = {"node": ["node", "npm"], "python": ["python3", "pip3"], "docker": ["docker"], "go": ["go"], "rust": ["cargo"], "ruby": ["ruby", "bundle"], "php": ["php", "composer"], "java": ["java", "mvn"], "make": ["make"], "deno": ["deno"], "elixir": ["elixir", "mix"], "dotnet": ["dotnet"]}
    needed: List[str] = ["git"]
    for svc in analysis.services:
        needed.extend(req_map.get(svc.service_type, []))
        pm = getattr(svc, "package_manager", None)
        if pm and pm in SYSTEM_DEPS:
            needed.append(pm)
    if analysis.likely_db_needed:
        needed.append("docker")
    analysis.host_requirements = sorted(set(needed))
    analysis.missing_system_deps = check_system_dependencies(analysis.host_requirements)
    analysis.runtime_version_warnings = check_runtime_versions(read_runtime_versions(real_root))
    if not analysis.services:
        analysis.warnings.append("No s'ha detectat cap manifest de servei conegut.")
    return analysis


def _detect_root_package_manager(root: Path) -> str:
    """Detecta el package manager del root per a workspace install."""
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def choose_node_install_cmd(svc: ServiceInfo, monorepo_tool: Optional[str] = None) -> str:
    pm = svc.package_manager or "npm"
    if monorepo_tool:
        # Workspace-level install al root del monorepo
        if monorepo_tool in ("turborepo", "pnpm-workspace"):
            return "pnpm install -r"
        if monorepo_tool == "npm-workspaces":
            return "npm install -ws"
        if monorepo_tool == "lerna":
            return "npx lerna bootstrap"
        if monorepo_tool == "nx":
            if pm == "pnpm":
                return "pnpm install -r"
            if pm == "yarn":
                return "yarn install"
            return "npm install -ws"
    # Per-servei: instal·la només les dependencies del package concret
    return {"pnpm": "pnpm install", "yarn": "yarn install"}.get(pm, "npm install")


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
            return f"{get_docker_compose_cmd()} up --build"
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
                st = svc.service_type
                if st == "python":
                    new_cmd = step_command
                    # Streamlit: --server.port NNN
                    new_cmd = re.sub(r"--server\.port[=\s]+\d+", f"--server.port {free_port}", new_cmd)
                    # uvicorn / FastAPI / Flask / Django: --port NNN or -p NNN
                    new_cmd = re.sub(r"(--port|-p)[=\s]+\d+", lambda m: f"{m.group(1)} {free_port}", new_cmd)
                    # Gunicorn / generic: --bind HOST:NNN or -b HOST:NNN
                    new_cmd = re.sub(r"(--bind|-b)[=\s]+([^\s:]+):\d+", lambda m: f"{m.group(1)} {m.group(2)}:{free_port}", new_cmd)
                    if new_cmd == step_command:
                        command = f"PORT={free_port} {step_command}"
                    else:
                        command = new_cmd
                elif st == "php":
                    # php artisan serve --port NNN / php -S HOST:NNN
                    new_cmd = re.sub(r"(--port[=\s]+)\d+", f"\\g<1>{free_port}", step_command)
                    new_cmd = re.sub(r"(-S[=\s]+[\w.]+):\d+", f"\\g<1>:{free_port}", new_cmd)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "ruby":
                    # rails server -p NNN / bundle exec ruby app.rb -p NNN
                    new_cmd = re.sub(r"(--port|-p)[=\s]+\d+", f"\\g<1> {free_port}", step_command)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "elixir":
                    # mix phx.server uses PORT env; mix run --no-halt uses PORT env
                    command = f"PORT={free_port} {step_command}"
                elif st == "go":
                    # Go apps typically read PORT or use -port flag
                    new_cmd = re.sub(r"(--port|-p)[=\s]+\d+", f"\\g<1> {free_port}", step_command)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "java":
                    # Spring Boot: --server.port=NNN / Gradle: -Dserver.port=NNN
                    new_cmd = re.sub(r"--server\.port[=\s]+\d+", f"--server.port={free_port}", step_command)
                    new_cmd = re.sub(r"-Dserver\.port=\d+", f"-Dserver.port={free_port}", new_cmd)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "dotnet":
                    # ASP.NET: --urls http://HOST:NNN
                    new_cmd = re.sub(r"--urls[=\s]+https?://[^:]+:\d+", f"--urls http://localhost:{free_port}", step_command)
                    command = new_cmd if new_cmd != step_command else f"ASPNETCORE_URLS=http://localhost:{free_port} {step_command}"
                else:
                    # node, deno, rust, make, docker, i qualsevol altre: PORT env var genèrica
                    command = f"PORT={free_port} {step_command}"
                svc.run_url = f"{parsed.scheme}://{parsed.hostname}:{free_port}"
            verify_url = svc.run_url
            verify_port = free_port
    return command, verify_port, verify_url


def build_deterministic_plan(analysis: RepoAnalysis) -> ExecutionPlan:
    # A3: Consulta la KB d'èxits — si aquest stack ja té un pla validat, reutilitza'l
    if analysis.services:
        kb_service_type = "+".join(sorted(set(s.service_type for s in analysis.services)))
        kb_manifests = sorted(set(m for s in analysis.services for m in s.manifests))
        cached = lookup_plan(kb_service_type, kb_manifests, analysis.repo_name)
        if cached:
            steps = [CommandStep(**s) for s in cached]
            return ExecutionPlan(
                summary=f"Pla reutilitzat de la KB d'èxits ({len(steps)} passos validats)",
                steps=steps,
                notes=[f"Stack {kb_service_type} — pla validat per execucions anteriors."],
            )
    steps: List[CommandStep] = []
    notes: List[str] = []
    root = Path(analysis.root)
    if analysis.likely_db_needed and analysis.db_hints and is_docker_available():
        db_steps, _ = build_db_provision_steps(analysis.db_hints)
        steps.extend(db_steps)
        notes.append(f"BD provisionada automàticament via Docker: {', '.join(analysis.db_hints)}.")
        if "postgresql" in analysis.db_hints:
            cred_step = _build_pg_credentials_step(root)
            if cred_step:
                steps.append(cred_step)
    elif analysis.likely_db_needed and not is_docker_available():
        notes.append("⚠️  Cal una BD però Docker no està disponible. Instal·la Docker o configura les credencials manualment al .env.")
    for script_rel in analysis.setup_scripts_found:
        script_dir = (root / script_rel).parent
        # Pre-pas: copia .env.example → .env si no existeix ja,
        # evita que setup.sh pregunti interactivament si sobreescriure
        for env_ex_name in (".env.example", ".env.sample", ".env.template", "env.example"):
            env_ex = script_dir / env_ex_name
            env_target = script_dir / ".env"
            if env_ex.exists() and not env_target.exists():
                rel_ex = env_ex.relative_to(root)
                rel_tg = env_target.relative_to(root)
                steps.append(CommandStep(
                    id=f"env-copy-{slugify(str(rel_tg))}",
                    title=f"Copia {rel_ex} → {rel_tg}",
                    cwd=str(root),
                    command=f"cp {rel_ex} {rel_tg}",
                    expected_outcome=".env creat des de l'exemple",
                    category="install", critical=False,
                ))
                break
        step = build_setup_script_step(root / script_rel, root)
        if step:
            steps.append(step)
    root_docker = detect_docker_service(root)
    if root_docker and file_exists_any(root, ["docker-compose.yml", "docker-compose.yaml", "compose.yml"]):
        # No afegir docker-up si un setup script (start.sh, run.sh...) ja crida docker compose
        # internament: evita 2 builds docker simultanis que causen OOM.
        script_runs_docker = False
        for s in analysis.setup_scripts_found:
            content = read_text(root / s, max_chars=4000)
            if "docker compose up" in content or "docker-compose up" in content:
                script_runs_docker = True
                break
        if not script_runs_docker:
            cmd = choose_docker_cmd(root_docker)
            if cmd:
                command, verify_port_num, verify_url = choose_service_verify(cmd, root_docker)
                steps.append(CommandStep(id="docker-up", title="Inicia el stack amb docker compose", cwd=str(root), command=command, expected_outcome="Tots els serveis arrenquen correctament", category="run", verify_port=verify_port_num, verify_url=verify_url))
        return ExecutionPlan(summary="Docker Compose detectat al root del repositori.", steps=steps, notes=notes)
    # Orquestració de monorepo: instal·la workspace al root abans dels passos per servei
    if analysis.monorepo_tool:
        root_pm = _detect_root_package_manager(root)
        root_install = choose_node_install_cmd(
            ServiceInfo(name=analysis.repo_name, path=str(root), service_type="node",
                        package_manager=root_pm),
            monorepo_tool=analysis.monorepo_tool,
        )
        steps.append(CommandStep(
            id="monorepo-root-install",
            title=f"Instal·la workspace del monorepo ({analysis.monorepo_tool})",
            cwd=str(root), command=root_install,
            expected_outcome=f"Dependències workspace instal·lades via {root_pm}",
            category="install",
        ))
        notes.append(
            f"Monorepo {analysis.monorepo_tool}: instal·lació workspace al root + "
            "passos per servei independents."
        )
    for svc in analysis.services:
        svc_path = Path(svc.path)
        st = svc.service_type
        if st == "node":
            steps.append(CommandStep(id=f"node-install-{slugify(svc.name)}", title=f"Instal·la dependències Node — {svc.name}", cwd=svc.path, command=choose_node_install_cmd(svc), expected_outcome="node_modules instal·lats", category="install"))
            # Build step: si package.json té script "build", executar-lo abans de run
            build_cmd = None
            scripts = svc.scripts or {}
            pm = svc.package_manager or "npm"
            if "build" in scripts:
                build_cmd = {"pnpm": "pnpm build", "yarn": "yarn build"}.get(pm, "npm run build")
            elif svc.framework == "next" and "build" not in scripts:
                build_cmd = "npx next build"
            if build_cmd:
                steps.append(CommandStep(id=f"node-build-{slugify(svc.name)}",
                    title=f"Build — {svc.name}", cwd=svc.path, command=build_cmd,
                    expected_outcome="Build completat", category="install"))
            # Migrations Node: Prisma, Knex, Sequelize
            if (svc_path / "prisma" / "schema.prisma").exists():
                steps.append(CommandStep(id=f"prisma-migrate-{slugify(svc.name)}",
                    title=f"Prisma migrate — {svc.name}", cwd=svc.path,
                    command="npx prisma migrate deploy",
                    expected_outcome="BD migrada (Prisma)", category="migrate", critical=False))
            if (svc_path / "knexfile.js").exists() or (svc_path / "knexfile.ts").exists():
                steps.append(CommandStep(id=f"knex-migrate-{slugify(svc.name)}",
                    title=f"Knex migrate — {svc.name}", cwd=svc.path,
                    command="npx knex migrate:latest",
                    expected_outcome="BD migrada (Knex)", category="migrate", critical=False))
            if (svc_path / ".sequelizerc").exists():
                steps.append(CommandStep(id=f"sequelize-migrate-{slugify(svc.name)}",
                    title=f"Sequelize migrate — {svc.name}", cwd=svc.path,
                    command="npx sequelize-cli db:migrate",
                    expected_outcome="BD migrada (Sequelize)", category="migrate", critical=False))
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
                steps.append(CommandStep(id=f"php-migrate-{slugify(svc.name)}", title=f"Artisan migrate — {svc.name}", cwd=svc.path, command="php artisan migrate --force", expected_outcome="BD migrada (Artisan)", category="migrate", critical=False))
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
        elif st == "deno":
            # Llegeix les tasks del deno.json per trobar la millor comanda
            run_cmd = "deno run -A main.ts"  # fallback
            deno_json_path = svc_path / "deno.json"
            if deno_json_path.exists():
                try:
                    deno_cfg = json.loads(deno_json_path.read_text(errors="ignore"))
                    tasks = deno_cfg.get("tasks", {}) if isinstance(deno_cfg, dict) else {}
                    if tasks and isinstance(tasks, dict):
                        # Preferim start > dev > serve > run > demo > qualsevol
                        for preferred in ("start", "dev", "serve", "run", "demo"):
                            if preferred in tasks:
                                run_cmd = f"deno task {preferred}"
                                break
                        else:
                            first = next(iter(tasks.keys()))
                            run_cmd = f"deno task {first}"
                except Exception:
                    pass
            else:
                # Sense deno.json: busca el millor entry point .ts
                for candidate in ("server.ts", "main.ts", "index.ts", "app.ts", "mod.ts"):
                    if (svc_path / candidate).exists():
                        run_cmd = f"deno run -A {candidate}"
                        break
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(id=f"deno-run-{slugify(svc.name)}", title=f"Deno run — {svc.name}", cwd=svc.path, command=command, expected_outcome="Servidor Deno disponible", category="run", critical=False, verify_port=verify_port_num, verify_url=verify_url))
        elif st == "elixir":
            steps.append(CommandStep(id=f"elixir-deps-{slugify(svc.name)}", title=f"Mix deps.get — {svc.name}", cwd=svc.path, command="mix deps.get", expected_outcome="Dependències Elixir instal·lades", category="install"))
            run_cmd = "mix phx.server" if svc.framework == "phoenix" else "mix run --no-halt"
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(id=f"elixir-run-{slugify(svc.name)}", title=f"Elixir run — {svc.name}", cwd=svc.path, command=command, expected_outcome="Servidor Elixir disponible", category="run", critical=False, verify_port=verify_port_num, verify_url=verify_url))
        elif st == "dotnet":
            steps.append(CommandStep(id=f"dotnet-restore-{slugify(svc.name)}", title=f"dotnet restore — {svc.name}", cwd=svc.path, command="dotnet restore", expected_outcome="Paquets NuGet restaurats", category="install"))
            run_cmd = "dotnet watch run" if svc.framework == "aspnet" else "dotnet run"
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(id=f"dotnet-run-{slugify(svc.name)}", title=f"dotnet run — {svc.name}", cwd=svc.path, command=command, expected_outcome="Servidor .NET disponible", category="run", critical=False, verify_port=verify_port_num, verify_url=verify_url))
    if not steps:
        manifests = analysis.top_level_manifests or []
        lib_manifests = [m for m in manifests if m in ("package.json", "setup.py", "setup.cfg", "pyproject.toml",
                        "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml")]
        if lib_manifests and not analysis.services:
            notes.append(f"ℹ️  El repo sembla una llibreria/package ({', '.join(lib_manifests)}), no una aplicació executable."
                         f"\n   Si és una app, cal un manifest de servei addicional (Dockerfile, Procfile, start.sh...).")
        else:
            notes.append("⚠️  No s'ha pogut derivar cap pla d'execució automàticament.")
    # Reordena: install/migrate/setup abans de run (crític per monorepos)
    _CATEGORY_ORDER = {"db": -1, "install": 0, "migrate": 1, "setup": 2, "configure": 3, "run": 4, "verify": 5}
    steps.sort(key=lambda s: _CATEGORY_ORDER.get(getattr(s, "category", "run"), 99))
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
    if analysis.warnings:
        for w in analysis.warnings:
            print(f"⚠️  {w}")
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


_FALLBACK_MAP: Dict[str, List[str]] = {
    "pnpm install": ["npm install", "npm install --legacy-peer-deps"],
    "pnpm dev": ["npm run dev"],
    "pnpm start": ["npm start"],
    "pnpm build": ["npm run build"],
    "go mod download": ["go version", "go env GOPATH"],
    "yarn install": ["npm install", "npm install --legacy-peer-deps"],
    "yarn dev": ["npm run dev"],
    "yarn start": ["npm start"],
    "pip install -r requirements.txt": ["pip install --break-system-packages -r requirements.txt"],
}


def _get_fallbacks(step: CommandStep, result: ExecutionResult) -> List[str]:
    """Retorna llista de comandaments alternatius a provar abans del debugger LLM."""
    cmd_key = step.command.strip()
    # Match exacte
    if cmd_key in _FALLBACK_MAP:
        return _FALLBACK_MAP[cmd_key]
    # Match per prefix (ex: "pnpm install --frozen-lockfile" → fallback de "pnpm install")
    for key, fbs in _FALLBACK_MAP.items():
        if cmd_key.startswith(key):
            return fbs
    # Fallback genèric per error 127 (command not found)
    if result.returncode == 127 and cmd_key.startswith("pnpm"):
        return ["npm install", "npm install --legacy-peer-deps"]
    if result.returncode == 127 and cmd_key.startswith("yarn"):
        return ["npm install"]
    return []


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
        if success and step.category in ("run", "db"):
            success = verify_step(step)
            if not success:
                current_result.returncode = 1
                current_result.stderr += "\nVerification failed: service did not become reachable.\n"
        if success:
            info("Step succeeded.")
            continue
        warn(f"Step failed with code {current_result.returncode}.")
        # Plan B ràpid: alternatives predefinides abans del debugger LLM
        repaired = False
        fallbacks = _get_fallbacks(step, current_result)
        for fb_cmd in fallbacks:
            info(f"Plan B: provant '{fb_cmd}'...")
            fb_result = run_shell(fb_cmd, cwd=Path(step.cwd), repo_root=repo_root)
            results.append(fb_result)
            if fb_result.returncode == 0:
                info(f"Plan B OK: '{fb_cmd}' ha funcionat.")
                repaired = True
                break
            else:
                warn(f"Plan B també ha fallat (rc={fb_result.returncode}).")
        if repaired:
            continue
        # Si el plan B falla, escala al debugger LLM
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
            _execute_rollback(analysis, workspace)
            raise AgentError(f"Critical step failed: {step.title}")
    # A3: Registra el pla a la KB d'èxits si tots els passos han funcionat
    if results and not dry_run and not [e for e in errors if not e.repaired]:
        try:
            if analysis.services:
                kb_service_type = "+".join(sorted(set(s.service_type for s in analysis.services)))
                kb_manifests = sorted(set(m for s in analysis.services for m in s.manifests))
                record_success(kb_service_type, kb_manifests, [asdict(s) for s in plan.steps], analysis.repo_name)
        except Exception:
            pass  # Un fallo de KB mai ha de blocar un desplegament
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
    if analysis.cloud_services:
        import shutil as _shutil
        print("\n☁️  Serveis cloud detectats → alternativa local provisionada:")
        for cloud_db in analysis.cloud_services:
            local_db = CLOUD_TO_LOCAL.get(cloud_db, cloud_db)
            cfg = DB_DOCKER_CONFIGS.get(local_db, {})
            if cloud_db == "supabase":
                print(f"  Supabase → PostgreSQL local (Supabase és PostgreSQL + Auth + Storage)")
                if cfg:
                    print(f"    Per usar Supabase cloud: defineix SUPABASE_URL i SUPABASE_ANON_KEY al .env")
            elif cloud_db == "mongodb_atlas":
                print(f"  MongoDB Atlas → MongoDB local")
                if cfg:
                    print(f"    Per usar MongoDB Atlas: defineix MONGODB_URI_ATLAS al .env")
    if analysis.db_provisioned or analysis.db_hints:
        import shutil as _shutil
        print("BD local:")
        for db in analysis.db_provisioned or analysis.db_hints:
            # Els cloud services es mostren a la secció superior, aquí mostrem la BD real
            actual_db = CLOUD_TO_LOCAL.get(db, db)
            cfg = DB_DOCKER_CONFIGS.get(actual_db, {})
            if not cfg:
                continue
            env = cfg.get("env_vars", {})
            label = db
            if db in CLOUD_TO_LOCAL:
                label = f"{db} (→ {CLOUD_TO_LOCAL[db]} local)"
            print(f"\n  {label}")
            print(f"     Contenidor: {cfg['container']}")
            print(f"     Host:      localhost:{cfg['port']}")
            if "POSTGRES_USER" in env:
                print(f"     Usuari:    {env['POSTGRES_USER']}")
                print(f"     Password:  {env['POSTGRES_PASSWORD']}")
                print(f"     BD:        {env['POSTGRES_DB']}")
            elif "MYSQL_USER" in env:
                print(f"     Usuari:    {env['MYSQL_USER']}")
                print(f"     Password:  {env['MYSQL_PASSWORD']}")
                print(f"     BD:        {env['MYSQL_DATABASE']}")
            print(f"     URL:       {cfg['url_template']}")
            if db == "postgresql":
                user = env.get("POSTGRES_USER", "agentuser")
                bd = env.get("POSTGRES_DB", "agentdb")
                print(f"     Connecta:  docker exec -it {cfg['container']} psql -U {user} -d {bd}")
                if _shutil.which("psql"):
                    print(f"     O:         psql {cfg['url_template']}")
            elif db == "mysql":
                user = env.get("MYSQL_USER", "agentuser")
                bd = env.get("MYSQL_DATABASE", "agentdb")
                pw = env.get("MYSQL_PASSWORD", "agentpass")
                print(f"     Connecta:  docker exec -it {cfg['container']} mysql -u {user} -p{pw} {bd}")
                if _shutil.which("mysql"):
                    print(f"     O:         mysql {cfg['url_template']}")
            elif db == "mongodb":
                print(f"     Connecta:  docker exec -it {cfg['container']} mongosh")
                if _shutil.which("mongosh"):
                    print(f"     O:         mongosh {cfg['url_template']}")
            elif db == "redis":
                print(f"     Connecta:  docker exec -it {cfg['container']} redis-cli")
                if _shutil.which("redis-cli"):
                    print(f"     O:         redis-cli -u {cfg['url_template']}")
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
        # Per stacks no-Emergent: si té start.sh, stop + restart
        start_sh = repo_root / "start.sh"
        if start_sh.exists():
            info(f"Stack no-Emergent detectat. Reiniciant via start.sh...")
            subprocess.run(["bash", str(start_sh), "stop"], cwd=str(repo_root),
                           capture_output=True)
            stop_services(workspace, repo_name)
            r = subprocess.run(["bash", str(start_sh)], cwd=str(repo_root))
            return r.returncode
        err(f"El repositori no és Emergent (FastAPI+React+Mongo) ni té start.sh.")
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

        # Pre-flight check: deps + ports + disk (abans de generar pla)
        svc_ports = [p for s in analysis.services for p in (s.ports_hint or [])]
        if not preflight_check(analysis.missing_system_deps, ports_hint=svc_ports or None,
                               auto_approve=args.approve_all,
                               non_interactive=args.non_interactive):
            return 1

        # Backup .env abans de modificar (rollback)
        _backup_env_files(Path(analysis.root))

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

        # 1.5) Versions runtime: avisa si .python-version /.nvmrc / go.mod demana versió superior
        if analysis.runtime_version_warnings:
            print("\n⚠️  VERSIONS RUNTIME (el repo demana una versió més recent):")
            for w in analysis.runtime_version_warnings:
                print(f"   · {w}")
            print("   Continuo igualment, però pot fallar. Instal·la la versió requerida si cal.")

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
                interactive_env_setup(Path(analysis.root), env_examples, prefilled=db_env_vars, detected_vars=analysis.env_vars_needed, non_interactive=args.non_interactive or args.approve_all)

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
        # B4: Guia post-desplegament (per a tots els stacks)
        print(f"\n📁 Fitxer .env: {primary_env_file}")
        if db_env_vars:
            print("🗄️  Variables de BD injectades:")
            for k, v in db_env_vars.items():
                print(f"   {k}={v}")
        if emergent:
            print("\n🟢 Emergent stack iniciat:")
            print("   Backend : http://localhost:8001/api/")
            print("   Frontend: http://localhost:3000")
            if analysis.db_provisioned:
                for db in analysis.db_provisioned:
                    cfg = DB_DOCKER_CONFIGS.get(db, {})
                    if cfg:
                        print(f"   {db}: {cfg.get('url_template', '')}")
            print(f"   Per aturar: python3 {Path(__file__).name} --stop {analysis.repo_name}")
        return 0 if not any(e for e in errors if not e.repaired) else 1
    except KeyboardInterrupt:
        err("Interromput per l'usuari.")
        return 130
    except Exception as e:
        err(str(e))
        try:
            if 'analysis' in locals() and 'workspace' in locals():
                _execute_rollback(analysis, workspace)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
