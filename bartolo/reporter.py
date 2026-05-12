"""Reporter: funcions de sortida formatada per anàlisi, pla i resum."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from bartolo.provisioner import CLOUD_TO_LOCAL, DB_DOCKER_CONFIGS
from bartolo.types import ExecutionPlan, ExecutionResult, RepoAnalysis, StepError


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
            print(f"  • {note}")
    for i, step in enumerate(plan.steps, 1):
        cat = getattr(step, "category", "-")
        marker = "[CRÍTIC]" if step.critical else ""
        print(f"\n  Pas {i}: {step.title} {marker}")
        print(f"    cat: {cat}  |  cwd: {step.cwd}")
        print(f"    cmd: {step.command}")
        if step.verify_url or step.verify_port:
            v = step.verify_url or f"port {step.verify_port}"
            print(f"    verify: {v}")


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
        print("BD local:")
        for db in analysis.db_provisioned or analysis.db_hints:
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
                if shutil.which("psql"):
                    print(f"     O:         psql {cfg['url_template']}")
            elif db == "mysql":
                user = env.get("MYSQL_USER", "agentuser")
                bd = env.get("MYSQL_DATABASE", "agentdb")
                pw = env.get("MYSQL_PASSWORD", "agentpass")
                print(f"     Connecta:  docker exec -it {cfg['container']} mysql -u {user} -p{pw} {bd}")
                if shutil.which("mysql"):
                    print(f"     O:         mysql {cfg['url_template']}")
            elif db == "mongodb":
                print(f"     Connecta:  docker exec -it {cfg['container']} mongosh")
                if shutil.which("mongosh"):
                    print(f"     O:         mongosh {cfg['url_template']}")
            elif db == "redis":
                print(f"     Connecta:  docker exec -it {cfg['container']} redis-cli")
                if shutil.which("redis-cli"):
                    print(f"     O:         redis-cli -u {cfg['url_template']}")
    print(f"Logs: {log_dir}")
