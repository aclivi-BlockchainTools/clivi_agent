"""Provisionament de bases de dades via Docker + variables d'entorn."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bartolo.shell import run_check
from bartolo.types import CommandStep

# Configuració de contenidors Docker per a cada BD suportada
DB_DOCKER_CONFIGS = {
    "mongodb": {
        "image": "mongo:7",
        "container": "agent-mongo",
        "port": 27017,
        "env_vars": {},
        "url_env": "MONGO_URL",
        "alt_url_envs": ["MONGODB_URL", "MONGODB_URI", "MONGO_URI", "MONGODB_CONNECTION_STRING"],
        "url_template": "mongodb://localhost:27017/agentdb",
    },
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
    "redis": {
        "image": "redis:7-alpine",
        "container": "agent-redis",
        "port": 6379,
        "env_vars": {},
        "url_env": "REDIS_URL",
        "alt_url_envs": ["REDIS_URI", "REDISCLOUD_URL", "REDIS_TLS_URL"],
        "url_template": "redis://localhost:6379/0",
    },
}

CLOUD_TO_LOCAL = {
    "supabase": "postgresql",
    "mongodb_atlas": "mongodb",
}

HEALTH_CHECK_SLEEP = 3
_HEALTH_CHECK_ITERATIONS = 90
_HEALTH_CHECK_INTERVAL = 2

_PG_URL_RE = re.compile(
    r'DATABASE_URL\s*=\s*["\']?(postgresql|postgres)://([^:@\s]+):([^@\s]+)@(localhost|127\.0\.0\.1)[:/]?\d*/([^\s"\'?]+)'
)


def slugify(value: str) -> str:
    import re as _re
    value = value.strip().lower()
    value = _re.sub(r"[^a-z0-9._-]+", "-", value)
    value = _re.sub(r"-+", "-", value).strip("-")
    return value


def is_docker_available() -> bool:
    return run_check("docker info")


def build_db_provision_steps(db_hints: List[str]) -> Tuple[List[CommandStep], Dict[str, str]]:
    steps: List[CommandStep] = []
    env_vars: Dict[str, str] = {}
    for hint in db_hints:
        hint_lower = hint.lower()
        resolved = CLOUD_TO_LOCAL.get(hint_lower, hint_lower)
        cfg = DB_DOCKER_CONFIGS.get(resolved)
        if not cfg:
            continue
        img = cfg["image"]
        container = cfg["container"]
        port = cfg["port"]
        env_args = " ".join(f'-e {k}={v}' for k, v in cfg["env_vars"].items())
        start_cmd = (
            f"docker inspect {container} > /dev/null 2>&1 && docker start {container}"
            f" || (docker run -d --name {container} {env_args} -p {port}:{port} {img}"
            f" && sleep {HEALTH_CHECK_SLEEP}"
            f" && for i in $(seq 1 {_HEALTH_CHECK_ITERATIONS}); do nc -z localhost {port} 2>/dev/null && break; sleep {_HEALTH_CHECK_INTERVAL}; done)"
        )
        title = f"Provisió automàtica de {cfg['container'].replace('agent-', '').upper()} (Docker)"
        steps.append(CommandStep(
            id=f"db-provision-{resolved}",
            title=title,
            cwd="/tmp",
            command=start_cmd,
            expected_outcome=f"Container {container} arrencat i healthy al port {port}",
            category="db",
            verify_port=port,
        ))
        env_vars[cfg["url_env"]] = cfg["url_template"]
        for alt_name in cfg.get("alt_url_envs", []):
            env_vars[alt_name] = cfg["url_template"]
        env_vars.update(cfg["env_vars"])
    return steps, env_vars


def inject_db_env_vars(root: Path, env_vars: Dict[str, str]) -> None:
    if not env_vars:
        return
    env_file = root / ".env"
    existing = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k = line.split("=", 1)[0].strip()
                existing[k] = line
    for k, v in env_vars.items():
        if k not in existing:
            existing[k] = v
    lines = []
    for k, v in existing.items():
        if isinstance(v, str) and v.lstrip().startswith(f"{k}="):
            lines.append(v)
        else:
            lines.append(f"{k}={v}")
    env_file.write_text("\n".join(lines) + "\n")


def _build_pg_credentials_step(root: Path) -> Optional[CommandStep]:
    candidates: List[Path] = []
    for name in (".env", ".env.example", ".env.sample", ".env.template"):
        candidates.append(root / name)
        for subdir in root.iterdir():
            if subdir.is_dir() and subdir.name not in {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "target", ".agent_logs"}:
                candidates.append(subdir / name)
    for env_path in candidates:
        env_text = ""
        try:
            env_text = env_path.read_text(errors="ignore")[:2000]
        except Exception:
            continue
        m = _PG_URL_RE.search(env_text)
        if not m:
            continue
        user, password, db = m.group(2), m.group(3), m.group(5).rstrip("/")
        if user == "agentuser" and db == "agentdb":
            continue
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
