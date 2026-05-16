"""bartolo/dashboard/repos_routes.py — Gestió de repos (status, stop, launch, logs)."""

from __future__ import annotations

import sys
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from urllib.parse import parse_qs
import asyncio

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from universal_repo_agent_v5 import DEFAULT_WORKSPACE, LOG_DIRNAME  # type: ignore
from bartolo.executor import load_services_registry, stop_services
from bartolo.dashboard.templates import render_logs

router = APIRouter()
AGENT_SCRIPT = PROJECT_ROOT / "universal_repo_agent_v5.py"

# Ports coneguts per identificar serveis sense info de procés
_KNOWN_PORTS = {
    11434: ("Ollama", "ollama"),
    9999: ("Bartolo Dashboard", "bartolo"),
    9090: ("Bartolo Bridge", "bartolo"),
    3000: ("OpenWebUI / React Dev", "web"),
    8082: ("Free Claude Code", "ai"),
    27017: ("MongoDB", "database"),
    3306: ("MySQL", "database"),
    3307: ("MySQL (alt)", "database"),
    5432: ("PostgreSQL", "database"),
    6379: ("Redis", "database"),
    631: ("CUPS (impressió)", "system"),
    22: ("SSH", "system"),
    53: ("DNS (systemd-resolved)", "system"),
    4369: ("Erlang Port Mapper", "epmd"),
}


