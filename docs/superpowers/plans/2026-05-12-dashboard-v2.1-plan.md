# Dashboard v2.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xat amb múltiples fils de conversa persistents, navegació d'historial d'inputs amb fletxa ↑, i 7 millores addicionals al dashboard (toasts, logs inline, shell WS, timeline, syntax highlight, auto-refresh).

**Architecture:** Backend JSON a `~/.bartolo/chats/` amb 6 endpoints REST + WebSocket ampliat amb `thread_id`. Frontend inline HTML+CSS+JS amb sidebar de fils, input amb històric via localStorage, i components millorats a totes les pestanyes.

**Tech Stack:** Python 3.8+ stdlib, FastAPI+Uvicorn, aiohttp, WebSocket nadiu, vanilla JS (zero deps externes).

---

## File Map

| File | Role |
|------|------|
| `bartolo/dashboard/chat_routes.py` | **NEW** — 6 REST endpoints per threads/history, gestió de fitxers JSON a `~/.bartolo/chats/` |
| `bartolo/dashboard/chat.py` | **MOD** — WebSocket rep `thread_id`, persisteix missatges, envia historial en connectar |
| `bartolo/dashboard/templates.py` | **MOD** — Sidebar fils (HTML+CSS+JS), input ↑↓, toasts, logs inline, auto-refresh, syntax highlight |
| `bartolo/dashboard/__init__.py` | **MOD** — Registrar `chat_routes`, lifespan crea `~/.bartolo/chats/` |
| `bartolo/dashboard/repos_routes.py` | **MOD** — Start/restart endpoint + timeline endpoint |
| `bartolo/dashboard/shell_routes.py` | **MOD** — WebSocket `/ws/shell` per output en temps real |

---

### Task 1: chat_routes.py — Backend de fils i historial

**Files:**
- Create: `bartolo/dashboard/chat_routes.py`

- [ ] **Step 1: Create chat_routes.py with all 6 endpoints**

```python
"""bartolo/dashboard/chat_routes.py — REST API per fils de conversa i historial d'inputs."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

CHATS_DIR = Path.home() / ".bartolo" / "chats"
THREADS_FILE = CHATS_DIR / "threads.json"
HISTORY_FILE = CHATS_DIR / "input_history.json"
MAX_HISTORY = 100


def _ensure_dirs():
    CHATS_DIR.mkdir(parents=True, exist_ok=True)


def _load_threads() -> list:
    _ensure_dirs()
    if not THREADS_FILE.exists():
        return []
    try:
        return json.loads(THREADS_FILE.read_text())
    except Exception:
        return []


def _save_threads(threads: list):
    _ensure_dirs()
    tmp = THREADS_FILE.parent / ".threads_tmp"
    tmp.write_text(json.dumps(threads, indent=2, ensure_ascii=False))
    os.replace(tmp, THREADS_FILE)


def _load_messages(thread_id: str) -> list:
    _ensure_dirs()
    f = CHATS_DIR / f"{thread_id}.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text())
    except Exception:
        return []


def _save_messages(thread_id: str, messages: list):
    _ensure_dirs()
    f = CHATS_DIR / f"{thread_id}.json"
    tmp = CHATS_DIR / f".{thread_id}_tmp"
    tmp.write_text(json.dumps(messages, indent=2, ensure_ascii=False))
    os.replace(tmp, f)


def _load_history() -> list:
    _ensure_dirs()
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return []


def _save_history(history: list):
    _ensure_dirs()
    tmp = HISTORY_FILE.parent / ".history_tmp"
    tmp.write_text(json.dumps(history[-MAX_HISTORY:], indent=2, ensure_ascii=False))
    os.replace(tmp, HISTORY_FILE)


def _append_message(thread_id: str, msg: dict):
    """Append a message to a thread file and update threads.json index."""
    messages = _load_messages(thread_id)
    msg["timestamp"] = int(time.time())
    messages.append(msg)
    _save_messages(thread_id, messages)
    # Update index
    threads = _load_threads()
    for t in threads:
        if t["id"] == thread_id:
            t["updated_at"] = int(time.time())
            t["msg_count"] = len(messages)
            # Auto-title from first user message
            if msg["role"] == "user" and t.get("title") == "Xat nou":
                t["title"] = msg["content"][:50]
            break
    _save_threads(threads)


@router.get("/api/chat/threads")
async def list_threads():
    threads = _load_threads()
    # Sort by updated_at desc
    threads.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
    return {"threads": threads}


@router.post("/api/chat/threads")
async def create_thread(body: dict):
    title = body.get("title", "Xat nou").strip() or "Xat nou"
    thread_id = "t-" + uuid.uuid4().hex[:12]
    now = int(time.time())
    thread = {
        "id": thread_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "msg_count": 0,
    }
    threads = _load_threads()
    threads.append(thread)
    _save_threads(threads)
    _save_messages(thread_id, [])
    return {"ok": True, "thread": thread}


@router.delete("/api/chat/threads/{thread_id}")
async def delete_thread(thread_id: str):
    threads = _load_threads()
    threads = [t for t in threads if t["id"] != thread_id]
    _save_threads(threads)
    f = CHATS_DIR / f"{thread_id}.json"
    if f.exists():
        os.unlink(f)
    return {"ok": True, "deleted": thread_id}


@router.put("/api/chat/threads/{thread_id}")
async def rename_thread(thread_id: str, body: dict):
    title = body.get("title", "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    threads = _load_threads()
    for t in threads:
        if t["id"] == thread_id:
            t["title"] = title
            break
    _save_threads(threads)
    return {"ok": True, "renamed": thread_id, "title": title}


@router.get("/api/chat/threads/{thread_id}")
async def get_thread(thread_id: str):
    messages = _load_messages(thread_id)
    threads = _load_threads()
    thread_info = next((t for t in threads if t["id"] == thread_id), None)
    return {"thread": thread_info, "messages": messages}


@router.get("/api/chat/history")
async def get_history():
    return {"history": _load_history()}


# Public API for chat.py WS to use:
def append_input_to_history(text: str):
    """Record an input to the global input history."""
    history = _load_history()
    # Deduplicate consecutive same inputs
    if not history or history[-1] != text:
        history.append(text)
    _save_history(history)


def persist_thread_message(thread_id: str, role: str, content: str):
    """Save a message to a thread file. Creates thread if it doesn't exist."""
    _append_message(thread_id, {"role": role, "content": content})


def get_thread_messages(thread_id: str) -> list:
    """Get all messages for a thread."""
    return _load_messages(thread_id)


def ensure_thread_exists(thread_id: str) -> dict:
    """Get or create a thread. Returns thread info dict."""
    threads = _load_threads()
    for t in threads:
        if t["id"] == thread_id:
            return t
    # Create new thread
    now = int(time.time())
    thread = {
        "id": thread_id,
        "title": "Xat nou",
        "created_at": now,
        "updated_at": now,
        "msg_count": 0,
    }
    threads.append(thread)
    _save_threads(threads)
    return thread
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/home/usuari/Projects/bartolo/bartolo/dashboard/chat_routes.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add bartolo/dashboard/chat_routes.py
git commit -m "feat: chat_routes.py — REST API per fils de conversa i historial"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 2: chat.py — WebSocket amb thread_id i persistència

**Files:**
- Modify: `bartolo/dashboard/chat.py`

- [ ] **Step 1: Add thread support to the WebSocket handler**

Replace the `websocket_chat` function (lines 83-188) with:

```python
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
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/home/usuari/Projects/bartolo/bartolo/dashboard/chat.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add bartolo/dashboard/chat.py
git commit -m "feat: WS amb thread_id + persistència de missatges"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 3: __init__.py — Registrar chat_routes, lifespan crea chats dir

**Files:**
- Modify: `bartolo/dashboard/__init__.py`

- [ ] **Step 1: Add chat_routes and create chats dir in lifespan**

Edit the lifespan function and add the import:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(DEFAULT_WORKSPACE / LOG_DIRNAME, exist_ok=True)
    from pathlib import Path as _Path
    _Path.home().joinpath(".bartolo", "chats").mkdir(parents=True, exist_ok=True)
    yield
```

Add the chat_routes import and include in `create_app()`:

```python
    from bartolo.dashboard.chat_routes import router as chat_api_router

    app.include_router(chat_router)
    app.include_router(chat_api_router)  # new: REST threads/history
```

- [ ] **Step 2: Verify syntax and imports**

```bash
cd /home/usuari/Projects/bartolo && python3 -c "import sys; sys.path.insert(0, '.'); from bartolo.dashboard import create_app; app = create_app(); print('OK,', len(app.routes), 'routes')"
```

Expected: `OK, <N> routes`

- [ ] **Step 3: Commit**

```bash
git add bartolo/dashboard/__init__.py
git commit -m "feat: registrar chat_routes + lifespan crea ~/.bartolo/chats/"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 4: templates.py — Sidebar de fils + input amb fletxa ↑/↓

**Files:**
- Modify: `bartolo/dashboard/templates.py`

This is the largest task. The template currently has the chat section as a single `<section id="tab-chat">`. We need to refactor it to have a sidebar within the section.

- [ ] **Step 1: Add CSS for thread sidebar**

Add these styles inside the `<style>` block, right before `/* Chat */`:

```css
/* Thread sidebar (inside chat) */
.chat-layout{display:flex;flex:1;overflow:hidden}
.thread-sidebar{width:220px;min-width:220px;background:var(--card);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.thread-sidebar .ts-header{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border)}
.thread-sidebar .ts-header span{font-weight:600;font-size:13px;color:var(--accent)}
.thread-sidebar .ts-header button{background:var(--accent);color:#0d1117;border:0;width:26px;height:26px;border-radius:6px;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.thread-list{flex:1;overflow-y:auto;padding:4px 0}
.thread-item{padding:8px 12px;cursor:pointer;border-left:2px solid transparent;transition:all .15s}
.thread-item:hover{background:#1c2129}
.thread-item.active{background:#1c2945;border-left-color:var(--accent)}
.thread-item .ti-title{font-size:12px;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.thread-item .ti-meta{font-size:10px;color:var(--muted);margin-top:2px;display:flex;justify-content:space-between}
.thread-item .ti-del{display:none;color:var(--bad);font-size:10px;cursor:pointer}
.thread-item:hover .ti-del{display:inline}
.ts-footer{border-top:1px solid var(--border);padding:6px 12px;font-size:10px;color:var(--muted);display:flex;justify-content:space-between}
/* Chat area (right of thread sidebar) */
.chat-area{flex:1;display:flex;flex-direction:column;overflow:hidden}
.chat-area-header{padding:8px 16px;border-bottom:1px solid var(--border);font-size:12px;font-weight:600;display:flex;justify-content:space-between;align-items:center}
.chat-area-header .editable-title{cursor:pointer;border-bottom:1px dashed transparent}
.chat-area-header .editable-title:hover{border-bottom-color:var(--muted)}
/* Toast notifications */
#toast-container{position:fixed;bottom:16px;right:16px;z-index:200;display:flex;flex-direction:column;gap:6px;max-width:340px}
.toast{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:12px;animation:slideIn .25s ease-out;display:flex;align-items:center;gap:8px;box-shadow:0 4px 12px rgba(0,0,0,.4)}
.toast.ok{border-left:3px solid var(--ok)}
.toast.bad{border-left:3px solid var(--bad)}
.toast.info{border-left:3px solid var(--accent)}
.toast .toast-close{margin-left:auto;cursor:pointer;color:var(--muted);font-size:14px}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
/* Logs inline panel */
.logs-panel{display:none;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;padding:8px;margin-top:8px;max-height:250px;overflow-y:auto;font-family:monospace;font-size:11px;white-space:pre-wrap;color:var(--fg)}
.logs-panel.show{display:block}
/* Syntax highlight basics */
.syn-keyword{color:#ff7b72}
.syn-string{color:#a5d6ff}
.syn-comment{color:#8b949e;font-style:italic}
.syn-func{color:#d2a8ff}
/* Timeline */
.timeline{border-left:2px solid var(--border);margin-left:8px;padding-left:16px}
.timeline-item{padding:4px 0;font-size:11px}
.timeline-item .tl-time{color:var(--muted);font-size:10px}
.timeline-item .tl-event{color:var(--fg)}
.timeline-item.ok .tl-event{color:var(--ok)}
.timeline-item.bad .tl-event{color:var(--bad)}
/* Progress bar */
.progress-bar{width:100%;height:6px;background:var(--border);border-radius:3px;margin-top:4px;overflow:hidden}
.progress-fill{height:100%;background:var(--accent);border-radius:3px;transition:width .3s}
/* Health indicator */
.health-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
.health-dot.ok{background:var(--ok)}
.health-dot.warn{background:var(--warn)}
.health-dot.bad{background:var(--bad)}
```

- [ ] **Step 2: Replace the CHAT section HTML**

Replace the entire chat section (currently `<!-- CHAT -->` through the end of the chat section) with the new layout that includes the thread sidebar:

```html
<!-- CHAT -->
<section id="tab-chat" class="active">
  <div class="chat-layout">
    <!-- Thread sidebar -->
    <div class="thread-sidebar" id="thread-sidebar">
      <div class="ts-header">
        <span>Xats</span>
        <button id="new-thread-btn" title="Xat nou (Ctrl+N)">+</button>
      </div>
      <div class="thread-list" id="thread-list">
        <div class="empty" style="padding:12px">Cap xat</div>
      </div>
      <div class="ts-footer">
        <span id="thread-count">0 fils</span>
        <span id="clear-threads-btn" style="cursor:pointer;color:var(--bad);display:none">netejar</span>
      </div>
    </div>
    <!-- Main chat area -->
    <div class="chat-area">
      <div class="chat-area-header">
        <span class="editable-title" id="chat-title" title="Doble click per reanomenar">Xat nou</span>
        <span style="color:var(--muted);font-size:10px">Model: <span id="chat-model-name">qwen2.5:14b</span> &middot; <span id="chat-status">connectant...</span></span>
      </div>
      <div id="chat-messages"></div>
      <div id="chat-input-area">
        <input type="text" id="chat-input" placeholder="Escriu un missatge... (↑ historial, Enter enviar)">
        <button id="chat-send-btn">Enviar</button>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 3: Replace the Chat JS with thread-aware implementation**

Replace the chat JS section (from `// ===== WEBSOCKET CHAT =====` through the end of the chat-related code before `// ===== MODELS =====`) with:

```javascript
// ===== WEBSOCKET CHAT =====
let _currentThreadId = null;
let _threads = [];
let _inputHistory = [];
let _historyIdx = -1;
let _savedInput = '';

function connectWS() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  try {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      document.getElementById('chat-status').innerHTML = '<span class="badge ok">connectat</span>';
      if (_currentThreadId) {
        ws.send(JSON.stringify({type:'set_thread', thread_id:_currentThreadId}));
      }
    };
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'token') appendToken(data.token);
      else if (data.type === 'done') finishMessage();
      else if (data.type === 'intent') addChatMessage('system', 'Intent: ' + data.intent);
      else if (data.type === 'error') addChatMessage('system', 'Error: ' + esc(data.error));
      else if (data.type === 'action') {
        if (data.done) addChatMessage('assistant', data.done);
        else addChatMessage('system', 'Executant: ' + esc(data.action));
      }
      else if (data.type === 'history') {
        document.getElementById('chat-messages').innerHTML = '';
        currentMsgEl = null;
        (data.messages||[]).forEach(m => addChatMessage(m.role, m.content));
      }
      else if (data.type === 'thread_created') {
        loadThreads().then(() => selectThread(data.thread.id, true));
      }
    };
    ws.onclose = () => {
      document.getElementById('chat-status').innerHTML = '<span class="badge warn">reconnectant...</span>';
      if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(connectWS, 3000);
    };
    ws.onerror = () => ws.close();
  } catch(e) { setTimeout(connectWS, 3000); }
}

function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg || !ws || ws.readyState !== WebSocket.OPEN) return;
  addChatMessage('user', msg);
  // Add to input history (deduplicate)
  if (!_inputHistory.length || _inputHistory[_inputHistory.length-1] !== msg) {
    _inputHistory.push(msg);
  }
  _historyIdx = -1;
  _savedInput = '';
  input.value = '';
  currentMsgEl = null;
  ws.send(JSON.stringify({type:'chat', message:msg, thread_id:_currentThreadId}));
  // Refresh thread list after a moment
  setTimeout(loadThreads, 500);
}

function addChatMessage(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  document.getElementById('chat-messages').appendChild(el);
  el.scrollIntoView({behavior:'smooth'});
}

// ===== INPUT HISTORY (arrow up/down) =====
document.getElementById('chat-input').addEventListener('keydown', function(e) {
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (_historyIdx === -1) {
      _savedInput = this.value;
      _historyIdx = _inputHistory.length - 1;
    } else if (_historyIdx > 0) {
      _historyIdx--;
    }
    if (_historyIdx >= 0 && _historyIdx < _inputHistory.length) {
      this.value = _inputHistory[_historyIdx];
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (_historyIdx >= 0 && _historyIdx < _inputHistory.length - 1) {
      _historyIdx++;
      this.value = _inputHistory[_historyIdx];
    } else {
      _historyIdx = -1;
      this.value = _savedInput;
    }
  } else if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});

// ===== THREAD MANAGEMENT =====
async function loadThreads() {
  try {
    const r = await fetch('/api/chat/threads');
    const data = await r.json();
    _threads = data.threads || [];
    renderThreadList();
  } catch(e) {}
}

function renderThreadList() {
  const el = document.getElementById('thread-list');
  if (!_threads.length) {
    el.innerHTML = '<div class="empty" style="padding:12px">Cap xat</div>';
    document.getElementById('thread-count').textContent = '0 fils';
    document.getElementById('clear-threads-btn').style.display = 'none';
    return;
  }
  document.getElementById('thread-count').textContent = _threads.length + ' fils';
  document.getElementById('clear-threads-btn').style.display = 'inline';
  let h = '';
  for (const t of _threads) {
    const active = t.id === _currentThreadId ? ' active' : '';
    const timeAgo = relativeTime(t.updated_at);
    h += '<div class="thread-item'+active+'" data-thread-id="'+escUrl(t.id)+'">';
    h += '<div class="ti-title">'+esc(t.title)+'</div>';
    h += '<div class="ti-meta"><span>'+timeAgo+' &middot; '+t.msg_count+' msgs</span>';
    h += '<span class="ti-del" data-delete-thread="'+escUrl(t.id)+'">&#x1f5d1;</span></div>';
    h += '</div>';
  }
  el.innerHTML = h;
}

function relativeTime(ts) {
  if (!ts) return '';
  const diff = Math.floor(Date.now()/1000) - ts;
  if (diff < 60) return 'fa un moment';
  if (diff < 3600) return Math.floor(diff/60) + ' min';
  if (diff < 86400) return Math.floor(diff/3600) + ' h';
  if (diff < 604800) return Math.floor(diff/86400) + ' dies';
  return new Date(ts*1000).toLocaleDateString('ca');
}

async function selectThread(id, silent) {
  _currentThreadId = id;
  localStorage.setItem('bartolo-thread', id);
  document.getElementById('chat-messages').innerHTML = '';
  currentMsgEl = null;
  // Load messages from server
  try {
    const r = await fetch('/api/chat/threads/' + encodeURIComponent(id));
    const data = await r.json();
    if (data.messages) {
      data.messages.forEach(m => addChatMessage(m.role, m.content));
    }
    if (data.thread) {
      document.getElementById('chat-title').textContent = data.thread.title;
    }
  } catch(e) {}
  renderThreadList();
  if (!silent && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type:'set_thread', thread_id:id}));
  }
  document.getElementById('chat-input').focus();
}

async function createThread() {
  try {
    const r = await fetch('/api/chat/threads', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
    const data = await r.json();
    if (data.ok && data.thread) {
      await loadThreads();
      selectThread(data.thread.id, false);
    }
  } catch(e) {}
}

async function deleteThread(id) {
  if (!confirm('Esborrar aquest fil de conversa?')) return;
  await fetch('/api/chat/threads/' + encodeURIComponent(id), {method:'DELETE'});
  if (_currentThreadId === id) {
    _currentThreadId = null;
    document.getElementById('chat-messages').innerHTML = '';
    document.getElementById('chat-title').textContent = 'Xat nou';
    localStorage.removeItem('bartolo-thread');
  }
  await loadThreads();
}

async function renameThread(id) {
  const title = prompt('Nou nom del fil:', '');
  if (!title) return;
  await fetch('/api/chat/threads/' + encodeURIComponent(id), {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:title})});
  await loadThreads();
  if (_currentThreadId === id) {
    document.getElementById('chat-title').textContent = title;
  }
}

// Thread header double-click to rename
document.getElementById('chat-title').addEventListener('dblclick', function() {
  if (_currentThreadId) renameThread(_currentThreadId);
});

// New thread button
document.getElementById('new-thread-btn').addEventListener('click', createThread);

// Clear all threads
document.getElementById('clear-threads-btn').addEventListener('click', async function() {
  if (!confirm('Esborrar TOTS els fils de conversa?')) return;
  for (const t of _threads) {
    await fetch('/api/chat/threads/' + encodeURIComponent(t.id), {method:'DELETE'});
  }
  _threads = [];
  _currentThreadId = null;
  document.getElementById('chat-messages').innerHTML = '';
  document.getElementById('chat-title').textContent = 'Xat nou';
  localStorage.removeItem('bartolo-thread');
  renderThreadList();
});

// Load input history from server
async function loadInputHistory() {
  try {
    const r = await fetch('/api/chat/history');
    const data = await r.json();
    if (data.history) _inputHistory = data.history;
  } catch(e) {}
}
```

- [ ] **Step 4: Update the send button event listener**

The old send button listener is at line 289. Replace it with the inline `keydown` handler from Step 3 (which already handles Enter). Keep the button click:

```javascript
document.getElementById('chat-send-btn').addEventListener('click', sendChat);
```

Also remove the duplicate `addEventListener('keydown', ...)` that was at lines 289-290 (the old Enter handler).

- [ ] **Step 5: Update delegated click handlers for thread actions**

Add these handlers to the global click handler (before the existing models handler):

```javascript
  // Thread click
  const threadEl = e.target.closest('[data-thread-id]');
  if (threadEl && !e.target.closest('[data-delete-thread]')) {
    selectThread(decodeURIComponent(threadEl.getAttribute('data-thread-id')), false);
    return;
  }
  // Thread delete
  const delThreadEl = e.target.closest('[data-delete-thread]');
  if (delThreadEl) {
    deleteThread(decodeURIComponent(delThreadEl.getAttribute('data-delete-thread')));
    return;
  }
```

- [ ] **Step 6: Update INIT section to load threads and history**

Add to the init section (after connectWS and switchTab):

```javascript
// Load threads and history
loadThreads();
loadInputHistory();
// Restore last thread
const lastThread = localStorage.getItem('bartolo-thread');
if (lastThread) {
  _currentThreadId = lastThread;
  setTimeout(function() {
    selectThread(lastThread, true);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type:'set_thread', thread_id:lastThread}));
    }
  }, 300);
}
```

- [ ] **Step 7: Add keyboard shortcuts (Ctrl+N, Ctrl+W, Ctrl+arrows)**

Add to the init section:

```javascript
// Global keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.key === 'n') {
    e.preventDefault();
    createThread();
  }
  if (e.ctrlKey && e.key === 'w') {
    e.preventDefault();
    if (_currentThreadId) deleteThread(_currentThreadId);
  }
});
```

- [ ] **Step 8: Verify JS syntax**

```bash
cd /home/usuari/Projects/bartolo && python3 -c "
import sys, re, subprocess, tempfile, os
sys.path.insert(0, '.')
from bartolo.dashboard.templates import render_index
html = render_index()
scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
if scripts:
    with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
        f.write(scripts[0])
        tmp = f.name
    r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
    os.unlink(tmp)
    if r.returncode == 0:
        print('JS OK, HTML:', len(html), 'bytes')
    else:
        print('JS ERROR:', r.stderr)
"
```

Expected: `JS OK, HTML: <N> bytes`

- [ ] **Step 9: Restart dashboard and test**

```bash
systemctl --user restart agent-dashboard
sleep 2
# Test endpoints
curl -s http://localhost:9999/api/chat/threads | python3 -m json.tool
curl -s -X POST http://localhost:9999/api/chat/threads -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
curl -s http://localhost:9999/api/chat/history | python3 -m json.tool
```

- [ ] **Step 10: Commit**

```bash
git add bartolo/dashboard/templates.py
git commit -m "feat: sidebar fils de xat + input historial amb fletxa amunt"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 5: Toast notifications + auto-refresh

**Files:**
- Modify: `bartolo/dashboard/templates.py`

- [ ] **Step 1: Add toast container HTML**

After the modal div (before `</body>`):

```html
<div id="toast-container"></div>
```

- [ ] **Step 2: Add toast JS functions**

Add this JS section (before `// ===== UTILS =====`):

```javascript
// ===== TOAST NOTIFICATIONS =====
let _toastQueue = [];
function showToast(msg, type) {
  type = type || 'info';
  _toastQueue.push({msg:msg, type:type});
  if (_toastQueue.length > 3) _toastQueue.shift();
  renderToasts();
  setTimeout(function() {
    _toastQueue = _toastQueue.filter(function(t) { return t.msg !== msg; });
    renderToasts();
  }, 5000);
}
function renderToasts() {
  var container = document.getElementById('toast-container');
  var h = '';
  for (var i = 0; i < _toastQueue.length; i++) {
    var t = _toastQueue[i];
    h += '<div class="toast '+t.type+'"><span>'+esc(t.msg)+'</span><span class="toast-close" onclick="this.parentElement.remove()">x</span></div>';
  }
  container.innerHTML = h;
}
```

- [ ] **Step 3: Add auto-refresh logic**

