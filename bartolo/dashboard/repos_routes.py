"""bartolo/dashboard/repos_routes.py — Gestió de repos (status, stop, launch, logs)."""

from __future__ import annotations

import sys
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from urllib.parse import parse_qs

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from universal_repo_agent_v5 import DEFAULT_WORKSPACE, LOG_DIRNAME  # type: ignore
from bartolo.executor import load_services_registry, stop_services
from bartolo.dashboard.templates import render_logs

router = APIRouter()
AGENT_SCRIPT = PROJECT_ROOT / "universal_repo_agent_v5.py"


def _launch_async(input_value: str, dockerize: bool, approve_all: bool, no_refine: bool) -> None:
    cmd = [sys.executable, str(AGENT_SCRIPT), "--input", input_value, "--execute",
           "--non-interactive", "--workspace", str(DEFAULT_WORKSPACE)]
    if approve_all:
        cmd.append("--approve-all")
    if dockerize:
        cmd.append("--dockerize")
    if no_refine:
        cmd.append("--no-model-refine")
    log_dir = DEFAULT_WORKSPACE / LOG_DIRNAME
    log_dir.mkdir(parents=True, exist_ok=True)
    idx = len(list(log_dir.glob("dashboard-launch-*")))
    launch_log = log_dir / f"dashboard-launch-{idx}.log"
    with launch_log.open("w") as f:
        f.write(f"CMD: {' '.join(cmd)}\n\n")
        f.flush()
        subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(DEFAULT_WORKSPACE))


@router.get("/api/status")
async def api_status():
    return load_services_registry(DEFAULT_WORKSPACE)


@router.get("/api/logs")
async def api_logs(request: Request):
    params = parse_qs(str(request.query_params))
    repo = params.get("repo", [""])[0]
    step = params.get("step", [""])[0]
    return HTMLResponse(content=render_logs(repo, step, DEFAULT_WORKSPACE))


@router.post("/api/stop")
async def api_stop(request: Request):
    body = await request.body()
    params = parse_qs(body.decode("utf-8"))
    repo = params.get("repo", ["all"])[0]
    stop_services(DEFAULT_WORKSPACE, repo_name=repo)
    return {"ok": True, "stopped": repo}


@router.post("/api/restart")
async def api_restart(request: Request):
    """Restart a repo by stopping and re-launching."""
    body = await request.body()
    params = parse_qs(body.decode("utf-8"))
    repo = params.get("repo", [""])[0].strip()
    if not repo:
        return {"ok": False, "error": "repo required"}
    # Stop first
    stop_services(DEFAULT_WORKSPACE, repo_name=repo)
    # Re-launch via agent with refresh
    repo_path = DEFAULT_WORKSPACE / repo
    if not repo_path.exists():
        return {"ok": False, "error": f"Repo {repo} no trobat"}
    import time

    def _restart():
        subprocess.run(
            [sys.executable, str(AGENT_SCRIPT), "--input", str(repo_path), "--execute",
             "--approve-all", "--non-interactive", "--no-readme", "--no-model-refine",
             "--workspace", str(DEFAULT_WORKSPACE)],
            capture_output=True, text=True, timeout=600, cwd=str(DEFAULT_WORKSPACE)
        )
    threading.Thread(target=_restart, daemon=True).start()
    return {"ok": True, "message": f"Reiniciant {repo}"}


@router.post("/api/launch")
async def api_launch(request: Request):
    body = await request.body()
    params = parse_qs(body.decode("utf-8"))
    input_value = params.get("input", [""])[0].strip()
    if not input_value:
        return {"ok": False, "error": "input required"}
    dockerize = "dockerize" in params
    approve_all = "approve_all" in params
    no_refine = "no_refine" in params
    threading.Thread(target=_launch_async, args=(input_value, dockerize, approve_all, no_refine), daemon=True).start()
    return {"ok": True, "message": f"Llançant {input_value}"}


@router.get("/api/timeline/{repo}")
async def api_timeline(repo: str):
    """Extract timeline events from agent log files."""
    log_dir = DEFAULT_WORKSPACE / LOG_DIRNAME
    events = []
    if not log_dir.exists():
        return {"repo": repo, "events": events}
    import re
    for f in sorted(log_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True):
        if repo not in f.name:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            for line in content.split("\n"):
                # Look for timestamped events: [HH:MM:SS] or YYYY-MM-DD HH:MM:SS
                ts_match = re.match(r'^\[?(\d{2}:\d{2}(?::\d{2})?)\]?\s*(.+)$', line)
                if ts_match:
                    events.append({"time": ts_match.group(1), "event": ts_match.group(2)[:200]})
                elif re.search(r'(ERROR|FAIL|FATAL|exception|Traceback)', line, re.IGNORECASE):
                    events.append({"time": "", "event": line[:200], "level": "error"})
                elif re.search(r'(SUCCESS|OK|complet|cORRECTE)', line, re.IGNORECASE):
                    events.append({"time": "", "event": line[:200], "level": "ok"})
        except Exception:
            pass
    return {"repo": repo, "events": events[-50:]}