def _scan_system_services() -> list:
    """Escaneja tots els ports TCP escoltant i identifica serveis coneguts."""
    import re as _re
    services = []
    try:
        r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return services
        for line in r.stdout.strip().splitlines()[1:]:
            line = line.strip()
            if not line or "LISTEN" not in line:
                continue
            # Parse port de la columna d'escolta (format IP:PORT)
            parts = line.split()
            listen_col = None
            for p in parts:
                if ":" in p and not p.startswith("users:"):
                    listen_col = p
                    break
            if not listen_col:
                continue
            addr, port_str = listen_col.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                continue
            # Extreure procés i PID
            pid = None
            process = ""
            m = _re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
            if m:
                process = m.group(1)
                pid = int(m.group(2))
            # Identificar servei
            name = ""
            service_type = "unknown"
            known = False
            if pid and process in ("python3", "python"):
                try:
                    cmdline = Path(f"/proc/{pid}/cmdline").read_text(errors="ignore")
                    cmdline = cmdline.replace("\x00", " ")
                    if "dashboard.py" in cmdline:
                        name = "Bartolo Dashboard"
                        service_type = "bartolo"
                        known = True
                    elif "agent_http_bridge" in cmdline:
                        name = "Bartolo Bridge"
                        service_type = "bartolo"
                        known = True
                    elif "uvicorn" in cmdline:
                        name = "Uvicorn"
                        service_type = "python"
                        known = True
                    elif "streamlit" in cmdline:
                        name = "Streamlit"
                        service_type = "python"
                        known = True
                    elif "free-claude-code" in cmdline:
                        name = "Free Claude Code"
                        service_type = "ai"
                        known = True
                    else:
                        name = process
                except Exception:
                    name = process
            elif "ollama" in process.lower():
                name = "Ollama"
                service_type = "ollama"
                known = True
            elif "node" in process:
                name = "Node.js"
                service_type = "node"
                known = True
            elif "docker-proxy" in process or "dockerd" in process:
                name = "Docker"
                service_type = "docker"
                known = True
            elif "php" in process:
                name = "PHP Built-in Server"
                service_type = "php"
                known = True
            elif "sshd" in process:
                name = "SSH Server"
                service_type = "system"
                known = True
            if not name:
                info = _KNOWN_PORTS.get(port)
                if info:
                    name, service_type = info
                    known = True
                else:
                    name = process or f"Servei desconegut"
            services.append({
                "port": port,
                "pid": pid,
                "process": process,
                "name": name,
                "address": addr,
                "known": known,
                "service_type": service_type,
            })
    except Exception:
        pass
    return services


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
    data = load_services_registry(DEFAULT_WORKSPACE)
    # Scan Docker containers for databases
    try:
        import subprocess as _sp
        r = _sp.run(
            ["docker", "ps", "--format", "{{.Names}} {{.Ports}}", "--filter", "name=agent-"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            from bartolo.provisioner import DB_DOCKER_CONFIGS
            databases = []
            for line in r.stdout.strip().splitlines():
                parts = line.strip().split(maxsplit=1)
                if not parts:
                    continue
                container = parts[0]
                for db_type, cfg in DB_DOCKER_CONFIGS.items():
                    if cfg.get("container") == container:
                        port = cfg["port"]
                        databases.append({
                            "type": db_type,
                            "container": container,
                            "port": port,
                            "connection_url": cfg.get("url_template", ""),
                        })
            if databases:
                data["_databases"] = databases
    except Exception:
        pass
    data["_system"] = _scan_system_services()
    return data


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
    log_dir = DEFAULT_WORKSPACE / LOG_DIRNAME
    log_dir.mkdir(parents=True, exist_ok=True)
    idx = len(list(log_dir.glob("dashboard-restart-*")))
    restart_log = log_dir / f"dashboard-restart-{idx}.log"

    def _restart():
        try:
            with restart_log.open("w") as f:
                cmd = [sys.executable, str(AGENT_SCRIPT), "--input", str(repo_path), "--execute",
                       "--approve-all", "--non-interactive", "--no-readme", "--no-model-refine",
                       "--workspace", str(DEFAULT_WORKSPACE)]
                f.write(f"CMD: {' '.join(cmd)}\n\n")
                f.flush()
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                               text=True, timeout=600, cwd=str(DEFAULT_WORKSPACE))
        except subprocess.TimeoutExpired:
            with restart_log.open("a") as f:
                f.write("\n[TIMEOUT] L'agent ha excedit els 10 minuts\n")
        except Exception as e:
            with restart_log.open("a") as f:
                f.write(f"\n[ERROR] {e}\n")
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


@router.websocket("/ws/logs/{repo}")
async def websocket_logs(ws: WebSocket, repo: str):
    await ws.accept()
    log_dir = DEFAULT_WORKSPACE / LOG_DIRNAME
    positions = {}  # filename -> last read byte position
    # Send initial tail
    if log_dir.exists():
        all_lines = []
        for f in sorted(log_dir.glob(f"*{repo}*.log"), key=lambda x: x.stat().st_mtime):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                lines = content.split("\n")
                all_lines.extend(lines[-50:])
                positions[str(f)] = f.stat().st_size
            except Exception:
                pass
        if all_lines:
            await ws.send_json({"type": "init", "lines": all_lines[-50:]})
        else:
            await ws.send_json({"type": "init", "lines": []})
    try:
        while True:
            await asyncio.sleep(0.5)
            if not log_dir.exists():
                continue
            new_lines = []
            for f in sorted(log_dir.glob(f"*{repo}*.log"), key=lambda x: x.stat().st_mtime):
                fkey = str(f)
                try:
                    size = f.stat().st_size
                    pos = positions.get(fkey, 0)
                    if size > pos:
                        with open(f, "rb") as fh:
                            fh.seek(pos)
                            chunk = fh.read(size - pos)
                            lines = chunk.decode("utf-8", errors="ignore").split("\n")
                            for line in lines:
                                if line.strip():
                                    new_lines.append(line)
                        positions[fkey] = size
                    elif pos == 0 and fkey not in positions:
                        # New file detected
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        lines = [l for l in content.split("\n") if l.strip()]
                        if lines:
                            new_lines.extend(lines[-10:])
                        positions[fkey] = size
                except Exception:
                    pass
            for line in new_lines:
                await ws.send_json({"type": "line", "text": line})
            await ws.send_json({"type": "heartbeat"})
    except (WebSocketDisconnect, Exception):
        pass
