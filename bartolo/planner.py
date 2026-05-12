"""Planificador: genera plans d'execució a partir de l'anàlisi del repo."""

from __future__ import annotations

import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests

from bartolo.detectors import detect_docker_service
from bartolo.detectors.discovery import SKIP_DIRS, read_text
from bartolo.exceptions import AgentError
from bartolo.kb.success import lookup_plan
from bartolo.llm import ollama_chat_json, OLLAMA_CHAT_URL, DEFAULT_MODEL
from bartolo.provisioner import (
    DB_DOCKER_CONFIGS,
    build_db_provision_steps,
    is_docker_available,
    slugify,
    _build_pg_credentials_step,
)
from bartolo.reporter import print_analysis, print_plan
from bartolo.shell import find_free_port, run_check, maybe_background_command
from bartolo.types import (
    CommandStep, ExecutionPlan, RepoAnalysis, ServiceInfo,
)
from bartolo.validator import validate_command

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

README_NAMES = [
    "README.md", "README.rst", "README.txt", "README", "INSTALL.md", "INSTALL.txt",
    "GETTING_STARTED.md", "docs/INSTALL.md",
]


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def file_exists_any(root: Path, names: Sequence[str]) -> bool:
    return any((root / n).exists() for n in names)


def find_readme(root: Path) -> Optional[Path]:
    for name in README_NAMES:
        p = root / name
        if p.exists():
            return p
    return None




def _detect_root_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def choose_node_install_cmd(svc: ServiceInfo, monorepo_tool: Optional[str] = None) -> str:
    pm = svc.package_manager or "npm"
    if monorepo_tool:
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


def choose_python_run_cmd(svc: ServiceInfo) -> Optional[str]:
    path = Path(svc.path)
    port = None
    if svc.run_url:
        parsed = urlparse(svc.run_url)
        if parsed.port:
            port = parsed.port
    if port is None and svc.ports_hint:
        port = svc.ports_hint[0]
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
            return f"docker compose up --build"
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
                    new_cmd = re.sub(r"--server\.port[=\s]+\d+", f"--server.port {free_port}", new_cmd)
                    new_cmd = re.sub(r"(--port|-p)[=\s]+\d+", lambda m: f"{m.group(1)} {free_port}", new_cmd)
                    new_cmd = re.sub(r"(--bind|-b)[=\s]+([^\s:]+):\d+", lambda m: f"{m.group(1)} {m.group(2)}:{free_port}", new_cmd)
                    if new_cmd == step_command:
                        command = f"PORT={free_port} {step_command}"
                    else:
                        command = new_cmd
                elif st == "php":
                    new_cmd = re.sub(r"(--port[=\s]+)\d+", f"\\g<1>{free_port}", step_command)
                    new_cmd = re.sub(r"(-S[=\s]+[\w.]+):\d+", f"\\g<1>:{free_port}", new_cmd)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "ruby":
                    new_cmd = re.sub(r"(--port|-p)[=\s]+\d+", f"\\g<1> {free_port}", step_command)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "elixir":
                    command = f"PORT={free_port} {step_command}"
                elif st == "go":
                    new_cmd = re.sub(r"(--port|-p)[=\s]+\d+", f"\\g<1> {free_port}", step_command)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "java":
                    new_cmd = re.sub(r"--server\.port[=\s]+\d+", f"--server.port={free_port}", step_command)
                    new_cmd = re.sub(r"-Dserver\.port=\d+", f"-Dserver.port={free_port}", new_cmd)
                    command = new_cmd if new_cmd != step_command else f"PORT={free_port} {step_command}"
                elif st == "dotnet":
                    new_cmd = re.sub(r"--urls[=\s]+https?://[^:]+:\d+", f"--urls http://localhost:{free_port}", step_command)
                    command = new_cmd if new_cmd != step_command else f"ASPNETCORE_URLS=http://localhost:{free_port} {step_command}"
                else:
                    command = f"PORT={free_port} {step_command}"
                svc.run_url = f"{parsed.scheme}://{parsed.hostname}:{free_port}"
            verify_url = svc.run_url
            verify_port = free_port
    return command, verify_port, verify_url


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
    return CommandStep(
        id=f"setup-script-{slugify(script_path.name)}",
        title=f"Script de setup: {rel}",
        cwd=str(repo_root), command=command,
        expected_outcome="Script de setup completat sense errors",
        critical=False, category="setup",
    )