Replace the current `_reposInterval` logic in `switchTab()` and `loadTabData()` with the new adaptive polling system:

In the navigation section, replace `let _reposInterval = null;` and the polling logic with:

```javascript
let _intervals = {};
let _lastChanges = {};

function startPolling(tab, fn, fastMs, slowMs) {
  stopPolling(tab);
  _lastChanges[tab] = Date.now();
  _intervals[tab] = setInterval(function() {
    var elapsed = Date.now() - (_lastChanges[tab] || 0);
    var interval = elapsed < 30000 ? (fastMs || 2000) : (slowMs || 15000);
    // Only poll if tab is active
    var sec = document.getElementById('tab-' + tab);
    if (!sec || !sec.classList.contains('active')) return;
    fn();
  }, fastMs || 2000);
}

function stopPolling(tab) {
  if (_intervals[tab]) { clearInterval(_intervals[tab]); _intervals[tab] = null; }
}

function bumpPolling(tab) {
  _lastChanges[tab] = Date.now();
}
```

Update `loadTabData` to use new polling:

```javascript
function loadTabData(t) {
  if (t === 'models') loadModels();
  if (t === 'repos') { loadStatus(); startPolling('repos', loadStatus, 2000, 15000); }
  if (t === 'databases') { loadDatabases(); startPolling('databases', loadDatabases, 5000, 30000); }
  if (t === 'secrets') loadSecrets();
  if (t === 'tools') loadTools();
}
```

Update `switchTab` to stop polling for non-active tabs:

```javascript
  // Stop polling for tabs we're leaving
  if (t !== 'repos') stopPolling('repos');
  if (t !== 'databases') stopPolling('databases');
```

- [ ] **Step 4: Verify JS syntax and commit**

```bash
cd /home/usuari/Projects/bartolo && python3 -c "
import sys, re, subprocess, tempfile, os
sys.path.insert(0, '.')
from bartolo.dashboard.templates import render_index
html = render_index()
scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
if scripts:
    with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
        f.write(scripts[0]); tmp = f.name
    r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
    os.unlink(tmp)
    print('JS OK' if r.returncode == 0 else 'JS ERROR: ' + r.stderr)
"
```

```bash
git add bartolo/dashboard/templates.py
git commit -m "feat: toast notifications + auto-refresh intel·ligent"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 6: repos_routes.py — Start/Restart + timeline

**Files:**
- Modify: `bartolo/dashboard/repos_routes.py`

- [ ] **Step 1: Add start/restart endpoint**

Add after the `/api/stop` route:

```python
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
```

- [ ] **Step 2: Add timeline endpoint**

```python
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
```

- [ ] **Step 3: Verify syntax and commit**

```bash
python3 -c "import ast; ast.parse(open('/home/usuari/Projects/bartolo/bartolo/dashboard/repos_routes.py').read()); print('Syntax OK')"
git add bartolo/dashboard/repos_routes.py
git commit -m "feat: restart endpoint + timeline per repo a repos_routes.py"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 7: shell_routes.py — WebSocket shell

**Files:**
- Modify: `bartolo/dashboard/shell_routes.py`

- [ ] **Step 1: Add WebSocket shell endpoint**

Add after the imports:

```python
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
```

Add the WebSocket endpoint at the end of the file:

```python
@router.websocket("/ws/shell")
async def websocket_shell(ws: WebSocket):
    await ws.accept()
    # Shell history (in-memory, per connection)
    shell_history = []
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd", "").strip()
            if not cmd:
                continue
            # Add to history
            if not shell_history or shell_history[-1] != cmd:
                shell_history.append(cmd)
                if len(shell_history) > 100:
                    shell_history = shell_history[-100:]
            # Send ack
            await ws.send_json({"type": "start", "cmd": cmd})
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(DEFAULT_WORKSPACE),
                )
                # Read line by line with timeout
                try:
                    while True:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                        if not line:
                            break
                        await ws.send_json({"type": "output", "line": line.decode("utf-8", errors="replace").rstrip("\n")})
                except asyncio.TimeoutError:
                    proc.kill()
                    await ws.send_json({"type": "output", "line": "[timeout 30s]"})
                await proc.wait()
                await ws.send_json({"type": "done", "returncode": proc.returncode, "history": shell_history})
            except Exception as e:
                await ws.send_json({"type": "error", "error": str(e)})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
```

- [ ] **Step 2: Verify syntax and commit**

```bash
python3 -c "import ast; ast.parse(open('/home/usuari/Projects/bartolo/bartolo/dashboard/shell_routes.py').read()); print('Syntax OK')"
git add bartolo/dashboard/shell_routes.py
git commit -m "feat: WebSocket /ws/shell per output en temps real"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 8: templates.py — Frontend millores (logs inline, timeline, shell WS, syntax highlight)

**Files:**
- Modify: `bartolo/dashboard/templates.py`

- [ ] **Step 1: Add inline logs panel to Repos tab**

Replace `window.open('/api/logs?...')` in the delegated click handler with inline log loading:

```javascript
  // Repos - view logs inline
  const logEl = e.target.closest('[data-view-logs]');
  if (logEl) {
    const parts = logEl.getAttribute('data-view-logs').split('/');
    const repo = decodeURIComponent(parts[0]);
    const step = decodeURIComponent(parts.slice(1).join('/'));
    // Find or create logs panel
    let panelId = 'logs-' + repo.replace(/[^a-zA-Z0-9]/g, '_');
    let panel = document.getElementById(panelId);
    let svcDiv = logEl.closest('.svc');
    if (!panel && svcDiv) {
      panel = document.createElement('div');
      panel.id = panelId;
      panel.className = 'logs-panel show';
      svcDiv.appendChild(panel);
    }
    if (panel) {
      panel.textContent = 'Carregant...';
      fetch('/api/logs?repo=' + encodeURIComponent(repo) + '&step=' + encodeURIComponent(step))
        .then(r => r.text())
        .then(text => { panel.textContent = text; })
        .catch(() => { panel.textContent = 'Error'; });
    }
    return;
  }
