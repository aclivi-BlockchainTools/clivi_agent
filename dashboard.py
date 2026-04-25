#!/usr/bin/env python3
"""
dashboard.py — Dashboard web mínim per universal_repo_agent_v5.

Utilitza només la biblioteca estàndard (http.server) — zero dependències extra.
Serveix a http://localhost:9999 i et permet:
  - Veure repos i serveis registrats (amb PID + estat RUNNING/STOPPED)
  - Veure logs de cada servei (streaming via auto-refresh)
  - Aturar serveis (botó Stop)
  - Reexecutar l'agent amb --input des del formulari

Ús:
    python3 dashboard.py                 # arrenca a http://0.0.0.0:9999
    python3 dashboard.py --port 9000     # port custom
    python3 dashboard.py --workspace ... # workspace custom

Requeriments: només Python 3.8+ i que universal_repo_agent_v5.py sigui al mateix directori.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from universal_repo_agent_v5 import (  # type: ignore
    DEFAULT_WORKSPACE, SERVICES_REGISTRY, LOG_DIRNAME,
    load_services_registry, stop_services,
)

WORKSPACE = DEFAULT_WORKSPACE
AGENT_SCRIPT = THIS_DIR / "universal_repo_agent_v5.py"


INDEX_HTML = """<!doctype html>
<html lang="ca">
<head>
<meta charset="utf-8">
<title>Universal Agent Dashboard</title>
<meta http-equiv="refresh" content="5">
<style>
  :root { --bg:#0d1117; --fg:#c9d1d9; --muted:#8b949e; --ok:#3fb950; --bad:#f85149; --card:#161b22; --accent:#58a6ff; --border:#30363d; }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--fg); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0; padding: 24px; }
  h1 { color: var(--accent); margin: 0 0 4px; font-size: 24px; }
  .sub { color: var(--muted); margin-bottom: 24px; font-size: 13px; }
  .repo { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
  .repo h2 { margin: 0 0 12px; font-size: 16px; color: var(--accent); }
  .svc { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-left: 3px solid var(--border); margin-bottom: 6px; background: #0d1117; }
  .svc.run { border-left-color: var(--ok); }
  .svc.stop { border-left-color: var(--bad); opacity: 0.6; }
  .svc-info { flex: 1; min-width: 0; }
  .svc-info code { display: block; font-size: 12px; color: var(--muted); word-break: break-all; white-space: normal; }
  .svc-info strong { color: var(--fg); }
  .actions { display: flex; gap: 6px; flex-shrink: 0; }
  .actions a, .actions button { color: var(--fg); background: transparent; border: 1px solid var(--border); padding: 4px 10px; font-size: 12px; text-decoration: none; border-radius: 4px; cursor: pointer; font-family: inherit; }
  .actions a:hover, .actions button:hover { background: var(--border); }
  .actions .danger { border-color: var(--bad); color: var(--bad); }
  .actions .danger:hover { background: var(--bad); color: white; }
  form.launch { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap; }
  form.launch input[type=text] { flex: 1; min-width: 300px; background: #0d1117; border: 1px solid var(--border); color: var(--fg); padding: 8px 12px; border-radius: 4px; font-family: inherit; font-size: 13px; }
  form.launch input[type=submit] { background: var(--accent); color: #0d1117; border: 0; padding: 8px 18px; border-radius: 4px; font-weight: bold; cursor: pointer; font-family: inherit; }
  form.launch input[type=submit]:hover { opacity: 0.9; }
  form.launch label { color: var(--muted); font-size: 12px; display: flex; align-items: center; gap: 4px; }
  pre.logs { background: #010409; border: 1px solid var(--border); border-radius: 4px; padding: 12px; max-height: 500px; overflow: auto; font-size: 11px; color: var(--muted); white-space: pre-wrap; word-break: break-all; }
  .empty { color: var(--muted); font-style: italic; padding: 24px; text-align: center; }
  .flash { background: #1f2937; border-left: 3px solid var(--accent); padding: 8px 12px; margin-bottom: 16px; font-size: 13px; }
  a { color: var(--accent); }
</style>
</head>
<body>
  <h1>🚀 Universal Agent Dashboard</h1>
  <div class="sub">Workspace: {WORKSPACE} · Auto-refresh 5s · <a href="/refresh">↻ Refrescar</a></div>
  {FLASH}
  <form class="launch" action="/launch" method="post">
    <input type="text" name="input" placeholder="URL git / carpeta / .zip (ex: https://github.com/user/repo.git)" required>
    <label><input type="checkbox" name="dockerize" value="1"> dockerize</label>
    <label><input type="checkbox" name="approve_all" value="1" checked> approve-all</label>
    <label><input type="checkbox" name="no_model_refine" value="1" checked> sense LLM</label>
    <input type="submit" value="▶ Llençar">
  </form>
  {REPOS}
</body>
</html>
"""


def render_index(flash: str = "") -> str:
    data = load_services_registry(WORKSPACE)
    if not data or not any(services for services in data.values()):
        repos_html = '<div class="empty">Cap repo arrencat encara. Llança un amb el formulari de dalt.</div>'
    else:
        blocks = []
        for repo_name, services in data.items():
            if not services:
                continue
            svc_html_parts = []
            for svc in services:
                pid = svc.get("pid")
                alive = False
                if pid:
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except Exception:
                        alive = False
                cls = "run" if alive else "stop"
                status_text = "🟢 RUNNING" if alive else "🔴 STOPPED"
                svc_html_parts.append(f"""
                  <div class="svc {cls}">
                    <div class="svc-info">
                      <strong>{html.escape(status_text)} · PID {pid}</strong> · step: <code style="display:inline">{html.escape(svc.get('step_id',''))}</code>
                      <code>{html.escape(svc.get('command',''))}</code>
                    </div>
                    <div class="actions">
                      <a href="/logs?repo={html.escape(repo_name)}&step={html.escape(svc.get('step_id',''))}">📜 Logs</a>
                      <form action="/stop" method="post" style="display:inline">
                        <input type="hidden" name="repo" value="{html.escape(repo_name)}">
                        <button class="danger">⏹ Stop</button>
                      </form>
                    </div>
                  </div>
                """)
            blocks.append(f"""
            <div class="repo">
              <h2>📦 {html.escape(repo_name)}</h2>
              {''.join(svc_html_parts)}
            </div>
            """)
        repos_html = "\n".join(blocks)
    return (
        INDEX_HTML
        .replace("{WORKSPACE}", html.escape(str(WORKSPACE)))
        .replace("{REPOS}", repos_html)
        .replace("{FLASH}", f'<div class="flash">{html.escape(flash)}</div>' if flash else "")
    )


def render_logs(repo: str, step: str) -> str:
    log_dir = WORKSPACE / LOG_DIRNAME
    content_parts = []
    for f in sorted(log_dir.glob(f"*{step}*.log")):
        content_parts.append(f"=== {f.name} ===\n" + f.read_text(encoding="utf-8", errors="ignore")[-8000:])
    repo_dir = WORKSPACE / repo
    for sub in ("backend", "frontend", ""):
        candidate = (repo_dir / sub / ".agent_last_run.log") if sub else (repo_dir / ".agent_last_run.log")
        if candidate.exists():
            content_parts.append(f"=== {candidate.relative_to(WORKSPACE)} ===\n" + candidate.read_text(encoding="utf-8", errors="ignore")[-8000:])
    content = "\n\n".join(content_parts) or "(sense logs)"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Logs {repo}/{step}</title>
<meta http-equiv="refresh" content="3">
<style>body{{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,monospace;margin:0;padding:24px}}
a{{color:#58a6ff}}pre{{background:#010409;padding:12px;border-radius:4px;white-space:pre-wrap;word-break:break-all;font-size:11px;color:#8b949e;max-height:85vh;overflow:auto}}</style></head>
<body><a href="/">← Tornar</a> · Auto-refresh 3s · <strong>{html.escape(repo)}/{html.escape(step)}</strong><pre>{html.escape(content)}</pre></body></html>"""


def launch_agent_async(input_value: str, dockerize: bool, approve_all: bool, no_model_refine: bool) -> None:
    cmd = [sys.executable, str(AGENT_SCRIPT), "--input", input_value, "--execute", "--non-interactive", "--workspace", str(WORKSPACE)]
    if approve_all:
        cmd.append("--approve-all")
    if dockerize:
        cmd.append("--dockerize")
    if no_model_refine:
        cmd.append("--no-model-refine")
    launch_log = WORKSPACE / LOG_DIRNAME / f"dashboard-launch-{len(list((WORKSPACE / LOG_DIRNAME).glob('dashboard-launch-*')))}.log"
    launch_log.parent.mkdir(parents=True, exist_ok=True)
    with launch_log.open("w") as f:
        f.write(f"CMD: {' '.join(cmd)}\n\n")
        f.flush()
        subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(WORKSPACE))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/refresh"):
            self._send(200, render_index())
        elif parsed.path == "/logs":
            params = parse_qs(parsed.query)
            self._send(200, render_logs(params.get("repo", [""])[0], params.get("step", [""])[0]))
        elif parsed.path == "/api/status":
            self._send(200, json.dumps(load_services_registry(WORKSPACE), indent=2), "application/json")
        else:
            self._send(404, "Not found", "text/plain")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = parse_qs(body)
        if self.path == "/stop":
            repo = params.get("repo", ["all"])[0]
            stop_services(WORKSPACE, repo_name=repo)
            self._redirect("/")
        elif self.path == "/launch":
            input_value = params.get("input", [""])[0].strip()
            if not input_value:
                self._send(400, "input required", "text/plain"); return
            dockerize = "dockerize" in params
            approve_all = "approve_all" in params
            no_model_refine = "no_model_refine" in params
            threading.Thread(target=launch_agent_async, args=(input_value, dockerize, approve_all, no_model_refine), daemon=True).start()
            self._redirect("/")
        else:
            self._send(404, "Not found", "text/plain")


def main() -> int:
    global WORKSPACE
    parser = argparse.ArgumentParser(description="Dashboard web per universal_repo_agent_v5")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    args = parser.parse_args()
    WORKSPACE = Path(args.workspace).expanduser().resolve()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / LOG_DIRNAME).mkdir(parents=True, exist_ok=True)
    print(f"🚀 Dashboard a http://{args.host}:{args.port}  (workspace: {WORKSPACE})")
    print(f"   Ctrl+C per aturar. Ruta del registry: {WORKSPACE / SERVICES_REGISTRY}")
    server = HTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAturant...")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