def build_deterministic_plan(analysis: RepoAnalysis) -> ExecutionPlan:
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
                steps.append(CommandStep(
                    id="docker-up", title="Inicia el stack amb docker compose",
                    cwd=str(root), command=command,
                    expected_outcome="Tots els serveis arrenquen correctament",
                    category="run", verify_port=verify_port_num, verify_url=verify_url,
                ))
        return ExecutionPlan(summary="Docker Compose detectat al root del repositori.", steps=steps, notes=notes)
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
            steps.append(CommandStep(
                id=f"node-install-{slugify(svc.name)}",
                title=f"Instal·la dependències Node — {svc.name}",
                cwd=svc.path, command=choose_node_install_cmd(svc),
                expected_outcome="node_modules instal·lats", category="install",
            ))
            build_cmd = None
            scripts = svc.scripts or {}
            pm = svc.package_manager or "npm"
            if "build" in scripts:
                build_cmd = {"pnpm": "pnpm build", "yarn": "yarn build"}.get(pm, "npm run build")
            elif svc.framework == "next" and "build" not in scripts:
                build_cmd = "npx next build"
            if build_cmd:
                steps.append(CommandStep(
                    id=f"node-build-{slugify(svc.name)}",
                    title=f"Build — {svc.name}", cwd=svc.path, command=build_cmd,
                    expected_outcome="Build completat", category="install",
                ))
            if (svc_path / "prisma" / "schema.prisma").exists():
                steps.append(CommandStep(
                    id=f"prisma-migrate-{slugify(svc.name)}",
                    title=f"Prisma migrate — {svc.name}", cwd=svc.path,
                    command="npx prisma migrate deploy",
                    expected_outcome="BD migrada (Prisma)", category="migrate", critical=False,
                ))
            if (svc_path / "knexfile.js").exists() or (svc_path / "knexfile.ts").exists():
                steps.append(CommandStep(
                    id=f"knex-migrate-{slugify(svc.name)}",
                    title=f"Knex migrate — {svc.name}", cwd=svc.path,
                    command="npx knex migrate:latest",
                    expected_outcome="BD migrada (Knex)", category="migrate", critical=False,
                ))
            if (svc_path / ".sequelizerc").exists():
                steps.append(CommandStep(
                    id=f"sequelize-migrate-{slugify(svc.name)}",
                    title=f"Sequelize migrate — {svc.name}", cwd=svc.path,
                    command="npx sequelize-cli db:migrate",
                    expected_outcome="BD migrada (Sequelize)", category="migrate", critical=False,
                ))
            run_cmd = choose_node_run_cmd(svc)
            if run_cmd:
                command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
                steps.append(CommandStep(
                    id=f"node-run-{slugify(svc.name)}",
                    title=f"Arrenca {svc.name} ({svc.framework})",
                    cwd=svc.path, command=command,
                    expected_outcome="Servidor Node disponible",
                    category="run", critical=False,
                    verify_port=verify_port_num, verify_url=verify_url,
                ))
        elif st == "python":
            for i, cmd in enumerate(choose_python_install_cmds(svc), start=1):
                steps.append(CommandStep(
                    id=f"py-install-{slugify(svc.name)}-{i}",
                    title=f"Prepara entorn Python — {svc.name}",
                    cwd=svc.path, command=cmd,
                    expected_outcome="Venv i dependències instal·lades", category="install",
                ))
            if (svc_path / "alembic.ini").exists() or (svc_path / "alembic").exists():
                steps.append(CommandStep(
                    id=f"py-migrate-{slugify(svc.name)}",
                    title=f"Migracions BD — {svc.name}",
                    cwd=svc.path, command=".venv/bin/alembic upgrade head",
                    expected_outcome="Esquema migrat", category="migrate", critical=False,
                ))
            if (svc_path / "manage.py").exists() and svc.framework == "django":
                steps.append(CommandStep(
                    id=f"django-migrate-{slugify(svc.name)}",
                    title=f"Migracions Django — {svc.name}",
                    cwd=svc.path, command=".venv/bin/python manage.py migrate",
                    expected_outcome="BD Django migrada", category="migrate", critical=False,
                ))
            run_cmd = choose_python_run_cmd(svc)
            if run_cmd:
                command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
                steps.append(CommandStep(
                    id=f"py-run-{slugify(svc.name)}",
                    title=f"Arrenca {svc.name} ({svc.framework})",
                    cwd=svc.path, command=command,
                    expected_outcome="Servidor Python disponible",
                    category="run", critical=False,
                    verify_port=verify_port_num, verify_url=verify_url,
                ))
        elif st == "docker":
            run_cmd = choose_docker_cmd(svc)
            if run_cmd:
                command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
                steps.append(CommandStep(
                    id=f"docker-run-{slugify(svc.name)}",
                    title=f"Docker — {svc.name}",
                    cwd=svc.path, command=command,
                    expected_outcome="Contenidor en execució",
                    category="run", critical=False,
                    verify_port=verify_port_num, verify_url=verify_url,
                ))
        elif st == "go":
            if not (svc_path / "go.sum").exists() and (svc_path / "go.mod").exists():
                steps.append(CommandStep(
                    id=f"go-install-{slugify(svc.name)}",
                    title=f"Go mod download — {svc.name}",
                    cwd=svc.path, command="go mod download",
                    expected_outcome="Dependències Go descarregades", category="install",
                ))
            entry = "main.go" if (svc_path / "main.go").exists() else "./..."
            run_cmd = f"go run {entry}"
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(
                id=f"go-run-{slugify(svc.name)}",
                title=f"Arrenca {svc.name} (Go)",
                cwd=svc.path, command=command,
                expected_outcome="Servidor Go disponible",
                category="run", critical=False,
                verify_port=verify_port_num, verify_url=verify_url,
            ))
        elif st == "rust":
            steps.append(CommandStep(
                id=f"rust-build-{slugify(svc.name)}",
                title=f"Cargo build — {svc.name}",
                cwd=svc.path, command="cargo build --release",
                expected_outcome="Binari compilat", category="install",
            ))
            steps.append(CommandStep(
                id=f"rust-run-{slugify(svc.name)}",
                title=f"Cargo run — {svc.name}",
                cwd=svc.path, command="cargo run --release",
                expected_outcome="Binari en execució", category="run", critical=False,
            ))
        elif st == "ruby":
            if (svc_path / "Gemfile").exists():
                steps.append(CommandStep(
                    id=f"ruby-install-{slugify(svc.name)}",
                    title=f"Bundle install — {svc.name}",
                    cwd=svc.path, command="bundle install",
                    expected_outcome="Gemfile installed", category="install",
                ))
            if svc.framework == "rails":
                steps.append(CommandStep(
                    id=f"rails-db-{slugify(svc.name)}",
                    title=f"Rails db:migrate — {svc.name}",
                    cwd=svc.path, command="bundle exec rails db:migrate",
                    expected_outcome="DB migrada", category="migrate", critical=False,
                ))
                steps.append(CommandStep(
                    id=f"rails-run-{slugify(svc.name)}",
                    title=f"Rails server — {svc.name}",
                    cwd=svc.path, command="bundle exec rails server -b 0.0.0.0",
                    expected_outcome="Rails a :3000", category="run", critical=False,
                    verify_port=3000, verify_url="http://localhost:3000",
                ))
            else:
                steps.append(CommandStep(
                    id=f"ruby-run-{slugify(svc.name)}",
                    title=f"Ruby run — {svc.name}",
                    cwd=svc.path,
                    command="bundle exec ruby main.rb" if (svc_path / "main.rb").exists() else "bundle exec ruby app.rb",
                    expected_outcome="Script Ruby en execució", category="run", critical=False,
                ))
        elif st == "php":
            steps.append(CommandStep(
                id=f"php-install-{slugify(svc.name)}",
                title=f"Composer install — {svc.name}",
                cwd=svc.path, command="composer install",
                expected_outcome="Composer deps instal·lades", category="install",
            ))
            if svc.framework == "laravel":
                steps.append(CommandStep(
                    id=f"php-migrate-{slugify(svc.name)}",
                    title=f"Artisan migrate — {svc.name}",
                    cwd=svc.path, command="php artisan migrate --force",
                    expected_outcome="BD migrada (Artisan)", category="migrate", critical=False,
                ))
                steps.append(CommandStep(
                    id=f"php-run-{slugify(svc.name)}",
                    title=f"Laravel serve — {svc.name}",
                    cwd=svc.path, command="php artisan serve --host=0.0.0.0 --port=8000",
                    expected_outcome="Laravel a :8000", category="run", critical=False,
                    verify_port=8000, verify_url="http://localhost:8000",
                ))
            else:
                steps.append(CommandStep(
                    id=f"php-run-{slugify(svc.name)}",
                    title=f"PHP built-in server — {svc.name}",
                    cwd=svc.path, command="php -S 0.0.0.0:8000",
                    expected_outcome="PHP a :8000", category="run", critical=False,
                    verify_port=8000,
                ))
        elif st == "java":
            pom = svc_path / "pom.xml"
            if pom.exists():
                steps.append(CommandStep(
                    id=f"java-build-{slugify(svc.name)}",
                    title=f"Maven package — {svc.name}",
                    cwd=svc.path, command="mvn -q -DskipTests package",
                    expected_outcome="JAR construït", category="install",
                ))
                steps.append(CommandStep(
                    id=f"java-run-{slugify(svc.name)}",
                    title=f"Spring Boot run — {svc.name}",
                    cwd=svc.path, command="mvn spring-boot:run",
                    expected_outcome="Spring a :8080", category="run", critical=False,
                    verify_port=8080, verify_url="http://localhost:8080",
                ))
            else:
                steps.append(CommandStep(
                    id=f"java-build-{slugify(svc.name)}",
                    title=f"Gradle build — {svc.name}",
                    cwd=svc.path, command="./gradlew build -x test",
                    expected_outcome="Build Gradle OK", category="install",
                ))
                steps.append(CommandStep(
                    id=f"java-run-{slugify(svc.name)}",
                    title=f"Gradle bootRun — {svc.name}",
                    cwd=svc.path, command="./gradlew bootRun",
                    expected_outcome="Spring a :8080", category="run", critical=False,
                    verify_port=8080, verify_url="http://localhost:8080",
                ))
        elif st == "make":
            targets = svc.entry_hints or []
            preferred = next((t for t in ["run", "start", "serve", "dev", "up"] if t in targets), None)
            if preferred:
                steps.append(CommandStep(
                    id=f"make-{slugify(svc.name)}-{preferred}",
                    title=f"make {preferred} — {svc.name}",
                    cwd=svc.path, command=f"make {preferred}",
                    expected_outcome=f"make {preferred} completat",
                    category="run", critical=False,
                ))
        elif st == "deno":
            run_cmd = "deno run -A main.ts"
            deno_json_path = svc_path / "deno.json"
            if deno_json_path.exists():
                try:
                    deno_cfg = json.loads(deno_json_path.read_text(errors="ignore"))
                    tasks = deno_cfg.get("tasks", {}) if isinstance(deno_cfg, dict) else {}
                    if tasks and isinstance(tasks, dict):
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
                for candidate in ("server.ts", "main.ts", "index.ts", "app.ts", "mod.ts"):
                    if (svc_path / candidate).exists():
                        run_cmd = f"deno run -A {candidate}"
                        break
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(
                id=f"deno-run-{slugify(svc.name)}",
                title=f"Deno run — {svc.name}",
                cwd=svc.path, command=command,
                expected_outcome="Servidor Deno disponible",
                category="run", critical=False,
                verify_port=verify_port_num, verify_url=verify_url,
            ))
        elif st == "elixir":
            steps.append(CommandStep(
                id=f"elixir-deps-{slugify(svc.name)}",
                title=f"Mix deps.get — {svc.name}",
                cwd=svc.path, command="mix deps.get",
                expected_outcome="Dependències Elixir instal·lades", category="install",
            ))
            run_cmd = "mix phx.server" if svc.framework == "phoenix" else "mix run --no-halt"
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(
                id=f"elixir-run-{slugify(svc.name)}",
                title=f"Elixir run — {svc.name}",
                cwd=svc.path, command=command,
                expected_outcome="Servidor Elixir disponible",
                category="run", critical=False,
                verify_port=verify_port_num, verify_url=verify_url,
            ))
        elif st == "dotnet":
            steps.append(CommandStep(
                id=f"dotnet-restore-{slugify(svc.name)}",
                title=f"dotnet restore — {svc.name}",
                cwd=svc.path, command="dotnet restore",
                expected_outcome="Paquets NuGet restaurats", category="install",
            ))
            run_cmd = "dotnet watch run" if svc.framework == "aspnet" else "dotnet run"
            command, verify_port_num, verify_url = choose_service_verify(run_cmd, svc)
            steps.append(CommandStep(
                id=f"dotnet-run-{slugify(svc.name)}",
                title=f"dotnet run — {svc.name}",
                cwd=svc.path, command=command,
                expected_outcome="Servidor .NET disponible",
                category="run", critical=False,
                verify_port=verify_port_num, verify_url=verify_url,
            ))
    if not steps:
        manifests = analysis.top_level_manifests or []
        lib_manifests = [m for m in manifests if m in (
            "package.json", "setup.py", "setup.cfg", "pyproject.toml",
            "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml",
        )]
        if lib_manifests and not analysis.services:
            notes.append(
                f"ℹ️  El repo sembla una llibreria/package ({', '.join(lib_manifests)}), no una aplicació executable."
                f"\n   Si és una app, cal un manifest de servei addicional (Dockerfile, Procfile, start.sh...)."
            )
        else:
            notes.append("⚠️  No s'ha pogut derivar cap pla d'execució automàticament.")
    _CATEGORY_ORDER = {"db": -1, "install": 0, "migrate": 1, "setup": 2, "configure": 3, "run": 4, "verify": 5}
    steps.sort(key=lambda s: _CATEGORY_ORDER.get(getattr(s, "category", "run"), 99))
    return ExecutionPlan(summary="Pla generat automàticament a partir dels manifests del repositori.", steps=steps, notes=notes)


