"""Client LLM — Ollama chat + JSON parsing."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

OLLAMA_CHAT_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = "qwen2.5:14b"


def safe_json_loads(raw: str) -> Any:
    raw = raw.strip()
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return json.loads(raw)


def ollama_chat_json(model: str, messages: List[Dict[str, str]], schema: Optional[Dict[str, Any]] = None, timeout: int = 180) -> Any:
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if schema is not None:
        payload["format"] = schema
    res = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
    res.raise_for_status()
    return safe_json_loads(res.json()["message"]["content"])
