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

# Bartolo v6 Phase 2 imports
from bartolo.planner import (
    build_deterministic_plan, build_emergent_plan, merge_readme_instructions,
    build_setup_script_step, find_readme, FRAMEWORK_DEFAULT_PORTS,
)
from bartolo.llm import ollama_chat_json, safe_json_loads, OLLAMA_CHAT_URL, DEFAULT_MODEL
from bartolo.reporter import print_analysis, print_plan, print_final_summary
from bartolo.executor import (
    execute_plan, verify_step, register_service, stop_services,
    load_services_registry, save_services_registry,
    _backup_env_files, _execute_rollback,
)
from bartolo.preflight import (
    SYSTEM_DEPS, preflight_check, check_system_dependencies,
    report_missing_deps, _install_system_dep,
)
from bartolo.runtime import (
    read_runtime_versions, check_runtime_versions, parse_version,
)
from bartolo.shell import is_port_open, find_free_port, verify_http, verify_port
from bartolo.provisioner import (
    DB_DOCKER_CONFIGS, CLOUD_TO_LOCAL, build_db_provision_steps,
    inject_db_env_vars, is_docker_available, slugify, _build_pg_credentials_step,
)
from bartolo.smoke import _framework_endpoints, run_smoke_tests, print_smoke_report
from bartolo.detectors import ALL_DETECTORS
from bartolo.detectors.discovery import (
    SKIP_DIRS, detect_ports_from_text, read_text, is_node_library,
    is_library_package_root, classify_repo_type, detect_monorepo_tool,
    discover_candidate_dirs,
)


DEFAULT_WORKSPACE = Path.home() / "universal-agent-workspace"
LOG_DIRNAME = ".agent_logs"
SERVICES_REGISTRY = ".agent_services.json"
MAX_REPAIR_ATTEMPTS = 2
DEFAULT_VERIFY_TIMEOUT = 120

SETUP_SCRIPT_NAMES = [
    "setup.sh", "install.sh", "bootstrap.sh", "init.sh", "start.sh", "run.sh", "dev.sh", "build.sh", "setup.py", "Makefile",
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


def write_log(log_dir: Path, name: str, content: str) -> Path:
    path = log_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def tail_lines(text: str, n: int = 12) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:]) if lines else ""


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


_PG_URL_RE = re.compile(
    r'DATABASE_URL\s*=\s*["\']?(postgresql|postgres)://([^:@\s]+):([^@\s]+)@(localhost|127\.0\.0\.1)[:/]?\d*/([^\s"\'?]+)'
)


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


EXAMPLE_DIRS = {"examples", "example", "demo", "demos", "samples", "sample", "tutorials", "tutorial", "docs", "documentation"}


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


MAX_CANDIDATES = 60


_TEST_FILE_PATTERNS = (
    ".test.", ".spec.", "_test.", "_spec.", "test.", "spec.",
    ".fixture.", ".mock.", ".snap.",
)


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
    "MONGODB_URI_ATLAS", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_DB_PASSWORD",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "HUGGINGFACE_API_KEY", "FAL_KEY",
    "ENCRYPTION_KEY",
}

# Claus que es poden generar automàticament — no secrets a demanar a l'usuari
AUTO_GENERATED_KEYS = {
    "ENCRYPTION_KEY",      # Fernet: cryptography.fernet.Fernet.generate_key()
    "JWT_SECRET",          # JWT: secrets.token_urlsafe(32)
    "SECRET_KEY",          # Django/Flask: secrets.token_urlsafe(32)
    "DJANGO_SECRET_KEY",   # Django: secrets.token_urlsafe(32)
    "NEXTAUTH_SECRET",     # NextAuth: openssl rand -base64 32
}

# Claus que l'app gestiona internament (admin panel, Supabase) — no secrets a demanar
SELF_CONFIGURED_KEYS = {
    "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_BUSINESS_ACCOUNT_ID", "WHATSAPP_API_URL", "WHATSAPP_APP_SECRET",
}

# Variables de configuració amb defaults, no secrets
NON_SECRET_CONFIG_KEYS = {
    "BASE_URL", "CORS_ORIGINS", "NODE_ENV", "REACT_APP_BACKEND_URL",
    "PORT", "HOST", "DEBUG", "LOG_LEVEL", "API_URL", "BACKEND_URL",
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
        "secrets": ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY"],
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


# =============================================================================
# END millores A / B / C
# =============================================================================


# =============================================================================
# Registry de serveis en background (per --stop / --status)
# =============================================================================


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


# =============================================================================
# MILLORA V6 — LLM com a planner primari (en comptes de només refinador)
# =============================================================================



if __name__ == "__main__":
    from bartolo.cli import main
    raise SystemExit(main())
