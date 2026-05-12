"""Pre-flight check: dependències del sistema, espai disc, ports."""

import getpass
import shutil as _shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from bartolo.shell import run_check, is_port_open

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
        return True
    answer = input("Vols continuar igualment? [s/N]: ").strip().lower()
    return answer in {"s", "si", "y", "yes"}


def _install_system_dep(dep: str, non_interactive: bool = False) -> bool:
    dep_info = SYSTEM_DEPS.get(dep)
    if not dep_info:
        return False
    install_cmd = dep_info.get("install", "")
    if not install_cmd or install_cmd.startswith("http"):
        return False

    needs_sudo = install_cmd.strip().startswith("sudo ")
    if needs_sudo and non_interactive:
        return False

    if needs_sudo:
        print(f"\n🔐 {dep} requereix permisos de superusuari.")
        try:
            password = getpass.getpass(f"   Contrasenya sudo per instal·lar {dep}: ")
        except (EOFError, KeyboardInterrupt):
            return False
        if not password:
            return False
        install_cmd = install_cmd.replace("sudo ", "sudo -S ", 1)
        try:
            result = subprocess.run(
                install_cmd, shell=True, timeout=120,
                input=password + "\n", text=True, capture_output=True,
            )
            if result.returncode != 0:
                return False
        except subprocess.TimeoutExpired:
            return False
    else:
        try:
            result = subprocess.run(
                install_cmd, shell=True, timeout=120,
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                return False
        except subprocess.TimeoutExpired:
            return False
    check_cmd = dep_info.get("check", f"which {dep}")
    if not run_check(check_cmd):
        return False
    return True


def preflight_check(missing_deps: List[str], ports_hint: Optional[List[int]] = None,
                    auto_approve: bool = False, non_interactive: bool = False) -> bool:
    all_ok = True
    lines: List[str] = []
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
            return True
        answer = input("Vols continuar igualment? [S/n]: ").strip().lower()
        if answer and answer not in {"s", "si", "y", "yes"}:
            return False
    return True