def build_emergent_plan(root: Path, emergent: Dict[str, Any]) -> ExecutionPlan:
    backend = Path(emergent["backend"])
    frontend = Path(emergent["frontend"])
    steps: List[CommandStep] = []
    notes: List[str] = ["🟢 Detectat stack Emergent (FastAPI + React + MongoDB)."]
    if emergent["uses_mongo"] and is_docker_available():
        cfg = DB_DOCKER_CONFIGS["mongodb"]
        container, image, port = cfg["container"], cfg["image"], cfg["port"]
        cmd = f"docker inspect {container} > /dev/null 2>&1 && docker start {container} || docker run -d --name {container} -p {port}:{port} {image}"
        steps.append(CommandStep(
            id="emergent-db-mongo", title="MongoDB (Docker)", cwd="/tmp",
            command=cmd, expected_outcome="Contenidor mongo en execució",
            category="db", critical=False, verify_port=port,
        ))
    elif emergent["uses_mongo"]:
        notes.append("⚠️  Cal MongoDB però Docker no disponible. Instal·la mongodb-server o Docker.")
    steps.append(CommandStep(
        id="emergent-be-venv", title="Backend: venv",
        cwd=str(backend), command="python3 -m venv .venv",
        expected_outcome="Venv creat", category="install",
    ))
    be_extra_index = ""
    be_req = backend / "requirements.txt"
    if be_req.exists():
        try:
            if "emergentintegrations" in be_req.read_text(errors="ignore").lower():
                be_extra_index = " --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/"
        except Exception:
            pass
    steps.append(CommandStep(
        id="emergent-be-install", title="Backend: pip install",
        cwd=str(backend), command=f".venv/bin/pip install -r requirements.txt{be_extra_index}",
        expected_outcome="Dependències backend instal·lades", category="install",
    ))
    be_port = find_free_port(8001)
    fe_port = find_free_port(3000)
    if be_port != 8001:
        notes.append(f"ℹ️  Port 8001 ocupat, backend reassignat a :{be_port}.")
    if fe_port != 3000:
        notes.append(f"ℹ️  Port 3000 ocupat (probablement per OpenWebUI), frontend reassignat a :{fe_port}.")
    steps.append(CommandStep(
        id="emergent-be-run", title=f"Backend: uvicorn (port {be_port})",
        cwd=str(backend),
        command=f".venv/bin/uvicorn server:app --host 0.0.0.0 --port {be_port} --reload",
        expected_outcome=f"FastAPI servint a :{be_port}", category="run", critical=False,
        verify_port=be_port, verify_url=f"http://localhost:{be_port}/api/",
    ))
    fe_env = f"NODE_OPTIONS=--openssl-legacy-provider BROWSER=none"
    if be_port != 8001:
        fe_env = f"REACT_APP_BACKEND_URL=http://localhost:{be_port} {fe_env}"
    has_yarn = run_check("yarn --version")
    if has_yarn:
        steps.append(CommandStep(
            id="emergent-fe-install", title="Frontend: yarn install",
            cwd=str(frontend), command="yarn install",
            expected_outcome="node_modules instal·lats", category="install",
        ))
        steps.append(CommandStep(
            id="emergent-fe-run", title=f"Frontend: yarn start (port {fe_port})",
            cwd=str(frontend), command=f"{fe_env} PORT={fe_port} yarn start",
            expected_outcome=f"React servint a :{fe_port}", category="run", critical=False,
            verify_port=fe_port, verify_url=f"http://localhost:{fe_port}",
        ))
    else:
        steps.append(CommandStep(
            id="emergent-fe-install", title="Frontend: npm install (legacy peer deps)",
            cwd=str(frontend), command="npm install --legacy-peer-deps",
            expected_outcome="node_modules instal·lats", category="install",
        ))
        steps.append(CommandStep(
            id="emergent-fe-run", title=f"Frontend: npm start (port {fe_port})",
            cwd=str(frontend), command=f"{fe_env} PORT={fe_port} npm start",
            expected_outcome=f"React servint a :{fe_port}", category="run", critical=False,
            verify_port=fe_port, verify_url=f"http://localhost:{fe_port}",
        ))
        notes.append("⚠️  Yarn no trobat. Instal·la'l (sudo npm install -g yarn) per evitar conflictes de peer deps.")
    notes.append(f"Backend: http://localhost:{be_port}  ·  Frontend: http://localhost:{fe_port}")
    notes.append("Totes les rutes backend han d'estar prefixades amb /api (ingress Emergent).")
    return ExecutionPlan(summary="Pla Emergent stack (FastAPI + React + MongoDB).", steps=steps, notes=notes)


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
        plan.steps.append(CommandStep(
            id=f"readme-step-{i}", title=f"Del README: {instr[:60]}",
            cwd=str(repo_root), command=instr,
            expected_outcome="Pas del README completat", critical=False, category=cat,
        ))
        existing_cmds.add(instr)
    return plan


