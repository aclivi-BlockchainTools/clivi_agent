"""bartolo/cli.py — CLI entry point: parse_args + main."""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path
from typing import Dict

from bartolo.executor import (
    execute_plan, stop_services, _backup_env_files, _execute_rollback,
)
from bartolo.llm import DEFAULT_MODEL, ollama_chat_json, safe_json_loads, OLLAMA_CHAT_URL
from bartolo.planner import (
    build_deterministic_plan, build_emergent_plan,
    build_llm_primary_plan, refine_plan_with_model, merge_readme_instructions,
)
from bartolo.preflight import preflight_check
from bartolo.provisioner import (
    DB_DOCKER_CONFIGS, CLOUD_TO_LOCAL, build_db_provision_steps,
    inject_db_env_vars, is_docker_available, slugify,
)
from bartolo.reporter import print_analysis, print_plan, print_final_summary
from bartolo.smoke import run_smoke_tests, print_smoke_report
from bartolo.types import RepoAnalysis

from universal_repo_agent_v5 import (
    info, warn, err, ensure_workspace, DEFAULT_WORKSPACE, LOG_DIRNAME,
    acquire_input, analyze_repo, detect_emergent_stack,
    prepare_emergent_env_files, _detect_lan_ip,
    check_and_warn_native_deps, detect_third_party_services,
    read_text, find_env_examples, prompt_and_cache_secrets,
    prompt_third_party_secrets, inject_secrets_into_env,
    interactive_env_setup, show_status, build_dockerize_plan,
)


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
    parser.add_argument("--status", action="store_true", help="Mostra els serveis registrats i el seu estat")
    parser.add_argument("--stop", default="", help="Atura serveis registrats. Ús: --stop all | --stop <repo-name>")
    parser.add_argument("--logs", default="", help="Mostra els últims logs d'un repo: --logs <repo-name>")
    parser.add_argument("--refresh", default="", help="Regenera els .env d'un repo ja clonat (útil després d'un canvi d'IP). Ús: --refresh <repo-name>")
    return parser.parse_args()


