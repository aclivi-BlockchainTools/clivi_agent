"""Motor d'execució de plans, registry de serveis, rollback."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bartolo.exceptions import AgentError
from bartolo.provisioner import DB_DOCKER_CONFIGS, CLOUD_TO_LOCAL, slugify
from bartolo.repair.fallback import _FALLBACK_MAP, _get_fallbacks
from bartolo.reporter import print_final_summary
from bartolo.validator import validate_command
from bartolo.shell import (
    run_shell, maybe_background_command, verify_http, verify_port,
)
from bartolo.types import (
    CommandStep, ExecutionPlan, ExecutionResult, RepoAnalysis, StepError,
)


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


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




def _registry_path(workspace: Path) -> Path:
    return workspace / ".agent_services.json"


def load_services_registry(workspace: Path) -> Dict[str, Any]:
    path = _registry_path(workspace)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
    if pid:
        repo_path = Path(cwd)
        logs_dir = repo_path / ".logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        pid_file = logs_dir / f"{step_id}.pid"
        pid_file.write_text(str(pid))


def stop_services(workspace: Path, repo_name: str = "all") -> None:
    data = load_services_registry(workspace)
    if not data:
        _info("No hi ha serveis registrats.")
        return
    targets = list(data.keys()) if repo_name == "all" else [repo_name]
    stopped = 0
    for name in targets:
        for svc in data.get(name, []):
            pid = svc.get("pid")
            if not pid:
                continue
            try:
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, 15)
                except Exception:
                    os.kill(pid, 15)
                stopped += 1
                _info(f"Aturat PID {pid} ({name}::{svc['step_id']})")
            except ProcessLookupError:
                pass
            except Exception as e:
                _warn(f"No s'ha pogut aturar PID {pid}: {e}")
            if svc.get("step_id") and svc.get("cwd"):
                pid_file = Path(svc["cwd"]) / ".logs" / f"{svc['step_id']}.pid"
                try:
                    pid_file.unlink(missing_ok=True)
                except Exception:
                    pass
        if name in data:
            del data[name]
    save_services_registry(workspace, data)
    _info(f"Total serveis aturats: {stopped}")


def _backup_env_files(root: Path) -> Dict[str, str]:
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
    cleaned: List[str] = []
    try:
        stop_services(workspace, analysis.repo_name)
        cleaned.append(f"Processos aturats per {analysis.repo_name}")
    except Exception as e:
        cleaned.append(f"Error aturant processos: {e}")
    for db_key in getattr(analysis, "db_provisioned", []) or []:
        cfg = DB_DOCKER_CONFIGS.get(db_key, {})
        container = cfg.get("container", "")
        if container:
            try:
                subprocess.run(f"docker stop {container}", shell=True, capture_output=True, timeout=15)
                cleaned.append(f"Contenidor BD aturat: {container}")
            except Exception as e:
                cleaned.append(f"Error aturant contenidor {container}: {e}")
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
        _info("Rollback executat: " + "; ".join(cleaned))
    return cleaned


def execute_plan(analysis: RepoAnalysis, plan: ExecutionPlan, model: str, workspace: Path, approve_all: bool, dry_run: bool, max_repair_attempts: int = 2) -> Tuple[List[ExecutionResult], List[StepError]]:
    LOG_DIRNAME = ".agent_logs"
    log_dir = workspace / LOG_DIRNAME
    results: List[ExecutionResult] = []
    errors: List[StepError] = []
    repo_root = Path(analysis.root)
    for idx, step in enumerate(plan.steps, 1):
        print(f"\n--- Step {idx}/{len(plan.steps)}: {step.title} ---")
        print(f"cwd: {step.cwd}")
        print(f"cmd: {step.command}")
        if dry_run:
            _info("Dry run enabled, skipping execution.")
            continue
        if step.category == "setup" and not approve_all:
            ans = input("Aquest és un script del repo. L'executes? [s/N]: ").strip().lower()
            if ans not in {"s", "si", "y", "yes"}:
                _warn("Pas omès per l'usuari.")
                continue
        elif not approve_all:
            ans = input("Execute this step? [y/N]: ").strip().lower()
            if ans not in {"y", "yes", "s", "si"}:
                _warn("Step skipped by user.")
                continue
        is_background = False
        if step.category == "run":
            # Valida la comanda ORIGINAL abans del wrap (el wrap afegeix export, setsid, nohup...)
            validate_command(step.command, repo_root=repo_root)
            command_to_run, is_background = maybe_background_command(step.command)
        else:
            validate_command(step.command, repo_root=repo_root)
            command_to_run = step.command
        current_result = run_shell(command_to_run, cwd=Path(step.cwd), repo_root=repo_root, _skip_validation=True)
        current_result.step_id = step.id
        results.append(current_result)
        _write_log(log_dir, idx, step, command_to_run, current_result)
        success = current_result.returncode == 0
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
                _info(f"Servei en background registrat (PID={pid}).")
        if success and step.category in ("run", "db"):
            success = verify_step(step)
            if not success:
                current_result.returncode = 1
                current_result.stderr += "\nVerification failed: service did not become reachable.\n"
        if success:
            _info("Step succeeded.")
            continue
        _warn(f"Step failed with code {current_result.returncode}.")
        repaired = False
        fallbacks = _get_fallbacks(step, current_result)
        for fb_cmd in fallbacks:
            _info(f"Plan B: provant '{fb_cmd}'...")
            fb_result = run_shell(fb_cmd, cwd=Path(step.cwd), repo_root=repo_root)
            results.append(fb_result)
            if fb_result.returncode == 0:
                _info(f"Plan B OK: '{fb_cmd}' ha funcionat.")
                repaired = True
                break
            else:
                _warn(f"Plan B també ha fallat (rc={fb_result.returncode}).")
        if repaired:
            continue
        from bartolo.repair.debugger import IntelligentDebugger
        _debugger = IntelligentDebugger(
            model=model,
            analysis=analysis,
            workspace=workspace,
            max_repair_attempts=max_repair_attempts,
        )
        _repair = _debugger.repair(step, current_result, approve_all=approve_all)
        results.extend(r for r in _repair.execution_results if r is not current_result)
        errors.append(_repair.to_step_error(step))
        repaired = _repair.repaired
        if step.critical and not repaired:
            _execute_rollback(analysis, workspace)
            raise AgentError(f"Critical step failed: {step.title}")
    if results and not dry_run and not [e for e in errors if not e.repaired]:
        try:
            if analysis.services:
                from bartolo.kb.success import record_success
                kb_service_type = "+".join(sorted(set(s.service_type for s in analysis.services)))
                kb_manifests = sorted(set(m for s in analysis.services for m in s.manifests))
                record_success(kb_service_type, kb_manifests, [asdict(s) for s in plan.steps], analysis.repo_name)
        except Exception:
            pass
    return results, errors


def _write_log(log_dir: Path, idx: int, step: CommandStep, command_to_run: str, result: ExecutionResult) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{idx:02d}_{slugify(step.id)}.log"
    path.write_text(
        f"COMMAND: {command_to_run}\nCWD: {result.cwd}\nRETURNCODE: {result.returncode}\n\n"
        f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )


