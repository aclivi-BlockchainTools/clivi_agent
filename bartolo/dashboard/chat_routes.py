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


@router.get("/api/repair-history")
async def get_repair_history(limit: int = 50):
    """Retorna l'historial de reparacions (JSONL) ordenat per data."""
    history_path = Path.home() / ".universal-agent" / "repair_history.jsonl"
    if not history_path.exists():
        return {"entries": []}
    entries = []
    try:
        with history_path.open() as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    except Exception:
        return {"entries": []}
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return {"entries": entries[:limit]}


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
