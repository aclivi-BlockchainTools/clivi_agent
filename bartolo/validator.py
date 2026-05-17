"""Validació de comandes shell — capa de seguretat principal de Bartolo.

Whitelist de prefixos + blacklist de patrons perillosos.
Inclou ShellCommand, una dataclass per construir comandes de forma estructurada.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bartolo.exceptions import AgentError, ValidationError


SAFE_COMMAND_PREFIXES = {
    "ls", "pwd", "cat", "echo", "cp", "mv", "mkdir", "rm", "find", "grep", "sed", "awk", "env", "printenv", "which", "test", "true", "false",
    "sleep", "wait", "kill", "pkill", "fuser", "[",
    "git", "unzip", "tar", "curl", "wget", "ss", "lsof", "ps", "df", "du", "chmod",
    "node", "npm", "npx", "yarn", "pnpm", "corepack",
    "python", "python3", "pip", "pip3", "pytest", "uvicorn", "flask", "django-admin", "alembic", "poetry", "streamlit", "gunicorn", "celery", "daphne", "hypercorn",
    "docker", "docker-compose", "compose",
    "make", "go", "cargo", "ruby", "bundle", "rails", "php", "composer", "mvn", "gradle", "java",
    "deno", "dotnet", "elixir", "mix",
    "bash", "sh", "nohup",
}

# Containers gestionats manualment que l'agent NO ha de destruir mai.
PROTECTED_CONTAINERS = {"open-webui", "open-webui-pipelines"}

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
    # Protegeix containers crítics de destrucció accidental
    r"docker\s+(stop|kill|rm|remove)\s+[^|&;\n]*\b(" + "|".join(PROTECTED_CONTAINERS) + r")\b",
    r"docker\s+compose\s+(down|stop|rm)\b",
]


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
    tokens = shlex.split(command)
    if not tokens:
        raise ValidationError("Comanda buida")
    # Saltar assignacions d'env var inicials: PORT=3000 yarn start → 'yarn'
    prefix, _env = _first_real_token(tokens)
    if not prefix:
        raise ValidationError("Comanda sense binari a executar")
    # Saltar wrappers de process management (setsid, nohup) i buscar el binari real
    while prefix in {"setsid", "nohup", "export"}:
        try:
            idx = tokens.index(prefix) + 1
        except ValueError:
            break
        sub_prefix, _ = _first_real_token(tokens[idx:])
        if not sub_prefix:
            raise ValidationError(f"{prefix} sense comanda")
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
            raise ValidationError("bash/sh sense argument d'script no permès")
        if repo_root:
            script_path = (repo_root / script_arg).resolve() if not Path(script_arg).is_absolute() else Path(script_arg).resolve()
            if not str(script_path).startswith(str(repo_root.resolve())):
                raise ValidationError(f"Script fora del repositori no permès: {script_arg}")
    elif prefix in SAFE_COMMAND_PREFIXES:
        pass
    elif "/" in prefix:
        # Permetre camins a binaris dins del repo o d'un venv del repo (p.ex. .venv/bin/pip, ./scripts/run.sh)
        basename = Path(prefix).name
        if basename not in SAFE_COMMAND_PREFIXES:
            raise ValidationError(f"Prefix de comanda no permès: {prefix!r}")
        if repo_root:
            bin_path = (repo_root / prefix).resolve() if not Path(prefix).is_absolute() else Path(prefix).resolve()
            if not str(bin_path).startswith(str(repo_root.resolve())):
                raise ValidationError(f"Binari fora del repositori no permès: {prefix}")
    else:
        raise ValidationError(f"Prefix de comanda no permès: {prefix!r}")
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            raise ValidationError(f"Patró de comanda bloquejat detectat: {command!r}")


@dataclass
class ShellCommand:
    """Comanda shell construïda de forma estructurada, no per strings.

    Suporta variables d'entorn, auto-càrrega de .env, execució en background,
    i redirecció de logs.
    """
    executable: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[Path] = None
    background: bool = False
    log_file: Optional[str] = None

    def build(self) -> str:
        """Genera la comanda shell completa."""
        parts: List[str] = []
        if self.env:
            parts.extend(f"{k}={shlex.quote(v)}" for k, v in self.env.items())
        # Auto-load .env si existeix
        parts.append("test -f .env && set -a && . ./.env && set +a;")
        cmd = f"{' '.join(parts)} {self.executable} {' '.join(self.args)}"
        if self.background:
            cmd = f"setsid nohup {cmd} > {self.log_file} 2>&1 < /dev/null & echo __AGENT_PID__=$!"
        return cmd
