#!/usr/bin/env python3
"""
HTTP Bridge per exposar l'agent al host a OpenWebUI dins Docker.

Endpoints:
    POST /run           { "input": "<url|path>", ... } (síncron, fins a 25 min)
    POST /run/async     { "input": ... }  →  retorna {"job_id": "..."} immediat
    GET  /job/<id>           → estat i sortida acumulada del job
    GET  /job/<id>/stream    → últimes N línies del log (polling; ?n=50)
    GET  /jobs               → llista de jobs (en execució i acabats)
    POST /analyze       { "input": ... }
    POST /stop                    { "repo": "nom|all" }
    POST /refresh                 { "repo": "nom" }
    POST /update_container/<nom>  → docker pull + stop + rm + run (mateixos params)
    POST /wizard/start  { "repo_url": "...", "rapid": false }
    POST /wizard/step   { "wizard_id": "...", "answer": "..." }
    GET  /wizard/<id>   → estat actual del wizard
    GET  /status        → JSON amb serveis registrats
    GET  /logs?repo=X   → text amb els últims logs
    GET  /health        → {"status": "ok"}
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time as _time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

# Router d'intencions (opcional — graceful fallback si no existeix)
try:
    from bartolo_router import classify as _router_classify, extract_cmd_l1 as _router_extract_cmd
    _ROUTER_AVAILABLE = True
except ImportError:
    _ROUTER_AVAILABLE = False

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
    import time as _time, gc as _gc
    cmd = [sys.executable, str(AGENT_PATH)] + args
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
        # Stream output directament a disc — no acumular res en RAM
        with open(log_path, "w", encoding="utf-8") as log_f:
            for line in proc.stdout:  # type: ignore
                log_f.write(line)
                log_f.flush()
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = -1
            with open(log_path, "a", encoding="utf-8") as log_f:
                log_f.write(f"\n[bridge] TIMEOUT {timeout}s\n")
        # Parse escalation reports des del fitxer
        error_reports: list = []
        if rc != 0:
            import re as _re, json as _json
            try:
                # Llegeix només les primeres 500KB per buscar reports d'escalació
                with open(log_path, "r", encoding="utf-8", errors="replace") as _f:
                    full_out = _f.read(524288)
                for _path_str in _re.findall(r"__ESCALATION_REPORT__=(.+)", full_out):
                    try:
                        with open(_path_str.strip()) as _f2:
                            error_reports.append(_json.load(_f2))
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
        _gc.collect()  # Alliberar memòria després de cada job


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


def _job_stream(job_id: str, n: int = 50) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        log_path = job.get("log_path", "")
        snap = {"id": job["id"], "status": job["status"], "started_at": job["started_at"]}
    out = ""
    if log_path:
        try:
            r = subprocess.run(["tail", "-n", str(n), log_path],
                               capture_output=True, text=True, timeout=5)
            out = r.stdout
        except Exception:
            out = ""
    snap["lines"] = out
    snap["n"] = n
    return snap


def _run_agent(args: list, timeout: int = 60) -> dict:
    cmd = [sys.executable, str(AGENT_PATH)] + args
    import tempfile as _tf, gc as _gc
    out_f = _tf.NamedTemporaryFile(mode="w+", suffix=".log", delete=False, encoding="utf-8", errors="replace")
    err_f = _tf.NamedTemporaryFile(mode="w+", suffix=".log", delete=False, encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, text=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            out_f.write("\n[bridge] TIMEOUT\n")
        out_f.close()
        err_f.close()
        # Llegeix només les últimes línies dels fitxers (max 6000 chars)
        out = Path(out_f.name).read_text(errors="replace")
        err = Path(err_f.name).read_text(errors="replace")
        if err:
            out += "\n--- STDERR ---\n" + err
        if len(out) > MAX_RESPONSE_CHARS:
            out = f"... [truncat] ...\n" + out[-MAX_RESPONSE_CHARS:]
        _gc.collect()
        return {"returncode": proc.returncode, "output": out, "ok": proc.returncode == 0}
    except Exception as e:
        return {"error": str(e), "returncode": -99, "output": ""}
    finally:
        Path(out_f.name).unlink(missing_ok=True)
        Path(err_f.name).unlink(missing_ok=True)




# === Shell exec amb token de confirmació ===
import threading as _threading
_SHELL_TOKENS = {}
_SHELL_LOCK = _threading.Lock()
_SHELL_TOKEN_TTL = 120
SHELL_BLOCKED = ("rm -rf /", "rm -rf ~", "mkfs", ":(){:|:&};:", "dd if=", "> /dev/sda",
                 "shutdown", "reboot", "poweroff", "halt", "rm -rf $home",
                 "docker stop open-webui", "docker rm open-webui", "docker kill open-webui",
                 "docker stop open-webui-pipelines", "docker rm open-webui-pipelines")

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
    import tempfile as _tf_shell, os as _os_shell
    out_f = _tf_shell.NamedTemporaryFile(mode="w+", suffix=".log", delete=False, encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=out_f, stderr=subprocess.STDOUT,
                                executable="/bin/bash")
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            out_f.write(f"\n[bridge] Timeout ({timeout}s)\n")
        out_f.close()
        out_text = Path(out_f.name).read_text(errors="replace")
        out = out_text
        if len(out) > MAX_RESPONSE_CHARS:
            out = out[-MAX_RESPONSE_CHARS:]
        return {"returncode": proc.returncode, "output": out, "ok": proc.returncode == 0}
    except Exception as e:
        return {"returncode": -99, "output": f"Error: {e}", "ok": False}
    finally:
        Path(out_f.name).unlink(missing_ok=True)

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

# =============================================================================
# WORKSPACE SERVICES — tracking de serveis start.sh (PIDs a .logs/*.pid)
# =============================================================================

def _workspace_services() -> Dict[str, Any]:
    """Escaneja el workspace per serveis arrencats via start.sh (.logs/*.pid)."""
    import os as _os
    result: Dict[str, Any] = {}
    ws = str(WORKSPACE)
    try:
        for repo_name in sorted(_os.listdir(ws)):
            if repo_name.startswith('.') or repo_name.startswith('_'):
                continue
            logs_dir = _os.path.join(ws, repo_name, ".logs")
            if not _os.path.isdir(logs_dir):
                continue
            services: Dict[str, Any] = {}
            for pid_file in sorted(_os.listdir(logs_dir)):
                if not pid_file.endswith(".pid"):
                    continue
                svc_name = pid_file[:-4]
                try:
                    with open(_os.path.join(logs_dir, pid_file)) as f:
                        pid = int(f.read().strip())
                    try:
                        _os.kill(pid, 0)
                        running = True
                    except ProcessLookupError:
                        running = False
                    except PermissionError:
                        running = True
                    services[svc_name] = {"pid": pid, "running": running}
                except Exception:
                    pass
            if services:
                result[repo_name] = services
    except Exception as e:
        result["_error"] = str(e)

    # Escaneja contenidors Docker de BD (agent-postgres, agent-mongo, etc.)
    try:
        r = subprocess.run(
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
                ports_raw = parts[1] if len(parts) > 1 else ""
                # Busca el tipus de BD per nom de contenidor
                for db_type, cfg in DB_DOCKER_CONFIGS.items():
                    if cfg.get("container") == container:
                        port = cfg["port"]
                        databases.append({
                            "type": db_type,
                            "container": container,
                            "port": port,
                            "connection_url": cfg.get("url_template", ""),
                        })
                        break
            if databases:
                result["_databases"] = databases
    except FileNotFoundError:
        pass  # Docker no instal·lat
    except Exception:
        pass  # Docker no disponible o error

    return result


def _workspace_stop(repo: str) -> Dict[str, Any]:
    """Atura serveis d'un repo (o tots) usant start.sh stop o matant PIDs."""
    import os as _os
    ws = str(WORKSPACE)
    stopped: list = []
    errors: list = []
    repos_to_stop: list = []

    if repo == "all":
        try:
            repos_to_stop = [
                d for d in _os.listdir(ws)
                if not d.startswith('.') and not d.startswith('_')
                and _os.path.isdir(_os.path.join(ws, d, ".logs"))
            ]
        except Exception:
            pass
    else:
        repos_to_stop = [repo]

    for rname in repos_to_stop:
        rpath = _os.path.join(ws, rname)
        start_sh = _os.path.join(rpath, "start.sh")
        if _os.path.isfile(start_sh):
            try:
                r = subprocess.run(["bash", start_sh, "stop"],
                                   capture_output=True, text=True, timeout=30, cwd=rpath)
                stopped.append(f"{rname}: OK via start.sh stop")
                continue
            except Exception as e:
                errors.append(f"{rname}: start.sh stop error: {e}")

        # Fallback: mata PIDs directament
        logs_dir = _os.path.join(rpath, ".logs")
        if _os.path.isdir(logs_dir):
            for pid_file in _os.listdir(logs_dir):
                if not pid_file.endswith(".pid"):
                    continue
                pid_path = _os.path.join(logs_dir, pid_file)
                try:
                    with open(pid_path) as f:
                        pid = int(f.read().strip())
                    import signal as _sig
                    try:
                        _os.kill(pid, _sig.SIGTERM)
                        stopped.append(f"{rname}/{pid_file[:-4]}: SIGTERM PID={pid}")
                    except ProcessLookupError:
                        stopped.append(f"{rname}/{pid_file[:-4]}: ja mort")
                    _os.remove(pid_path)
                except Exception as e:
                    errors.append(str(e))

    return {"stopped": stopped, "errors": errors,
            "ok": len(errors) == 0}


# =============================================================================
# ROUTER — dispatch per intent
# =============================================================================

def _router_dispatch(text: str, ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Classifica el text i executa el handler corresponent. Sempre retorna un dict."""
    import datetime as _dt

    if not _ROUTER_AVAILABLE:
        return {"intent": "error", "error": "bartolo_router.py no trobat al path"}

    classified = _router_classify(text, ollama_url)
    intent = classified.get("intent", "conversa")
    source = classified.get("source", "?")

    if intent == "temps_data":
        now = _dt.datetime.now()
        dies = ["dilluns","dimarts","dimecres","dijous","divendres","dissabte","diumenge"]
        mesos = ["gener","febrer","març","abril","maig","juny",
                 "juliol","agost","setembre","octubre","novembre","desembre"]
        s = (f"Ara són les {now.strftime('%H:%M')} del "
             f"{dies[now.weekday()]}, {now.day} de {mesos[now.month-1]} de {now.year}.")
        return {"intent": intent, "source": source, "result": s}

    if intent == "estat_workspace":
        svcs = _workspace_services()
        if not svcs or svcs.get("_error"):
            return {"intent": intent, "source": source,
                    "result": "Cap servei actiu al workspace."}
        lines = []
        for repo, comps in svcs.items():
            running = [s for s, i in comps.items() if i.get("running")]
            stopped_l = [s for s, i in comps.items() if not i.get("running")]
            if running:
                pids = ", ".join(f"{s} (PID {comps[s]['pid']})" for s in running)
                lines.append(f"✅ {repo}: {pids}")
            if stopped_l:
                lines.append(f"⚠️  {repo}: {', '.join(stopped_l)} aturat/s")
        result = "\n".join(lines) if lines else "Cap servei actiu al workspace."
        return {"intent": intent, "source": source, "result": result}

    if intent == "info_sistema":
        cmd = classified.get("cmd") or _router_extract_cmd(text)
        if not cmd:
            cmd = "docker ps && df -h / && ollama list"
        if not _info_safe(cmd):
            return {"intent": intent, "source": source,
                    "error": f"Comanda no segura per a mode lectura: {cmd[:80]}"}
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            out = (r.stdout or r.stderr or "").strip()
            if len(out) > 3000:
                out = out[-3000:]
            return {"intent": intent, "source": source,
                    "cmd": cmd, "result": out or "(sense sortida)"}
        except Exception as e:
            return {"intent": intent, "source": source, "error": str(e)}

    if intent == "start_servei":
        import os as _os
        repo_name = classified.get("repo_name") or ""
        if not repo_name:
            m = re.search(
                r'\b(?:arrenca|arrancar|arrencar|reinicia|reiniciar|engega|restart|start)\s+'
                r'(?:el\s+|la\s+|els?\s+|un\s+)?([\w][\w-]+)\b', text, re.I)
            repo_name = m.group(1) if m else ""
        if not repo_name:
            return {"intent": intent, "source": source,
                    "error": "No he pogut identificar el nom del servei. Di-me quin repo vols arrencar."}
        ws = str(WORKSPACE)
        found = None
        try:
            for d in _os.listdir(ws):
                if d.startswith('.') or d.startswith('_'):
                    continue
                if d.lower() == repo_name.lower() or repo_name.lower() in d.lower():
                    found = d
                    break
        except Exception:
            pass
        if not found:
            return {"intent": intent, "source": source,
                    "error": (f"El servei '{repo_name}' no es troba al workspace. "
                              f"Usa 'munta URL' per clonar-lo primer.")}
        repo_path = _os.path.join(ws, found)
        # Primer atura el servei si estava corrent
        _workspace_stop(found)
        # Després re-executa el pla complet (anàlisi + install + run)
        result = _run_agent([
            "--workspace", ws,
            "--input", repo_path,
            "--execute",
            "--approve-all",
            "--non-interactive",
            "--no-readme",
            "--no-model-refine",
        ], timeout=300)
        return {"intent": intent, "source": source, "repo": found, **result}

    if intent == "atura_repo":
        import os as _os
        repo_name = classified.get("repo_name") or ""
        if not repo_name:
            m = re.search(
                r'\b(?:atura|aturar|para|parar|stop|apaga|apagar|mata|matar|frena|deten|detener)\s+'
                r'(?:el\s+|la\s+|els?\s+|un\s+)?([\w][\w-]+)\b', text, re.I)
            repo_name = m.group(1) if m else ""
        if not repo_name:
            return {"intent": intent, "source": source,
                    "error": "No he pogut identificar el nom del servei. Quin repo vols aturar?"}
        # Cas especial: "atura tots els serveis" o "atura tot"
        if repo_name.lower() in ("tot", "tots", "all", "tot el workspace"):
            result = _workspace_stop("all")
            return {"intent": intent, "source": source,
                    "result": f"Aturats: {len(result.get('stopped', []))} serveis. "
                    f"Errors: {len(result.get('errors', []))}",
                    **result}
        ws = str(WORKSPACE)
        found = None
        try:
            for d in _os.listdir(ws):
                if d.startswith('.') or d.startswith('_'):
                    continue
                if d.lower() == repo_name.lower() or repo_name.lower() in d.lower():
                    found = d
                    break
        except Exception:
            pass
        if not found:
            return {"intent": intent, "source": source,
                    "error": f"El servei '{repo_name}' no es troba al workspace."}
        result = _workspace_stop(found)
        return {"intent": intent, "source": source, "repo": found, **result}

    if intent == "munta_repo":
        repo_url = classified.get("repo_url")
        if not repo_url:
            return {"intent": intent, "source": source,
                    "error": ("No he pogut extreure la URL del repo. "
                              "Proporciona-la: 'munta https://github.com/...' "
                              "Si el repo ja existeix al workspace, prova: 'arrenca [nom]'.")}
        try:
            result = wizard_start(repo_url, rapid=False)
            return {"intent": intent, "source": source, **result}
        except Exception as e:
            return {"intent": intent, "source": source, "error": str(e)}

    if intent == "gestio_docker":
        container_match = re.search(
            r'\b(open-webui|open-webui-pipelines|[\w][\w-]*)\b', text, re.I)
        container = "open-webui"
        if container_match:
            candidate = container_match.group(1).lower()
            if candidate not in {"actualitza", "update", "docker", "container", "el", "un", "the"}:
                container = candidate
        try:
            result = _update_container(container)
            return {"intent": intent, "source": source, **result}
        except Exception as e:
            return {"intent": intent, "source": source, "error": str(e)}

    if intent == "cerca_web":
        return {"intent": intent, "source": source,
                "redirect": "web_search",
                "message": "Per a cerques web usa la tool `web_search` directament."}

    # conversa_general — crida Ollama directament
    import urllib.request as _urllib_req
    payload = json.dumps({
        "model": "qwen2.5:14b",
        "messages": [{"role": "user", "content": text}],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 512}
    }).encode()
    try:
        req = _urllib_req.Request(
            f"{ollama_url}/api/chat", data=payload, method="POST",
            headers={"Content-Type": "application/json"}
        )
        with _urllib_req.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        answer = resp.get("message", {}).get("content", "")
        return {"intent": intent, "source": source, "result": answer}
    except Exception as e:
        return {"intent": intent, "source": source,
                "error": f"Error cridant Ollama: {e}"}


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
            import os as _os_health, gc as _gc_health
            _gc_health.collect()
            mem_bytes = 0
            try:
                with open(f"/proc/{_os_health.getpid()}/status") as _st:
                    for _l in _st:
                        if _l.startswith("VmRSS:"):
                            mem_bytes = int(_l.split()[1]) * 1024
                            break
            except Exception:
                pass
            self._json(200, {"status": "ok", "agent_path": str(AGENT_PATH),
                             "agent_exists": AGENT_PATH.exists(), "workspace": str(WORKSPACE),
                             "public_url": _get_public_url(_PORT),
                             "memory_mb": round(mem_bytes / 1048576, 1),
                             "jobs_count": len(_JOBS)})
        elif parsed.path == "/status":
            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--status"], timeout=30))
        elif parsed.path == "/workspace/services":
            self._json(200, _workspace_services())
        elif parsed.path == "/logs":
            q = parse_qs(parsed.query)
            repo = q.get("repo", [""])[0]
            if not repo:
                self._json(400, {"error": "missing 'repo'"}); return
            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--logs", repo], timeout=30))
        elif parsed.path.startswith("/job/"):
            rest = parsed.path.split("/job/", 1)[1].strip("/")
            if rest.endswith("/stream"):
                jid = rest[:-len("/stream")].strip("/")
                n = int(parse_qs(parsed.query).get("n", ["50"])[0])
                data = _job_stream(jid, n)
                if not data:
                    self._json(404, {"error": f"job {jid} no trobat"}); return
                self._json(200, data)
            else:
                snap = _job_snapshot(rest)
                if not snap:
                    self._json(404, {"error": f"job {rest} no trobat"}); return
                self._json(200, snap)
        elif parsed.path == "/jobs":
            # Neteja jobs zombie (running > 2h)
            import time as _t_now
            with _JOBS_LOCK:
                _now = _t_now.time()
                zombie = [j for j in _JOBS if _JOBS[j]["status"] == "running"
                          and _now - _JOBS[j]["started_at"] > 7200]
                for z in zombie:
                    _JOBS[z]["status"] = "failed"
                    _JOBS[z]["returncode"] = -99
                    _JOBS[z]["finished_at"] = _now
                summary = [{"id": j["id"], "status": j["status"],
                            "started_at": j["started_at"], "finished_at": j["finished_at"],
                            "returncode": j["returncode"]} for j in _JOBS.values()]
            summary.sort(key=lambda x: x["started_at"], reverse=True)
            _gc_old_jobs()
            self._json(200, {"jobs": summary, "count": len(summary)})
        elif parsed.path.startswith("/wizard/"):
            wid = parsed.path.split("/wizard/", 1)[1].strip("/")
            with _WIZARDS_LOCK:
                state = _WIZARDS.get(wid)
            if not state:
                self._json(404, {"error": f"wizard {wid} no trobat"}); return
            self._json(200, {"wizard_id": wid, "step": state["step"],
                             "job_id": state.get("job_id"),
                             "repo_url": state["repo_url"]})
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
        elif parsed.path == "/workspace/stop":
            repo = str(body.get("repo", "all")).strip() or "all"
            self._json(200, _workspace_stop(repo))
        elif parsed.path == "/refresh":
            repo = str(body.get("repo", "")).strip()
            if not repo:
                self._json(400, {"error": "missing 'repo'"}); return
            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--refresh", repo], timeout=60))
        elif parsed.path.startswith("/update_container/"):
            container_name = parsed.path.split("/update_container/", 1)[1].strip("/")
            if not container_name or "/" in container_name:
                self._json(400, {"error": "nom de container invàlid"}); return
            self._json(200, _update_container(container_name))
        elif parsed.path == "/wizard/start":
            repo_url = str(body.get("repo_url", "")).strip()
            if not repo_url:
                self._json(400, {"error": "missing 'repo_url'"}); return
            rapid = bool(body.get("rapid", False))
            self._json(200, wizard_start(repo_url, rapid=rapid))
        elif parsed.path == "/wizard/step":
            wid = str(body.get("wizard_id", "")).strip()
            answer = str(body.get("answer", "")).strip()
            if not wid:
                self._json(400, {"error": "missing 'wizard_id'"}); return
            import re as _re
            if not _re.match(r'^[0-9a-f]{8}$', wid):
                self._json(400, {"error": (
                    f"wizard_id invàlid ('{wid[:20]}{'...' if len(wid)>20 else ''}' té {len(wid)} chars, "
                    f"ha de ser exactament 8 hex). "
                    f"La resposta de l'usuari va al camp 'answer', no a 'wizard_id'. "
                    f"Si el wizard ha caducat, crida inicia_muntatge de nou."
                )}); return
            self._json(200, wizard_step(wid, answer))
        elif parsed.path == "/exec_info":
            cmd = str(body.get("cmd", "")).strip()
            if not cmd:
                self._json(400, {"error": "missing 'cmd'"}); return
            if not _info_safe(cmd):
                self._json(403, {"error": f"comanda no permesa en mode lectura: {cmd[:80]}"}); return
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
                out = (r.stdout or r.stderr or "").strip()
                if len(out) > 4000:
                    out = out[-4000:]
                self._json(200, {"output": out, "returncode": r.returncode})
            except Exception as e:
                self._json(500, {"error": str(e)})
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
        elif parsed.path == "/router/dispatch":
            text = str(body.get("text", "")).strip()
            if not text:
                self._json(400, {"error": "missing 'text'"}); return
            ollama_url = str(body.get("ollama_url", "http://localhost:11434"))
            self._json(200, _router_dispatch(text, ollama_url=ollama_url))
        else:
            self._json(404, {"error": "not found"})


# =============================================================================
# WIZARD de muntatge
# =============================================================================

_WIZARDS: Dict[str, Dict[str, Any]] = {}
_WIZARDS_LOCK = threading.Lock()
_WIZARDS_MAX = 20

SECRETS_FILE = Path.home() / ".universal-agent" / "secrets.json"
_SECRET_VAR_RE = re.compile(
    r'\b([A-Z][A-Z0-9_]{3,}(?:_KEY|_SECRET|_TOKEN|_PASSWORD|_API_KEY|_CLIENT_ID|_CLIENT_SECRET))\b'
)
_RAPID_KEYWORDS = {"ràpid", "rapid", "rapido", "defaults", "default",
                   "munta i prou", "just do it", "skip", "sí", "si", "yes", "y"}


def _wizard_load_secrets() -> Dict[str, str]:
    try:
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8")) if SECRETS_FILE.exists() else {}
    except Exception:
        return {}


def _wizard_save_secret(key: str, value: str) -> None:
    data = _wizard_load_secrets()
    data[key] = value
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        SECRETS_FILE.chmod(0o600)
    except Exception:
        pass


def _wizard_analyze(repo_url: str) -> Dict[str, Any]:
    """Clon superficial, detecta stack i secrets necessaris. Retorna dict amb la info."""
    tmpdir = tempfile.mkdtemp(prefix="bartolo_wizard_")
    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", repo_url, tmpdir],
            capture_output=True, text=True, timeout=45,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        )
        if r.returncode != 0:
            return {"error": f"No s'ha pogut clonar el repo: {r.stderr.strip()[:200]}"}

        root = Path(tmpdir)
        # Llegeix fitxers de config rellevants
        config_texts: List[str] = []
        for fname in (".env.example", ".env.sample", ".env.template", "env.example",
                      "package.json", "requirements.txt", "docker-compose.yml",
                      "docker-compose.yaml", "Dockerfile", ".env"):
            for candidate in [root / fname] + list(root.rglob(fname))[:3]:
                try:
                    config_texts.append(candidate.read_text(errors="ignore")[:3000])
                    break
                except Exception:
                    pass

        combined = "\n".join(config_texts)

        # Detecta secrets necessaris (exclou keys massa genèriques)
        _SKIP = {"SECRET_KEY", "JWT_SECRET", "APP_SECRET", "SESSION_SECRET",
                 "NEXT_PUBLIC_", "REACT_APP_"}
        found_secrets = []
        seen = set()
        for m in _SECRET_VAR_RE.finditer(combined):
            v = m.group(1)
            if v not in seen and not any(v.startswith(s) for s in _SKIP):
                seen.add(v)
                found_secrets.append(v)

        # Detecta necessitat de BD (vars d'entorn tipus MONGO_URL, DATABASE_URL, etc.)
        _DB_ENV_PATTERNS = [
            ("MONGO_URL", "mongodb"), ("MONGODB_URI", "mongodb"), ("MONGODB_URL", "mongodb"),
            ("DATABASE_URL", "postgresql"),  # genèric, es refina després
            ("POSTGRES_", "postgresql"), ("PG", "postgresql"),
            ("MYSQL_", "mysql"), ("MARIADB_", "mysql"),
            ("REDIS_URL", "redis"), ("REDIS_URI", "redis"), ("REDIS_HOST", "redis"),
            ("SUPABASE", "supabase"), ("SUPABASE_URL", "supabase"),
        ]
        db_hints: List[str] = []
        combined_lower = combined.lower()
        for pattern, db_type in _DB_ENV_PATTERNS:
            if pattern.lower() in combined_lower and db_type not in db_hints:
                db_hints.append(db_type)

        # Detecta stack
        stack_parts = []
        if (root / "package.json").exists():
            try:
                pkg = json.loads((root / "package.json").read_text(errors="ignore"))
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "next" in deps:
                    stack_parts.append("Next.js")
                elif "vite" in deps or "@vitejs/plugin-react" in deps:
                    stack_parts.append("Vite/React")
                else:
                    stack_parts.append("Node.js")
            except Exception:
                stack_parts.append("Node.js")
        if (root / "requirements.txt").exists() or list(root.glob("*.py")) or \
           (root / "setup.py").exists() or (root / "setup.cfg").exists() or \
           (root / "pyproject.toml").exists():
            txt = combined.lower()
            if "fastapi" in txt:
                stack_parts.append("FastAPI")
            elif "flask" in txt:
                stack_parts.append("Flask")
            elif "django" in txt:
                stack_parts.append("Django")
            else:
                stack_parts.append("Python")
        if (root / "docker-compose.yml").exists() or (root / "docker-compose.yaml").exists():
            stack_parts.append("Docker Compose")
        if (root / "Dockerfile").exists():
            stack_parts.append("Docker")

        # Nom del repo
        name = Path(repo_url.rstrip("/")).stem.replace(".git", "")

        return {
            "name": name,
            "stack": " + ".join(stack_parts) if stack_parts else "Desconegut",
            "secrets_needed": found_secrets,
            "has_docker_compose": (root / "docker-compose.yml").exists() or
                                   (root / "docker-compose.yaml").exists(),
            "db_hints": db_hints,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Timeout en clonar el repo (>45s). Comprova la URL."}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _is_rapid(answer: str) -> bool:
    a = answer.strip().lower()
    return a in _RAPID_KEYWORDS


def _wizard_next_question(state: Dict[str, Any]) -> Dict[str, Any]:
    """Retorna la pregunta del pas actual."""
    step = state["step"]
    analysis = state.get("analysis", {})
    name = analysis.get("name", "repo")
    default_path = str(WORKSPACE / name)

    if step == "CONFIRM_PATH":
        db_info = ""
        if analysis.get("db_hints"):
            from bartolo.provisioner import CLOUD_TO_LOCAL
            db_parts = []
            for db in analysis["db_hints"]:
                if db in CLOUD_TO_LOCAL:
                    db_parts.append(f"{db} → {CLOUD_TO_LOCAL[db]} local")
                else:
                    db_parts.append(db)
            db_info = f" | BD: {', '.join(db_parts)}"
        return {
            "step": step,
            "question": (
                f"He analitzat el repo.\n"
                f"Stack: {analysis.get('stack', '?')}{db_info} | "
                f"Secrets detectats: {len(state['pending_secrets'])}\n\n"
                f"On el muntes?\n"
                f"[Enter per defecte: {default_path}]"
            ),
            "done": False,
        }

    if step == "COLLECT_SECRETS":
        key = state["pending_secrets"][0]
        already = len(state["answers"].get("secrets", {}))
        total = already + len(state["pending_secrets"])
        return {
            "step": step,
            "question": (
                f"Clau {already + 1}/{total}: falta **{key}**\n"
                f"Introdueix el valor (o Enter per deixar-la buida):"
            ),
            "secret_key": key,
            "done": False,
        }

    if step == "DOCKER_PREF":
        return {
            "step": step,
            "question": "Vols usar Docker si és possible? [Sí / No / Auto (recomanat)]",
            "done": False,
        }

    if step == "SUMMARY":
        secrets = state["answers"].get("secrets", {})
        path = state["answers"].get("mount_path", default_path)
        docker = state["answers"].get("docker_pref", "auto")
        secrets_info = f"{len(secrets)} claus configurades" if secrets else "cap clau nova"
        db_info = ""
        if analysis.get("db_hints"):
            from bartolo.provisioner import DB_DOCKER_CONFIGS, CLOUD_TO_LOCAL
            db_parts = []
            for db in analysis["db_hints"]:
                actual_db = CLOUD_TO_LOCAL.get(db, db)
                cfg = DB_DOCKER_CONFIGS.get(actual_db, {})
                if db in CLOUD_TO_LOCAL:
                    db_parts.append(f"{db} → {CLOUD_TO_LOCAL[db]} (localhost:{cfg.get('port', '?')})")
                elif cfg:
                    db_parts.append(f"{db} (localhost:{cfg.get('port', '?')})")
                else:
                    db_parts.append(db)
            db_info = f"  🗄️ BD: {', '.join(db_parts)}\n"
        return {
            "step": step,
            "question": (
                f"Resum:\n"
                f"  📁 Path: {path}\n"
                f"  🔑 Secrets: {secrets_info}\n"
                f"  🐳 Docker: {docker}\n"
                f"{db_info}\n"
                f"Procedir? [Sí / Cancel·lar]"
            ),
            "done": False,
        }

    return {"step": step, "done": True}


def _wizard_advance(state: Dict[str, Any], answer: str) -> None:
    """Aplica la resposta i avança al pas següent."""
    step = state["step"]
    analysis = state.get("analysis", {})
    name = analysis.get("name", "repo")
    default_path = str(WORKSPACE / name)

    if step == "CONFIRM_PATH":
        path = answer.strip() or default_path
        state["answers"]["mount_path"] = path
        # Pas seguent: secrets pendents o docker
        if state["pending_secrets"]:
            state["step"] = "COLLECT_SECRETS"
        elif analysis.get("has_docker_compose"):
            state["step"] = "DOCKER_PREF"
        else:
            state["step"] = "SUMMARY"

    elif step == "COLLECT_SECRETS":
        key = state["pending_secrets"].pop(0)
        value = answer.strip()
        if value:
            state["answers"].setdefault("secrets", {})[key] = value
            _wizard_save_secret(key, value)
        if state["pending_secrets"]:
            state["step"] = "COLLECT_SECRETS"  # continua amb la seguent clau
        elif analysis.get("has_docker_compose"):
            state["step"] = "DOCKER_PREF"
        else:
            state["step"] = "SUMMARY"

    elif step == "DOCKER_PREF":
        a = answer.strip().lower()
        if a in {"no", "n"}:
            state["answers"]["docker_pref"] = "no"
        elif a in {"sí", "si", "s", "yes", "y"}:
            state["answers"]["docker_pref"] = "yes"
        else:
            state["answers"]["docker_pref"] = "auto"
        state["step"] = "SUMMARY"

    elif step == "SUMMARY":
        a = answer.strip().lower()
        if a in {"cancel·lar", "cancel", "no", "n"}:
            state["step"] = "CANCELLED"
        else:
            state["step"] = "LAUNCHING"


def _wizard_launch(state: Dict[str, Any]) -> str:
    """Construeix els args i llança el job. Retorna job_id."""
    analysis = state.get("analysis", {})
    name = analysis.get("name", "repo")
    default_path = str(WORKSPACE / name)
    mount_path = state["answers"].get("mount_path", default_path)
    docker_pref = state["answers"].get("docker_pref", "auto")

    workspace_parent = str(Path(mount_path).parent)
    args = [
        "--input", state["repo_url"],
        "--workspace", workspace_parent,
        "--execute", "--approve-all", "--non-interactive",
        "--no-model-refine", "--no-readme",
    ]
    if docker_pref == "yes":
        args.append("--dockerize")

    return _start_job(args, timeout=LAUNCH_TIMEOUT)


def _wizard_skip_to_launch(state: Dict[str, Any]) -> None:
    """Salta tots els passos i va directament a LAUNCHING."""
    state["pending_secrets"] = []
    state["answers"].setdefault("mount_path", str(WORKSPACE / state["analysis"].get("name", "repo")))
    state["answers"].setdefault("docker_pref", "auto")
    state["step"] = "LAUNCHING"


def wizard_start(repo_url: str, rapid: bool = False) -> Dict[str, Any]:
    """Crea un nou wizard. Fa l'anàlisi síncronament i retorna la 1a pregunta."""
    analysis = _wizard_analyze(repo_url)
    if "error" in analysis:
        return {"error": analysis["error"]}

    # Secrets que falten al cache
    cached = _wizard_load_secrets()
    pending = [s for s in analysis["secrets_needed"] if s not in cached or not cached[s]]

    import uuid
    wid = uuid.uuid4().hex[:8]
    state: Dict[str, Any] = {
        "id": wid,
        "repo_url": repo_url,
        "step": "CONFIRM_PATH",
        "analysis": analysis,
        "pending_secrets": pending,
        "answers": {},
        "job_id": None,
        "created_at": _time.time(),
    }

    if rapid:
        _wizard_skip_to_launch(state)

    if state["step"] == "LAUNCHING":
        jid = _wizard_launch(state)
        state["job_id"] = jid
        state["step"] = "DONE"

    with _WIZARDS_LOCK:
        # GC: elimina wizards vells si n'hi ha massa
        if len(_WIZARDS) >= _WIZARDS_MAX:
            oldest = sorted(_WIZARDS.items(), key=lambda x: x[1]["created_at"])
            for k, _ in oldest[:5]:
                _WIZARDS.pop(k, None)
        _WIZARDS[wid] = state

    if state["step"] == "DONE":
        return {"wizard_id": wid, "done": True, "job_id": state["job_id"],
                "step": "LAUNCHING"}

    q = _wizard_next_question(state)
    return {"wizard_id": wid, **q}


def wizard_step(wizard_id: str, answer: str) -> Dict[str, Any]:
    """Avança el wizard un pas. Retorna la seguent pregunta o done+job_id."""
    with _WIZARDS_LOCK:
        state = _WIZARDS.get(wizard_id)
    if not state:
        return {"error": f"Wizard '{wizard_id}' no trobat o caducat"}
    if state["step"] in ("DONE", "CANCELLED"):
        return {"wizard_id": wizard_id, "step": state["step"], "done": True,
                "job_id": state.get("job_id")}

    # Detecció de mode ràpid en qualsevol pas
    if _is_rapid(answer) and state["step"] != "SUMMARY":
        _wizard_skip_to_launch(state)
    else:
        _wizard_advance(state, answer)

    if state["step"] == "CANCELLED":
        with _WIZARDS_LOCK:
            _WIZARDS[wizard_id] = state
        return {"wizard_id": wizard_id, "step": "CANCELLED", "done": True,
                "message": "Muntatge cancel·lat."}

    if state["step"] == "LAUNCHING":
        jid = _wizard_launch(state)
        state["job_id"] = jid
        state["step"] = "DONE"
        with _WIZARDS_LOCK:
            _WIZARDS[wizard_id] = state
        return {"wizard_id": wizard_id, "done": True, "job_id": jid, "step": "LAUNCHING"}

    with _WIZARDS_LOCK:
        _WIZARDS[wizard_id] = state

    q = _wizard_next_question(state)
    return {"wizard_id": wizard_id, **q}


# =============================================================================
_INFO_SAFE_PREFIXES = (
    "docker inspect", "docker ps", "docker images", "docker version",
    "docker logs", "docker stats", "docker top", "docker port",
    "docker exec", "docker network", "docker volume",
    "curl http://localhost", "curl http://127.0.0.1", "curl http://host.docker.internal",
    "systemctl status", "systemctl --user status",
    "journalctl --user", "journalctl -u",
    "cat /proc/", "uname", "hostname", "whoami", "id",
    "ps aux", "ps -ef", "ls ", "du ", "df ",
    "python3 --version", "node --version", "npm --version",
    "ollama list", "ollama ps",
    "ss -tlnp", "lsof -i",
)
_INFO_BLOCKED = ("rm ", "kill ", "stop ", "start ", "restart ", "|bash", "|sh", "> /")

def _info_safe(cmd: str) -> bool:
    c = cmd.strip()
    for blocked in _INFO_BLOCKED:
        if blocked in c:
            return False
    for prefix in _INFO_SAFE_PREFIXES:
        if c.startswith(prefix):
            return True
    return False


def _update_container(name: str) -> dict:
    """
    Actualitza un container Docker existent:
    1. docker pull <image>
    2. docker stop <name>
    3. docker rm <name>
    4. docker run amb els mateixos paràmetres (ports, volums, envs, extra-hosts)
    """
    # 1. Inspeccionar el container actual
    insp = subprocess.run(["docker", "inspect", name], capture_output=True, text=True)
    if insp.returncode != 0:
        return {"error": f"Container '{name}' no trobat: {insp.stderr.strip()[:200]}"}
    try:
        data = json.loads(insp.stdout)[0]
    except Exception as e:
        return {"error": f"No s'ha pogut llegir la inspecció: {e}"}

    image = data["Config"]["Image"]
    hc = data.get("HostConfig", {})

    # Reconstruir flags
    port_flags: list[str] = []
    for cport, bindings in (hc.get("PortBindings") or {}).items():
        cp = cport.split("/")[0]
        for b in (bindings or []):
            hp = b.get("HostPort", "")
            if hp:
                port_flags += ["-p", f"{hp}:{cp}"]

    vol_flags: list[str] = []
    for m in (data.get("Mounts") or []):
        if m["Type"] == "volume":
            vol_flags += ["-v", f"{m['Name']}:{m['Destination']}"]
        elif m["Type"] == "bind":
            vol_flags += ["-v", f"{m['Source']}:{m['Destination']}"]

    env_flags: list[str] = []
    skip_pfx = ("PATH=", "HOME=", "HOSTNAME=", "TERM=")
    for e in (data.get("Config", {}).get("Env") or []):
        if not any(e.startswith(p) for p in skip_pfx):
            env_flags += ["-e", e]

    host_flags: list[str] = []
    for h in (hc.get("ExtraHosts") or []):
        host_flags += ["--add-host", h]

    restart = (hc.get("RestartPolicy") or {}).get("Name", "no")
    restart_flag = ["--restart", restart] if restart and restart != "no" else []

    run_cmd = (["docker", "run", "-d"] + port_flags + vol_flags + env_flags +
               host_flags + restart_flag + ["--name", name, image])

    log: list[str] = []

    # 2. Pull
    log.append(f"[pull] docker pull {image}")
    r = subprocess.run(["docker", "pull", image], capture_output=True, text=True, timeout=300)
    log.append(r.stdout.strip()[-500:] if r.stdout else r.stderr.strip()[-200:])
    if r.returncode != 0:
        return {"error": f"docker pull ha fallat", "log": "\n".join(log)}

    # 3. Stop + rm
    subprocess.run(["docker", "stop", name], capture_output=True, timeout=30)
    log.append(f"[stop] docker stop {name} → OK")
    subprocess.run(["docker", "rm", name], capture_output=True, timeout=15)
    log.append(f"[rm]   docker rm {name} → OK")

    # 4. Recrear
    log.append(f"[run]  {' '.join(run_cmd)}")
    r = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return {"error": f"docker run ha fallat: {r.stderr.strip()[:300]}", "log": "\n".join(log)}

    log.append(f"[ok]   Container '{name}' actualitzat i en marxa")
    return {"status": "ok", "container": name, "image": image, "log": "\n".join(log)}


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
    # GC periòdic per evitar fragmentació de memòria
    import gc as _periodic_gc
    def _periodic_gc_thread():
        while True:
            _time.sleep(300)
            _periodic_gc.collect()
    threading.Thread(target=_periodic_gc_thread, daemon=True).start()

    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Aturant bridge...")
        server.shutdown()


if __name__ == "__main__":
    main()