```

- [ ] **Step 2: Add restart button to Repos**

Update the repos render to include a restart button:

```javascript
  sh += '<div class="svc '+(alive?'run':'stop')+'"><div class="svc-info"><strong>'+(alive?'&#x1f7e2; RUNNING':'&#x1f534; STOPPED')+' &middot; PID '+(s.pid||'?')+'</strong> &middot; step: <code>'+esc(s.step_id||'')+'</code><code>'+esc(s.command||'')+'</code></div>'+
    '<div class="actions"><button class="small" data-view-logs="'+escUrl(repo)+'/'+escUrl(s.step_id||'')+'">Logs</button>'+
    '<button class="small primary" data-restart-repo="'+escUrl(repo)+'">Restart</button>'+
    '<button class="small danger" data-stop-repo="'+escUrl(repo)+'">Stop</button></div></div>';
```

Add delegated handler for restart:

```javascript
  const restartEl = e.target.closest('[data-restart-repo]');
  if (restartEl) {
    const repo = decodeURIComponent(restartEl.getAttribute('data-restart-repo'));
    restartRepo(repo);
    return;
  }
```

Add restart function:

```javascript
async function restartRepo(name) {
  showToast('Reiniciant ' + name + '...', 'info');
  await fetch('/api/restart', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'repo='+encodeURIComponent(name)});
  showToast(name + ' reiniciat. Verifica la pestanya Repos.', 'ok');
  bumpPolling('repos');
  setTimeout(loadStatus, 5000);
}
```

- [ ] **Step 3: Add timeline loading to Repos**

Add timeline section to the repos render for each repo card:

```javascript
  h += '<div class="card"><h2>'+esc(repo)+'</h2>'+sh+
    '<div class="timeline" id="tl-'+escUrl(repo)+'" style="display:none;margin-top:8px"></div>'+
    '<div style="margin-top:4px"><button class="small" data-load-timeline="'+escUrl(repo)+'">Timeline</button></div>'+
    '</div>';
```

Add delegated handler and loading function:

```javascript
  const tlEl = e.target.closest('[data-load-timeline]');
  if (tlEl) {
    loadTimeline(decodeURIComponent(tlEl.getAttribute('data-load-timeline')));
    return;
  }
```

```javascript
async function loadTimeline(repo) {
  const el = document.getElementById('tl-' + repo.replace(/[^a-zA-Z0-9]/g, '_'));
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML = '<span class="spinner"></span> Carregant...';
  try {
    const r = await fetch('/api/timeline/' + encodeURIComponent(repo));
    const data = await r.json();
    if (!data.events || !data.events.length) {
      el.innerHTML = '<div class="empty">Cap event</div>';
      return;
    }
    let h = '';
    for (const e of data.events) {
      const cls = e.level === 'error' ? 'bad' : (e.level === 'ok' ? 'ok' : '');
      h += '<div class="timeline-item '+cls+'"><span class="tl-time">'+esc(e.time||'')+'</span> <span class="tl-event">'+esc(e.event)+'</span></div>';
    }
    el.innerHTML = h;
  } catch(e) { el.innerHTML = '<div class="empty">Error</div>'; }
}
```

- [ ] **Step 4: Update Shell tab for WebSocket**

Replace the shell tab HTML with real-time WS shell:

```html
<!-- SHELL -->
<section id="tab-shell">
  <h1>&#x2328; Shell Exec</h1>
  <div class="sub">WebSocket en temps real</div>
  <div id="shell-flash"></div>
  <div class="card">
    <div class="row">
      <input type="text" id="shell-cmd" placeholder="docker ps, ollama list, pwd..." style="flex:1">
      <button id="shell-exec-btn" class="primary">Executar (Enter)</button>
    </div>
    <pre class="logs output" id="shell-output" style="min-height:200px;max-height:400px"></pre>
    <div id="shell-history-area" style="margin-top:8px;display:none">
      <div style="color:var(--muted);font-size:10px;margin-bottom:4px">Historial:</div>
      <div id="shell-history-list" style="font-size:11px"></div>
    </div>
  </div>
