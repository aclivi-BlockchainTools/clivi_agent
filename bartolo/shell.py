"""Execució de comandes shell — run_shell, run_check, maybe_background_command."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from bartolo.types import ExecutionResult
from bartolo.validator import ShellCommand, validate_command


def _env_with_local_bins() -> dict:
    """Retorna una còpia de l'entorn amb directoris d'instal·lació local al PATH."""
    env = os.environ.copy()
    local_bins = os.path.expanduser("~/.deno/bin:~/.local/bin:~/.cargo/bin")
    env["PATH"] = local_bins + ":" + env.get("PATH", "")
    return env


def run_shell(command: str, cwd: Path, timeout: int = 1800, repo_root: Optional[Path] = None) -> ExecutionResult:
    validate_command(command, repo_root=repo_root)
    started = time.time()
    env = _env_with_local_bins()
    env.update({"CI": "1", "DEBIAN_FRONTEND": "noninteractive", "NONINTERACTIVE": "1",
                "NPM_CONFIG_YES": "true", "GIT_TERMINAL_PROMPT": "0"})
    stdin_input = "\n" * 40
    try:
        proc = subprocess.run(command, cwd=str(cwd), shell=True, capture_output=True,
                              text=True, timeout=timeout, input=stdin_input, env=env)
    except subprocess.TimeoutExpired:
        return ExecutionResult(step_id="", command=command, cwd=str(cwd), returncode=-1, stdout="", stderr=f"TIMEOUT ({timeout}s)", started_at=started, finished_at=time.time())
    return ExecutionResult(step_id="", command=command, cwd=str(cwd), returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, started_at=started, finished_at=time.time())


def run_check(command: str) -> bool:
    try:
        env = _env_with_local_bins()
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15, env=env)
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def run_check_version(command: str) -> Optional[str]:
    """Com run_check() però retorna la primera línia de stdout (la versió)."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return (result.stdout + result.stderr).strip().split("\n")[0]
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def maybe_background_command(command: str, log_rel: str = ".agent_last_run.log") -> Tuple[str, bool]:
    """Retorna (command_modificat, is_background). Si cal, embolica amb nohup+& i imprimeix el PID.
    Les assignacions d'env var al principi (PORT=3000 ...) es mantenen abans de nohup perquè
    el shell les interpreti correctament."""
    markers = ["npm start", "npm run dev", "yarn start", "yarn dev", "pnpm dev",
               "uvicorn ", "flask ", "python manage.py runserver", "streamlit run",
               "rails server", "php artisan serve", "go run ", "cargo run",
               "docker compose up", "docker-compose up",
               "deno run", "deno task", "dotnet run", "dotnet watch",
               "mix phx.server", "mix run", "bundle exec"]
    if any(marker in command for marker in markers):
        # Evita re-wrapping si ja ve amb nohup/&
        if "nohup" in command or command.rstrip().endswith("&"):
            return command, True
        # Extreu assignacions d'env var inicials perquè quedin abans de 'nohup'
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
        dotenv_load = "test -f .env && export $(grep -v '^#' .env | grep -v '^$' | xargs); "
        wrapped = f"{env_prefix}{dotenv_load}setsid nohup {rest} > {log_rel} 2>&1 < /dev/null & echo __AGENT_PID__=$!"
        return wrapped, True
    return command, False
