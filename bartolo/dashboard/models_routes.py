"""bartolo/dashboard/models_routes.py — Gestió de models Ollama."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

import requests
from fastapi import APIRouter

router = APIRouter()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
TOOL_CALLING_MODELS = {"qwen2.5:14b", "qwen2.5:7b", "llama3.1:8b", "qwen3:8b"}
INCOMPATIBLE_MODELS = {"qwen2.5-coder:14b", "mistral-nemo:12b"}


def _tool_calling_status(name: str) -> Optional[bool]:
    base = name.split(":")[0]
    if name in TOOL_CALLING_MODELS:
        return True
    if name in INCOMPATIBLE_MODELS:
        return False
    for m in TOOL_CALLING_MODELS:
        if m.split(":")[0] == base:
            return True
    for m in INCOMPATIBLE_MODELS:
        if m.split(":")[0] == base:
            return False
    return None


@router.get("/api/models")
async def list_models():
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        data = resp.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            detail = m.get("details", {})
            size = detail.get("parameter_size", "")
            if not size and detail.get("format"):
                size = detail["format"].upper()
            models.append({
                "name": name,
                "size": size,
                "modified": m.get("modified_at", ""),
                "tool_calling": _tool_calling_status(name),
            })
        return {"models": models, "count": len(models)}
    except Exception as e:
        return {"models": [], "count": 0, "error": str(e)}


@router.post("/api/models/pull")
async def pull_model(body: dict):
    model = body.get("model", "").strip()
    if not model:
        return {"ok": False, "message": "model name required"}
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            return {"ok": True, "message": f"Model {model} descarregat correctament"}
        return {"ok": False, "message": result.stderr.strip() or result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Timeout (10 min)"}
    except FileNotFoundError:
        return {"ok": False, "message": "ollama CLI no trobat"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
