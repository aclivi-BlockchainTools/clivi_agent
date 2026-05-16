#!/usr/bin/env python3
"""
bartolo_init.py — CLI interactiva per muntar repos sense flags.

Guia l'usuari pas a pas: URL, directori, pre-flight check, pla i execució.
Reutilitza el cervell de universal_repo_agent_v5.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Assegura que el propi directori és al path per importar l'agent
_AGENT_DIR = Path(__file__).resolve().parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from universal_repo_agent_v5 import (
    DEFAULT_WORKSPACE,
    acquire_input,
    analyze_repo,
    ensure_workspace,
)
from bartolo.planner import build_deterministic_plan, print_analysis, print_plan
from bartolo.executor import execute_plan, print_final_summary
from bartolo.preflight import preflight_check


def _ask(prompt: str, default: str = "") -> str:
    """Pregunta amb default. Si l'usuari prem Enter, retorna el default."""
    if default:
        answer = input(f"{prompt} [{default}]: ").strip()
        return answer if answer else default
    while True:
        answer = input(f"{prompt}: ").strip()
        if answer:
            return answer


def _ask_yn(prompt: str, default_yes: bool = True) -> bool:
    """Pregunta sí/no."""
    suffix = " [S/n]: " if default_yes else " [s/N]: "
    answer = input(f"{prompt}{suffix}").strip().lower()
    if not answer:
        return default_yes
    return answer in {"s", "si", "y", "yes"}


def main() -> int:
    print("=" * 60)
    print("  Bartolo Init — Muntador interactiu de repos")
    print("=" * 60)
    print()
    print("Aquesta eina et guia per muntar un repositori al teu sistema.")
    print("Pot ser un URL (GitHub, GitLab, Bitbucket), un ZIP local o una carpeta.")
    print()

    # 1. On és el repo?
    print("─" * 40)
    print("1. Origen del repositori")
    print("─" * 40)
    repo_input = _ask("URL git, carpeta local o ZIP")
    print()

    # 2. On el muntem?
    print("─" * 40)
    print("2. Directori de treball")
    print("─" * 40)
    default_ws = os.path.expanduser(DEFAULT_WORKSPACE)
    workspace_str = _ask("Directori on clonar/desplegar", default=default_ws)
    workspace = Path(workspace_str).expanduser().resolve()
    print(f"   → {workspace}")
    print()

    # 3. Adquirir el repo (clonar/descomprimir)
    print("─" * 40)
    print("3. Adquirint repositori...")
    print("─" * 40)
    try:
        ensure_workspace(workspace)
        acquired = acquire_input(repo_input, workspace)
        print(f"   → Repo adquirit a: {acquired}")
    except Exception as e:
        print(f"\n❌ Error adquirint el repo: {e}")
        return 1
    print()

    # 4. Analitzar
    print("─" * 40)
    print("4. Analitzant el repositori...")
    print("─" * 40)
    try:
        analysis = analyze_repo(acquired, model="qwen2.5:14b", extract_readme=True)
        print_analysis(analysis)
    except Exception as e:
        print(f"\n❌ Error analitzant el repo: {e}")
        return 1
    print()

    # 5. Pre-flight check
    print("─" * 40)
    print("5. Comprovacions prèvies")
    print("─" * 40)
    svc_ports = [p for s in analysis.services for p in (s.ports_hint or [])]
    if not preflight_check(analysis.missing_system_deps, ports_hint=svc_ports or None,
                           auto_approve=False):
        print("\n⚠️  Corregiu els problemes i torneu a intentar.")
        return 1
    print()

    # 6. Generar pla
    print("─" * 40)
    print("6. Pla d'execució")
    print("─" * 40)
    plan = build_deterministic_plan(analysis)
    print_plan(plan)
    print()

    if not plan.steps:
        print("⚠️  No s'han detectat passos per executar.")
        return 1

    # 7. Confirmar
    if not _ask_yn("Executar aquest pla?"):
        print("\n❌ Cancel·lat per l'usuari.")
        return 0
    print()

    # 8. Executar
    print("─" * 40)
    print("7. Executant...")
    print("─" * 40)
    try:
        results, errors = execute_plan(
            analysis=analysis,
            plan=plan,
            model="qwen2.5:14b",
            workspace=workspace,
            approve_all=True,  # Ja hem demanat confirmació global
            dry_run=False,
        )
    except Exception as e:
        print(f"\n❌ Error durant l'execució: {e}")
        return 1

    print_final_summary(analysis, plan, results, errors,
                        workspace / ".agent_logs", workspace=workspace)

    if any(e for e in errors if not e.repaired):
        return 1

    print()
    print("✅ Tot correcte!")
    urls = sorted({svc.run_url for svc in analysis.services if svc.run_url})
    if urls:
        print("   URLs:")
        for url in urls:
            print(f"   - {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