def show_logs(workspace: Path, repo_name: str, lines: int = 50) -> None:
    log_dir = workspace / LOG_DIRNAME
    repo_dir = workspace / slugify(repo_name)
    print(f"\n=== Últims {lines} logs per '{repo_name}' ===")
    if log_dir.exists():
        files = sorted(log_dir.glob(f"*{slugify(repo_name)}*"))[-5:]
        for f in files:
            print(f"\n--- {f.name} ---")
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                print("\n".join(text.splitlines()[-lines:]))
            except Exception as e:
                print(f"(error llegint: {e})")
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
    slug = slugify(repo_name)
    repo_root = workspace / slug
    if not repo_root.exists():
        candidates = [p for p in repo_root.parent.glob(f"{slug}*") if p.is_dir()]
        if not candidates:
            err(f"No s'ha trobat el repositori '{repo_name}' a {workspace}")
            return 1
        repo_root = candidates[0]
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
        start_sh = repo_root / "start.sh"
        if start_sh.exists():
            info("Stack no-Emergent detectat. Reiniciant via start.sh...")
            subprocess.run(["bash", str(start_sh), "stop"], cwd=str(repo_root),
                           capture_output=True)
            stop_services(workspace, repo_name)
            r = subprocess.run(["bash", str(start_sh)], cwd=str(repo_root))
            return r.returncode
        err(f"El repositori no és Emergent (FastAPI+React+Mongo) ni té start.sh.")
        print(f"   Path: {repo_root}")
        return 1
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
    print(f"   python3 universal_repo_agent_v5.py --workspace {workspace} --stop {repo_name}")
    print(f"   python3 universal_repo_agent_v5.py --input {repo_root} --execute --approve-all --non-interactive --no-readme --no-model-refine")
    return 0


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    log_dir = workspace / LOG_DIRNAME

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

        emergent = None if args.no_emergent_detect else detect_emergent_stack(Path(analysis.root))
        if emergent:
            info("🟢 Emergent stack detectat — s'usarà pla específic.")
            analysis.likely_fullstack = True
            analysis.likely_db_needed = emergent["uses_mongo"]
            if emergent["uses_mongo"] and "mongodb" not in analysis.db_hints:
                analysis.db_hints.append("mongodb")

        svc_ports = [p for s in analysis.services for p in (s.ports_hint or [])]
        if not preflight_check(analysis.missing_system_deps, ports_hint=svc_ports or None,
                               auto_approve=args.approve_all,
                               non_interactive=args.non_interactive):
            return 1

        _backup_env_files(Path(analysis.root))

        db_env_vars: Dict[str, str] = {}
        if analysis.likely_db_needed and not args.no_db_provision and is_docker_available():
            _, db_env_vars = build_db_provision_steps(analysis.db_hints)
            if not emergent:
                inject_db_env_vars(Path(analysis.root), db_env_vars)
            analysis.db_provisioned = analysis.db_hints[:]

        if emergent:
            prepare_emergent_env_files(Path(analysis.root), emergent)

        missing_os = check_and_warn_native_deps(Path(analysis.root))
        if missing_os:
            print("\n⚠️  DEPENDÈNCIES DEL SISTEMA (per paquets natius):")
            for d in missing_os:
                print(f"   · {d}  → sudo apt-get install -y {d}")
            print("   Continuo igualment, però pot fallar el pip/npm install. Instal·la-les en una altra finestra si cal.")

        if analysis.runtime_version_warnings:
            print("\n⚠️  VERSIONS RUNTIME (el repo demana una versió més recent):")
            for w in analysis.runtime_version_warnings:
                print(f"   · {w}")
            print("   Continuo igualment, però pot fallar. Instal·la la versió requerida si cal.")

        third_party = detect_third_party_services(Path(analysis.root))

        primary_env_file = (Path(emergent["backend"]) / ".env") if emergent else (Path(analysis.root) / ".env")
        existing_env = read_text(primary_env_file) if primary_env_file.exists() else ""

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

        secrets = prompt_and_cache_secrets(
            detected_vars=analysis.env_vars_needed,
            existing_env=existing_env,
            non_interactive=args.non_interactive or args.approve_all,
            example_real_values=_example_real_values,
        )
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

        if emergent and args.dockerize:
            plan = build_dockerize_plan(Path(analysis.root), emergent)
        elif args.llm_primary:
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
        print_final_summary(analysis, plan, results, errors, log_dir, workspace=workspace)
        if not args.no_smoke:
            time.sleep(3)
            smoke = run_smoke_tests(emergent, analysis)
            print_smoke_report(smoke)
        print(f"\n📁 Fitxer .env: {primary_env_file}")
        if db_env_vars:
            print("🗄️  Variables de BD injectades:")
            for k, v in db_env_vars.items():
                print(f"   {k}={v}")
        if emergent:
            print("\n🟢 Emergent stack iniciat:")
            # Read actual running URLs from services registry
            from bartolo.executor import load_services_registry
            import re as _re
            reg = load_services_registry(workspace)
            for svc_name, svcs in reg.items():
                if isinstance(svcs, list):
                    for svc in svcs:
                        cmd = svc.get("command", "")
                        port = None
                        for m in _re.finditer(r'(?:PORT|port|--port)[= ](\d{4,5})', cmd):
                            port = m.group(1)
                        if not port:
                            parts = cmd.split()
                            if parts:
                                m = _re.search(r':(\d{4,5})\b', parts[-1])
                                port = m.group(1) if m else None
                        label = svc.get("step_id", "")
                        if "frontend" in label or "fe" in label:
                            label = "Frontend"
                        elif "backend" in label or "be" in label or "api" in label:
                            label = "Backend"
                        if port:
                            print(f"   {label} : http://localhost:{port}")
                        else:
                            print(f"   {label} : PID {svc.get('pid', '?')}")
            if analysis.db_provisioned:
                for db in analysis.db_provisioned:
                    cfg = DB_DOCKER_CONFIGS.get(db, {})
                    if cfg:
                        print(f"   {db}: {cfg.get('url_template', '')}")
            print(f"   Per aturar: python3 universal_repo_agent_v5.py --stop {analysis.repo_name}")
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
