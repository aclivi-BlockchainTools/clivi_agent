"""bartolo/dashboard/chat.py — WebSocket xat amb Ollama streaming + router dispatch."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bartolo.llm import OLLAMA_CHAT_URL, DEFAULT_MODEL
from universal_repo_agent_v5 import DEFAULT_WORKSPACE  # type: ignore

router = APIRouter()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
TOOL_CALLING_MODELS = {"qwen2.5:14b", "qwen2.5:7b", "llama3.1:8b", "qwen3:8b"}


async def stream_ollama_chat(ws: WebSocket, messages: list, model: str):
    import aiohttp
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.7, "num_predict": 1024},
    }
    full = ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                buffer = ""
                async for chunk in resp.content.iter_chunked(256):
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="ignore")
                    while True:
                        nl = buffer.find("\n")
                        if nl < 0:
                            break
                        line = buffer[:nl].strip()
                        buffer = buffer[nl + 1:]
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if "message" in obj and "content" in obj.get("message", {}):
                            token = obj["message"]["content"]
                            full += token
                            await ws.send_json({"type": "token", "token": token})
                        if obj.get("done"):
                            await ws.send_json({"type": "done", "full_text": full})
                            return full
    except Exception as e:
        if full:
            await ws.send_json({"type": "done", "full_text": full})
        else:
            await ws.send_json({"type": "error", "error": f"No s'ha pogut connectar a Ollama: {e}"})
    return full


def classify_intent(text: str) -> dict:
    try:
        from bartolo_router import classify
        result = classify(text, ollama_url=OLLAMA_URL)
        return {"intent": result.get("intent", "conversa"),
                "source": result.get("source", "l1"),
                "cmd": result.get("cmd"),
                "repo_url": result.get("repo_url"),
                "repo_name": result.get("repo_name")}
    except Exception:
        return {"intent": "conversa", "source": "fallback"}


@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    model = DEFAULT_MODEL
    history: list = []
    thread_id = None
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "chat")
            message = data.get("message", "").strip()

            if msg_type == "set_thread":
                # Client requests to switch thread — send history
                thread_id = data.get("thread_id", "")
                if thread_id:
                    from bartolo.dashboard.chat_routes import ensure_thread_exists, get_thread_messages
                    ensure_thread_exists(thread_id)
                    msgs = get_thread_messages(thread_id)
                    history = [{"role": m["role"], "content": m["content"]} for m in msgs]
                    await ws.send_json({"type": "history", "messages": msgs})
                continue

            if not message:
                continue

            if msg_type == "chat":
                # Ensure thread exists
                if not thread_id:
                    from bartolo.dashboard.chat_routes import ensure_thread_exists
                    import uuid
                    thread_id = "t-" + uuid.uuid4().hex[:12]
                    t = ensure_thread_exists(thread_id)
                    await ws.send_json({"type": "thread_created", "thread": t})

                # Persist user message
                from bartolo.dashboard.chat_routes import persist_thread_message, append_input_to_history
                persist_thread_message(thread_id, "user", message)
                append_input_to_history(message)

                intent_info = classify_intent(message)
                intent = intent_info["intent"]
                await ws.send_json({"type": "intent", "intent": intent, "source": intent_info["source"]})
                if intent == "info_sistema":
                    cmd = intent_info.get("cmd") or _extract_cmd(message)
                    if cmd:
                        await ws.send_json({"type": "action", "action": cmd})
                        import subprocess
                        try:
                            result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=15, cwd=str(DEFAULT_WORKSPACE))
                            output = result.stdout + result.stderr
                            persist_thread_message(thread_id, "assistant", output[:4000])
                            await ws.send_json({"type": "done", "full_text": output[:4000]})
                        except Exception as e:
                            persist_thread_message(thread_id, "assistant", f"Error: {e}")
                            await ws.send_json({"type": "done", "full_text": f"Error: {e}"})
                    else:
                        await ws.send_json({"type": "done", "full_text": "No s'ha pogut extreure una comanda per a aquesta consulta."})
                elif intent == "estat_workspace":
                    await ws.send_json({"type": "action", "action": "Consultant estat del workspace..."})
                    from bartolo.executor import load_services_registry
                    services = load_services_registry(DEFAULT_WORKSPACE)
                    repos = {k: v for k, v in services.items() if not k.startswith("_") and v}
                    if repos:
                        lines = ["**Repos actius:**"]
                        for repo, svcs in repos.items():
                            for s in svcs:
                                pid = s.get("pid", "?")
                                lines.append(f"- {repo}: {s.get('step_id','')} (PID {pid})")
                    else:
                        lines = ["Cap repo arrencat."]
                    text = "\n".join(lines)
                    persist_thread_message(thread_id, "assistant", text)
                    await ws.send_json({"type": "done", "full_text": text})
                elif intent == "temps_data":
                    from datetime import datetime, timezone as tz, timedelta
                    now_utc = datetime.now(tz.utc)
                    mar31 = datetime(now_utc.year, 3, 31, tzinfo=tz.utc)
                    last_sun_mar = mar31 - timedelta(days=(mar31.weekday() + 1) % 7)
                    oct31 = datetime(now_utc.year, 10, 31, tzinfo=tz.utc)
                    last_sun_oct = oct31 - timedelta(days=(oct31.weekday() + 1) % 7)
                    is_dst = last_sun_mar <= now_utc < last_sun_oct
                    cat_offset = timedelta(hours=2 if is_dst else 1)
                    cat_tz = "CEST (UTC+2)" if is_dst else "CET (UTC+1)"
                    cat_time = now_utc + cat_offset
                    lines = [
                        f"**Hora actual a Catalunya:**",
                        f"- Hora: **{cat_time.strftime('%H:%M:%S')}**",
                        f"- Data: {cat_time.strftime('%d/%m/%Y')}",
                        f"- Dia: {cat_time.strftime('%A')}",
                        f"- Zona: {cat_tz}",
                    ]
                    text = "\n".join(lines)
                    persist_thread_message(thread_id, "assistant", text)
                    await ws.send_json({"type": "done", "full_text": text})
                elif intent == "atura_repo":
                    await ws.send_json({"type": "action", "action": "Aturant serveis..."})
                    from bartolo.executor import stop_services
                    repo_hint = intent_info.get("repo_name") or _extract_repo(message)
                    stop_services(DEFAULT_WORKSPACE, repo_name=repo_hint or "all")
                    text = f"Aturats serveis de: {repo_hint or 'tots'}."
                    persist_thread_message(thread_id, "assistant", text)
                    await ws.send_json({"type": "done", "full_text": text})
                elif intent in ("munta_repo", "start_servei"):
                    repo_url = intent_info.get("repo_url") or _extract_url(message)
                    if repo_url:
                        await ws.send_json({"type": "action", "action": f"Llençant muntatge de {repo_url}..."})
                        import subprocess, threading
                        agent = PROJECT_ROOT / "universal_repo_agent_v5.py"
                        def _launch():
                            try:
                                subprocess.run(
                                    [sys.executable, str(agent), "--input", repo_url, "--execute",
                                     "--approve-all", "--non-interactive", "--no-readme", "--no-model-refine",
                                     "--workspace", str(DEFAULT_WORKSPACE)],
                                    capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT)
                                )
                            except Exception:
                                pass
                        threading.Thread(target=_launch, daemon=True).start()
                        text = f"Muntatge de {repo_url} iniciat. Mira la pestanya Repos per veure el progrés."
                        persist_thread_message(thread_id, "assistant", text)
                        await ws.send_json({"type": "done", "full_text": text})
                    else:
                        await ws.send_json({"type": "done", "full_text": "No s'ha detectat cap URL. Prova: munta https://github.com/usuari/repo.git"})
                else:
                    history.append({"role": "user", "content": message})
                    full_response = await stream_ollama_chat(ws, history, model)
                    if history and history[-1]["role"] == "user":
                        history.append({"role": "assistant", "content": full_response})
                    if len(history) > 20:
                        history = history[-20:]
                    # Persist assistant response
                    if full_response:
                        persist_thread_message(thread_id, "assistant", full_response)
                if intent in ("estat_workspace", "atura_repo", "munta_repo", "start_servei"):
                    await ws.send_json({"type": "action", "done": "Acció completada. Ves a Repos per veure l'estat."})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


def _extract_cmd(text: str) -> str:
    import re
    cmd_map = [
        (r"ollama\s+list", "ollama list"),
        (r"ollama\s+ps", "ollama ps"),
        (r"docker\s+ps", "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"),
        (r"docker\s+logs?\s+(\S+)", None),
        (r"ps\s+aux", "ps aux --sort=-%mem | head -20"),
        (r"df\s+-h", "df -h"),
        (r"free\s+-h", "free -h"),
        (r"lsof\s+-i", "lsof -i -P -n | grep LISTEN"),
    ]
    for pattern, cmd in cmd_map:
        m = re.search(pattern, text)
        if m:
            if cmd:
                return cmd
            return f"docker logs {m.group(1)} --tail 50"
    if re.search(r"(docker|ollama|ps|df|free|lsof)", text.lower()):
        return text.strip()
    return ""


def _extract_url(text: str) -> str:
    import re
    m = re.search(r'(https?://[^\s]+|github\.com/[^\s]+|gitlab\.com/[^\s]+|bitbucket\.org/[^\s]+)', text)
    if m:
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        return url
    return ""


def _extract_repo(text: str) -> str:
    import re
    stop_verbs = r"(?i)(atura|para|apaga|stop|mata|frena)\s+(el\s+|la\s+|l'|els\s+|les\s+)?"
    text_after = re.sub(stop_verbs, "", text).strip()
    words = text_after.split()
    for w in words:
        w = w.strip(".,;:!?\"'()[]{}")
        if len(w) >= 3 and not w.lower() in ("el", "la", "els", "les", "l'", "un", "una", "de", "del", "tot", "tots", "totes", "all"):
            return w
    return ""