</section>
```

Add JS for real-time shell via WebSocket:

```javascript
// ===== SHELL (WebSocket) =====
let shellWs = null;
function shellExec() {
  const cmd = document.getElementById('shell-cmd').value.trim();
  if (!cmd) return;
  const out = document.getElementById('shell-output');
  out.textContent = '$ ' + cmd + '\n';
  if (!shellWs || shellWs.readyState !== WebSocket.OPEN) {
    shellWs = new WebSocket('ws://' + location.host + '/ws/shell');
    shellWs.onmessage = function(e) {
      const d = JSON.parse(e.data);
      if (d.type === 'output') out.textContent += d.line + '\n';
      else if (d.type === 'done') {
        out.textContent += '\n[returncode: ' + d.returncode + ']';
        if (d.history) renderShellHistory(d.history);
      }
      else if (d.type === 'error') out.textContent += 'ERROR: ' + d.error + '\n';
      out.scrollTop = out.scrollHeight;
    };
    shellWs.onclose = function() { shellWs = null; };
    shellWs.onopen = function() { shellWs.send(JSON.stringify({cmd:cmd})); };
  } else {
    shellWs.send(JSON.stringify({cmd:cmd}));
  }
  document.getElementById('shell-cmd').value = '';
}

function renderShellHistory(history) {
  var area = document.getElementById('shell-history-area');
  area.style.display = 'block';
  var list = document.getElementById('shell-history-list');
  list.innerHTML = history.slice(-10).map(function(c, i) {
    return '<div style="cursor:pointer;color:var(--accent);padding:2px 0" data-shell-history="'+i+'">'+esc(c)+'</div>';
  }).join('');
}

document.getElementById('shell-exec-btn').addEventListener('click', shellExec);
document.getElementById('shell-cmd').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); shellExec(); }
});
```

- [ ] **Step 5: Syntax highlight for tool source viewer**

Add a simple syntax highlighter for Python code in the tool modal:

```javascript
function highlightPython(code) {
  return code
    .replace(/("""[\s\S]*?"""|'''[\s\S]*?''')/g, '<span class="syn-string">$1</span>')
    .replace(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g, '<span class="syn-string">$1</span>')
    .replace(/(#.*$)/gm, '<span class="syn-comment">$1</span>')
    .replace(/\b(def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|yield|async|await|raise|pass|break|continue|and|or|not|in|is|None|True|False)\b/g, '<span class="syn-keyword">$1</span>')
    .replace(/\b([a-zA-Z_]\w*)\s*\(/g, '<span class="syn-func">$1</span>(');
}
```

Update `viewToolSource` to apply highlighting:

```javascript
  const source = data.source || '(no disponible)';
  const highlighted = highlightPython(source);
  document.getElementById('tool-modal-source').innerHTML = highlighted;
```

Note: Since the modal source is now a textarea (for editing), syntax highlighting won't work in it. Keep the textarea for editing but add a "Preview" toggle:

Add button next to Desar in the modal: `<button class="small" onclick="toggleSyntaxPreview()">Preview</button>`

```javascript
function toggleSyntaxPreview() {
  var el = document.getElementById('tool-modal-source');
  var preview = document.getElementById('tool-preview');
  if (!preview) {
    preview = document.createElement('pre');
    preview.id = 'tool-preview';
    preview.className = 'logs';
    preview.style.cssText = 'max-height:65vh;overflow:auto;display:none';
    el.parentNode.insertBefore(preview, el.nextSibling);
  }
  if (el.style.display === 'none') {
    el.style.display = '';
    preview.style.display = 'none';
  } else {
    el.style.display = 'none';
    preview.style.display = 'block';
    preview.innerHTML = highlightPython(el.value);
  }
}
```

- [ ] **Step 6: Verify syntax and final commit**

```bash
cd /home/usuari/Projects/bartolo && python3 -c "
import sys, re, subprocess, tempfile, os
sys.path.insert(0, '.')
from bartolo.dashboard.templates import render_index
html = render_index()
scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
if scripts:
    with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
        f.write(scripts[0]); tmp = f.name
    r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
    os.unlink(tmp)
    print('JS OK' if r.returncode == 0 else 'JS ERROR: ' + r.stderr)
"
```

```bash
git add bartolo/dashboard/templates.py
git commit -m "feat: logs inline, timeline, shell WS, syntax highlight, restart"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

### Task 9: Verification final

- [ ] **Step 1: Restart and test all endpoints**

```bash
systemctl --user restart agent-dashboard
sleep 2
```

```bash
# Test all new endpoints
echo "=== threads ===" && curl -s http://localhost:9999/api/chat/threads | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('threads',[])), 'threads')"
echo "=== create thread ===" && curl -s -X POST http://localhost:9999/api/chat/threads -H 'Content-Type: application/json' -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok'), d.get('thread',{}).get('id','?'))"
echo "=== history ===" && curl -s http://localhost:9999/api/chat/history | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('history',[])), 'inputs')"
echo "=== status ===" && curl -s http://localhost:9999/api/status | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d), 'keys')"
echo "=== tools ===" && curl -s http://localhost:9999/api/tools | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0), 'tools')"
echo "=== models ===" && curl -s http://localhost:9999/api/models | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0), 'models')"
echo "=== secrets ===" && curl -s http://localhost:9999/api/secrets | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('secrets',{})), 'secrets')"
```

- [ ] **Step 2: Run bench.sh quick**

```bash
cd /home/usuari/Projects/bartolo && ./bench.sh quick
```

Expected: 6/6 (100%)

- [ ] **Step 3: Run bartolo-doctor.sh dashboard section**

```bash
cd /home/usuari/Projects/bartolo && ./bartolo-doctor.sh
```

Expected: dashboard section OK

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: verificació final dashboard v2.1 — tots els endpoints OK"

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```
