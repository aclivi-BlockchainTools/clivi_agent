#!/usr/bin/env python3
"""
HTTP Bridge per exposar l'agent al host a OpenWebUI dins Docker.

Endpoints:
    POST /run           { "input": "<url|path>", ... } (síncron, fins a 25 min)
    POST /run/async     { "input": ... }  →  retorna {"job_id": "..."} immediat
    GET  /job/<id>      → estat i sortida acumulada del job
    GET  /jobs          → llista de jobs (en execució i acabats)
    POST /analyze       { "input": ... }
    POST /stop          { "repo": "nom|all" }
    POST /refresh       { "repo": "nom" }
    GET  /status        → JSON amb serveis registrats
    GET  /logs?repo=X   → text amb els últims logs
    GET  /health        → {"status": "ok"}
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

AGENT_PATH = Path(os.environ.get(
    "UNIVERSAL_AGENT_PATH",
    str(Path.home() / "universal-agent" / "universal_repo_agent_v5.py"),
))
WORKSPACE = Path(os.environ.get(
    "UNIVERSAL_AGENT_WORKSPACE",
    str(Path.home() / "universal-agent-workspace"),
))
AUTH_TOKEN = os.environ.get("BRIDGE_AUTH_TOKEN", "")
MAX_RESPONSE_CHARS = 6000
LAUNCH_TIMEOUT = 1500
_PORT = 9090
LOG_DIR = Path(os.environ.get("BRIDGE_LOG_DIR", str(Path.home() / ".universal-agent" / "logs")))


def _get_public_url(port: int = 9090) -> str:
    override = os.environ.get("BRIDGE_PUBLIC_URL", "").strip()
    if override:
        return override
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    return f"http://{ip}:{port}"

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_MAX_KEEP = 50


def _new_job_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _gc_old_jobs() -> None:
    with _JOBS_LOCK:
        if len(_JOBS) <= _JOBS_MAX_KEEP:
            return
        done = [(j, _JOBS[j]) for j in _JOBS if _JOBS[j]["status"] in ("done", "failed")]
        done.sort(key=lambda x: x[1]["finished_at"] or 0)
        for jid, _ in done[:len(_JOBS) - _JOBS_MAX_KEEP]:
            _JOBS.pop(jid, None)


def _run_agent_async(job_id: str, args: list, timeout: int) -> None:
    import time as _time
    cmd = [sys.executable, str(AGENT_PATH)] + args
    # Fix 2: fitxer de log per job, evita acumular output en RAM
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{job_id}.log"
    with _JOBS_LOCK:
        _JOBS[job_id]["log_path"] = str(log_path)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        with _JOBS_LOCK:
            _JOBS[job_id]["pid"] = proc.pid
            _JOBS[job_id]["status"] = "running"
        # Fix 1: sliding window de 500 línies en RAM (elimina les primeres 100 quan s'omple)
        output_lines: list = []
        with open(log_path, "w", encoding="utf-8") as log_f:
            for line in proc.stdout:  # type: ignore
                log_f.write(line)   # Fix 2: escriu a disc en streaming
                log_f.flush()
                output_lines.append(line)
                if len(output_lines) >= 500:
                    del output_lines[:100]  # Fix 1: descarta les més antigues
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = -1
            with open(log_path, "a", encoding="utf-8") as log_f:
                log_f.write(f"\n[bridge] TIMEOUT {timeout}s\n")
        # Parse escalation reports des del fitxer (una sola lectura al final)
        error_reports: list = []
        if rc != 0:
            import re as _re, json as _json
            try:
                full_out = log_path.read_text(encoding="utf-8", errors="replace")
                for _path_str in _re.findall(r"__ESCALATION_REPORT__=(.+)", full_out):
                    try:
                        with open(_path_str.strip()) as _f:
                            error_reports.append(_json.load(_f))
                    except Exception as _err:
                        sys.stderr.write(f"[bridge] escalation parse error: {_err}\n")
            except Exception:
                pass
        with _JOBS_LOCK:
            _JOBS[job_id]["returncode"] = rc
            _JOBS[job_id]["status"] = "done" if rc == 0 else "failed"
            _JOBS[job_id]["finished_at"] = _time.time()
            _JOBS[job_id]["error_reports"] = error_reports
    except Exception as e:
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["returncode"] = -99
            _JOBS[job_id]["finished_at"] = _time.time()
        try:
            with open(log_path, "a", encoding="utf-8") as log_f:
                log_f.write(f"[bridge] Error intern: {e}\n")
        except Exception:
            pass
    finally:
        _gc_old_jobs()


def _start_job(args: list, timeout: int = LAUNCH_TIMEOUT) -> str:
    import time as _time
    job_id = _new_job_id()
    with _JOBS_LOCK:
        _JOBS[job_id] = {"id": job_id, "status": "queued", "args": args,
                         "returncode": None, "pid": None, "log_path": "",
                         "started_at": _time.time(), "finished_at": None,
                         "error_reports": []}
    threading.Thread(target=_run_agent_async, args=(job_id, args, timeout), daemon=True).start()
    return job_id


def _job_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        log_path = job.get("log_path", "")
        reports = job.get("error_reports", [])
        snap = {"id": job["id"], "status": job["status"], "returncode": job["returncode"],
                "pid": job["pid"], "started_at": job["started_at"],
                "finished_at": job["finished_at"], "log_path": log_path,
                "ok": job["status"] == "done" and job["returncode"] == 0,
                "error_reports": reports,
                "escalation_prompts": [r.get("claude_code_prompt", "") for r in reports]}
    # Fix 2: llegeix les últimes 50 línies del fitxer (no carrega tot en RAM)
    out = ""
    if log_path:
        try:
            r = subprocess.run(["tail", "-n", "50", log_path],
                               capture_output=True, text=True, timeout=5)
            out = r.stdout
        except Exception:
            out = f"[bridge] no s'ha pogut llegir el log: {log_path}"
    snap["output"] = out
    return snap


def _run_agent(args: list, timeout: int = 60) -> dict:
    cmd = [sys.executable, str(AGENT_PATH)] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (("\n--- STDERR ---\n" + r.stderr) if r.stderr else "")
        if len(out) > MAX_RESPONSE_CHARS:
            out = f"... [truncat] ...\n" + out[-MAX_RESPONSE_CHARS:]
        return {"returncode": r.returncode, "output": out, "ok": r.returncode == 0}
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout {timeout}s", "returncode": -1, "output": ""}
    except Exception as e:
        return {"error": str(e), "returncode": -99, "output": ""}




# === Shell exec amb token de confirmació ===
import threading as _threading
_SHELL_TOKENS = {}
_SHELL_LOCK = _threading.Lock()
_SHELL_TOKEN_TTL = 120
SHELL_BLOCKED = ("rm -rf /", "rm -rf ~", "mkfs", ":(){:|:&};:", "dd if=", "> /dev/sda",
                 "shutdown", "reboot", "poweroff", "halt", "rm -rf $home")

def _shell_register(cmd):
    import time as _t, uuid as _u
    tok = _u.uuid4().hex[:8]
    with _SHELL_LOCK:
        now = _t.time()
        for k in list(_SHELL_TOKENS.keys()):
            if now - _SHELL_TOKENS[k]["created"] > _SHELL_TOKEN_TTL:
                _SHELL_TOKENS.pop(k, None)
        _SHELL_TOKENS[tok] = {"cmd": cmd, "created": now, "used": False}
    return tok

def _shell_consume(tok):
    import time as _t
    with _SHELL_LOCK:
        info = _SHELL_TOKENS.get(tok)
        if not info or info["used"]:
            return None
        if _t.time() - info["created"] > _SHELL_TOKEN_TTL:
            _SHELL_TOKENS.pop(tok, None)
            return None
        info["used"] = True
        return info["cmd"]

def _shell_safe(cmd):
    low = cmd.lower()
    return not any(kw in low for kw in SHELL_BLOCKED)

def _shell_execute(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, executable="/bin/bash")
        out = (r.stdout or "") + (("\n[STDERR]\n" + r.stderr) if r.stderr else "")
        if len(out) > MAX_RESPONSE_CHARS:
            out = out[-MAX_RESPONSE_CHARS:]
        return {"returncode": r.returncode, "output": out, "ok": r.returncode == 0}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "output": f"Timeout ({timeout}s)", "ok": False}
    except Exception as e:
        return {"returncode": -99, "output": f"Error: {e}", "ok": False}

UPLOAD_DIR = WORKSPACE / "_uploads"
UPLOAD_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Upload ZIP</title>
<style>body{font-family:system-ui;max-width:680px;margin:40px auto;padding:0 20px}
.drop{border:2px dashed #888;border-radius:14px;padding:50px 20px;text-align:center;background:#fff;cursor:pointer}
.drop.over{border-color:#2563eb;background:#eff6ff}
.btn{background:#2563eb;color:#fff;border:0;padding:10px 20px;border-radius:8px;cursor:pointer}
.btn-sm{background:#2563eb;color:#fff;border:0;padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px;margin-top:4px}
.result{margin-top:20px;padding:15px;border-radius:8px;font-family:monospace;font-size:13px;white-space:pre-wrap}
.ok{background:#d1fae5}.err{background:#fee2e2}
code{background:#c6f6d5;padding:2px 6px;border-radius:4px;word-break:break-all}</style></head><body>
<h1>Upload ZIP al host</h1><p>Arrossega un .zip o clica per seleccionar.</p>
<div class="drop" id="drop"><p>Arrossega un .zip aquí, o clica</p>
<input type="file" id="file" accept="*" style="display:none">
<button class="btn" id="pick">Seleccionar fitxer</button></div>
<div id="result"></div><p style="font-size:12px;color:#666">Workspace: __WORKSPACE__</p>
<script>
var drop=document.getElementById('drop'),file=document.getElementById('file'),pick=document.getElementById('pick'),result=document.getElementById('result');
pick.addEventListener('click',function(e){e.stopPropagation();e.preventDefault();file.click();});
drop.addEventListener('click',function(e){if(!pick.contains(e.target))file.click();});
file.addEventListener('change',function(){if(file.files[0])upload(file.files[0]);});
drop.addEventListener('dragenter',function(e){e.preventDefault();drop.classList.add('over');});
drop.addEventListener('dragover',function(e){e.preventDefault();drop.classList.add('over');});
drop.addEventListener('dragleave',function(e){e.preventDefault();drop.classList.remove('over');});
drop.addEventListener('drop',function(e){e.preventDefault();drop.classList.remove('over');if(e.dataTransfer.files[0])upload(e.dataTransfer.files[0]);});
function _copy(btn,txt){
  navigator.clipboard.writeText(txt).then(function(){btn.textContent='Copiat!';setTimeout(function(){btn.textContent=btn.dataset.label;},2000);}).catch(function(){btn.textContent='(copia manual)';});
}
async function upload(f){
  if(!f){result.className='result err';result.textContent='Cap fitxer seleccionat';return;}
  result.className='result';result.textContent='Pujant '+f.name+' ('+f.size+' bytes)...';
  var fd=new FormData();fd.append('file',f);
  try{
    var r=await fetch('/upload',{method:'POST',body:fd});
    var d=await r.json();
    if(d.error){
      result.className='result err';
      result.textContent='Error: '+d.error;
    }else{
      var path=d.path,name=path.split('/').pop(),bartolo='munta el repo '+path;
      result.className='result ok';
      result.innerHTML='<b>Fitxer pujat!</b>\nNom: '+name+' | Mida: '+f.size+' bytes\nRuta al host: '+path+'\n\n'
        +'<button class="btn-sm" id="cp1" data-label="Copia la ruta">Copia la ruta</button>\n\n'
        +'Text per a Bartolo (enganxa al xat):\n<code>'+bartolo+'</code>\n'
        +'<button class="btn-sm" id="cp2" data-label="Copia text Bartolo">Copia text Bartolo</button>';
      document.getElementById('cp1').onclick=function(){_copy(this,path);};
      document.getElementById('cp2').onclick=function(){_copy(this,bartolo);};
    }
  }catch(err){
    result.className='result err';
    result.textContent='Error de xarxa: '+(err.message||String(err));
    console.error('[upload]',err);
  }
}
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[bridge] {self.address_string()} - {fmt % args}\n")

    def _auth_ok(self) -> bool:
        if not AUTH_TOKEN:
            return True
        return self.headers.get("X-Auth-Token", "") == AUTH_TOKEN

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Auth-Token")
        self.end_headers()

    def _handle_upload_post(self):
        try:
            import cgi
            ctype = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ctype:
                self._json(400, {"error": "expected multipart/form-data"}); return
            form = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype},
            )
            if "file" not in form:
                self._json(400, {"error": "missing 'file' field"}); return
            item = form["file"]
            import os as _os23
            fname = _os23.path.basename(item.filename or "")
            if not fname.lower().endswith(".zip"):
                self._json(400, {"error": "only .zip files accepted"}); return
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOAD_DIR / fname
            data = item.file.read()
            dest.write_bytes(data)
            self._json(200, {"status": "uploaded", "path": str(dest), "size": len(data),
                             "hint": "POST /run/async amb input=" + str(dest)})
        except Exception as e:
            self._json(500, {"error": "upload failed: " + str(e)})

    def do_GET(self) -> None:
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"}); return
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/upload"):
            html = UPLOAD_HTML.replace("__WORKSPACE__", str(WORKSPACE))
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "agent_path": str(AGENT_PATH),
                             "agent_exists": AGENT_PATH.exists(), "workspace": str(WORKSPACE),
                             "public_url": _get_public_url(_PORT)})
        elif parsed.path == "/status":
            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--status"], timeout=30))
        elif parsed.path == "/logs":
            q = parse_qs(parsed.query)
            repo = q.get("repo", [""])[0]
            if not repo:
                self._json(400, {"error": "missing 'repo'"}); return
            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--logs", repo], timeout=30))
        elif parsed.path.startswith("/job/"):
            jid = parsed.path.split("/job/", 1)[1].strip("/")
            snap = _job_snapshot(jid)
            if not snap:
                self._json(404, {"error": f"job {jid} no trobat"}); return
            self._json(200, snap)
        elif parsed.path == "/jobs":
            with _JOBS_LOCK:
                summary = [{"id": j["id"], "status": j["status"],
                            "started_at": j["started_at"], "finished_at": j["finished_at"],
                            "returncode": j["returncode"]} for j in _JOBS.values()]
            summary.sort(key=lambda x: x["started_at"], reverse=True)
            self._json(200, {"jobs": summary, "count": len(summary)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"}); return
        # === v2.3 routes === (multipart intercept)
        if urlparse(self.path).path == "/upload":
            self._handle_upload_post(); return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json(400, {"error": "invalid JSON"}); return
        parsed = urlparse(self.path)
        def _base_args(inp):
            a = ["--input", inp, "--workspace", str(WORKSPACE),
                 "--execute", "--approve-all", "--non-interactive"]
            if body.get("dockerize"):
                a.append("--dockerize")
            if body.get("llm_primary"):
                a.append("--llm-primary")
            else:
                a.append("--no-model-refine")
            a.append("--no-readme")
            return a
        if parsed.path == "/run":
            inp = str(body.get("input", "")).strip()
            if not inp:
                self._json(400, {"error": "missing 'input'"}); return
            self._json(200, _run_agent(_base_args(inp), timeout=LAUNCH_TIMEOUT))
        elif parsed.path == "/run/async":
            inp = str(body.get("input", "")).strip()
            if not inp:
                self._json(400, {"error": "missing 'input'"}); return
            jid = _start_job(_base_args(inp), timeout=LAUNCH_TIMEOUT)
            self._json(202, {"job_id": jid, "status": "queued",
                             "message": f"Feina iniciada. Consulta amb GET /job/{jid}"})
        elif parsed.path == "/analyze":
            inp = str(body.get("input", "")).strip()
            if not inp:
                self._json(400, {"error": "missing 'input'"}); return
            self._json(200, _run_agent(["--input", inp, "--workspace", str(WORKSPACE),
                                        "--no-readme", "--no-model-refine"], timeout=300))
        elif parsed.path == "/stop":
            repo = str(body.get("repo", "all")).strip() or "all"
            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--stop", repo], timeout=30))
        elif parsed.path == "/refresh":
            repo = str(body.get("repo", "")).strip()
            if not repo:
                self._json(400, {"error": "missing 'repo'"}); return
            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--refresh", repo], timeout=60))
        elif parsed.path == "/exec_shell":
            cmd = str(body.get("cmd", "")).strip()
            if not cmd:
                self._json(400, {"error": "missing 'cmd'"}); return
            if not _shell_safe(cmd):
                self._json(403, {"error": "command blocked by safety filter"}); return
            tok = _shell_register(cmd)
            self._json(200, {"status": "pending_confirmation", "token": tok, "cmd": cmd,
                             "expires_in": _SHELL_TOKEN_TTL,
                             "hint": "POST /exec_shell/confirm amb {\"token\": tok}"})
        elif parsed.path == "/exec_shell/confirm":
            tok = str(body.get("token", "")).strip()
            if not tok:
                self._json(400, {"error": "missing 'token'"}); return
            cmd = _shell_consume(tok)
            if cmd is None:
                self._json(400, {"error": "invalid or expired token"}); return
            try:
                timeout = int(body.get("timeout", 60))
            except Exception:
                timeout = 60
            self._json(200, _shell_execute(cmd, timeout=timeout))
        else:
            self._json(404, {"error": "not found"})


def main():
    global _PORT
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9090)
    p.add_argument("--bind", default="0.0.0.0")
    args = p.parse_args()
    _PORT = args.port
    print(f"🔗 Agent HTTP Bridge (async)")
    print(f"   Workspace  : {WORKSPACE}")
    print(f"   Agent path : {AGENT_PATH} (exists: {AGENT_PATH.exists()})")
    print(f"   Listening  : http://{args.bind}:{args.port}")
    print(f"   Endpoints  : POST /run /run/async /analyze /stop /refresh  ·  GET /status /logs /health /job/<id> /jobs")
    if AUTH_TOKEN:
        print(f"   Auth       : X-Auth-Token required")
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Aturant bridge...")
        server.shutdown()


if __name__ == "__main__":
    main()