def gather_repo_context_for_llm(root: Path, max_files_per_type: int = 3, max_chars_per_file: int = 2500) -> Dict[str, Any]:
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
    root = Path(analysis.root)
    _info(f"🤖 LLM primari llegint el repo (model: {model})...")
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
            "services_detected": [
                {"name": s.name, "type": s.service_type, "framework": s.framework, "path": s.path}
                for s in analysis.services
            ],
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
        _warn(f"LLM primari ha fallat: {e}")
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
            _warn(f"Descartant pas LLM insegur ({raw.get('id','?')}): {e}")
            rejected += 1
    if not safe_steps:
        _warn(f"LLM primari ha proposat 0 passos vàlids ({rejected} rebutjats). Fallback determinista.")
        return None
    _info(f"🤖 LLM ha proposat {len(safe_steps)} passos ({rejected} descartats per seguretat).")
    return ExecutionPlan(
        summary=proposed.get("summary", "Pla proposat per LLM primari"),
        notes=proposed.get("notes", []) + [f"🤖 Generat per {model}"],
        steps=safe_steps,
    )


def refine_plan_with_model(analysis: RepoAnalysis, plan: ExecutionPlan, model: str) -> ExecutionPlan:
    from dataclasses import asdict
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "notes": {"type": "array", "items": {"type": "string"}},
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "title": {"type": "string"},
                "cwd": {"type": "string"}, "command": {"type": "string"},
                "expected_outcome": {"type": "string"}, "critical": {"type": "boolean"},
                "category": {"type": "string"}, "verify_url": {"type": ["string", "null"]},
                "verify_port": {"type": ["integer", "null"]},
            }, "required": ["id", "title", "cwd", "command", "expected_outcome", "critical", "category"]}},
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
        refined = ollama_chat_json(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps({
                "analysis": asdict(analysis),
                "initial_plan": {"summary": plan.summary, "notes": plan.notes, "steps": [asdict(s) for s in plan.steps]},
            }, ensure_ascii=False, indent=2)}],
            schema=schema, timeout=240,
        )
        safe_steps: List[CommandStep] = []
        for raw in refined.get("steps", []):
            try:
                validate_command(raw["command"], repo_root=Path(analysis.root))
                safe_steps.append(CommandStep(**raw))
            except Exception as e:
                _warn(f"Descartant pas insegur del model ({raw.get('id', '?')}): {e}")
        if safe_steps:
            return ExecutionPlan(
                summary=refined.get("summary", plan.summary),
                notes=refined.get("notes", plan.notes),
                steps=safe_steps,
            )
    except Exception as e:
        _warn(f"Refinament del model ha fallat, usant pla determinista: {e}")
    return plan



