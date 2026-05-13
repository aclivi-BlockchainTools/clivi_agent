"""bartolo/dashboard/secrets_routes.py — CRUD + tipus de clau + toggle per API keys."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
SECRETS_PATH = Path.home() / ".universal-agent" / "secrets.json"

# Known key types with metadata
KEY_TYPES = {
    "ANTHROPIC_API_KEY": {"provider": "Anthropic", "icon": "A", "color": "#d4a574", "test_endpoint": "https://api.anthropic.com/v1/messages"},
    "DEEPSEEK_API_KEY": {"provider": "DeepSeek", "icon": "D", "color": "#4a9eff", "test_endpoint": "https://api.deepseek.com/v1/chat/completions"},
    "OPENAI_API_KEY": {"provider": "OpenAI", "icon": "O", "color": "#74aa9c", "test_endpoint": "https://api.openai.com/v1/models"},
}

# Additional keys that can be configured
OTHER_KEY_NAMES = ["GITHUB_TOKEN", "GITLAB_TOKEN", "BITBUCKET_TOKEN", "DOCKER_HUB_TOKEN"]


def _load() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    try:
        return json.loads(SECRETS_PATH.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SECRETS_PATH.parent / f".secrets_tmp_{os.getpid()}"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, SECRETS_PATH)
    SECRETS_PATH.chmod(0o600)


def _classify_key(key_name: str) -> str:
    """Identify key type from its name."""
    upper = key_name.upper()
    if "ANTHROPIC" in upper or "CLAUDE" in upper:
        return "anthropic"
    if "DEEPSEEK" in upper:
        return "deepseek"
    if "OPENAI" in upper:
        return "openai"
    return "other"


@router.get("/api/secrets")
async def list_secrets():
    data = _load()
    secrets = {}
    for k, v in data.items():
        if k.startswith("_"):
            continue
        ktype = _classify_key(k)
        meta = KEY_TYPES.get(k.upper(), {"provider": ktype.title(), "icon": "?", "color": "#8b949e"})
        secrets[k] = {
            "value": "••••••••",
            "masked": True,
            "type": ktype,
            "provider": meta["provider"],
            "icon": meta["icon"],
            "color": meta["color"],
            "active": not data.get(f"_{k}_disabled", False),
        }
    return {"secrets": secrets, "known_key_types": list(KEY_TYPES.keys()), "other_key_names": OTHER_KEY_NAMES}


@router.get("/api/secrets/{key}")
async def get_secret(key: str):
    data = _load()
    if key not in data:
        return {"value": None, "error": "not found"}
    return {"value": data[key], "type": _classify_key(key)}


@router.put("/api/secrets/{key}")
async def save_secret(key: str, body: dict):
    value = body.get("value", "")
    if not value:
        return {"ok": False, "error": "value required"}
    data = _load()
    data[key] = value
    # Remove disabled flag when saving a new value
    data.pop(f"_{key}_disabled", None)
    _save(data)
    return {"ok": True, "message": f"Clau {key} desada", "type": _classify_key(key)}


@router.delete("/api/secrets/{key}")
async def delete_secret(key: str):
    data = _load()
    if key in data:
        del data[key]
    data.pop(f"_{key}_disabled", None)
    _save(data)
    return {"ok": True, "message": f"Clau {key} eliminada"}


@router.post("/api/secrets/{key}/toggle")
async def toggle_secret(key: str):
    data = _load()
    if key not in data:
        return {"ok": False, "error": f"Clau {key} no configurada"}
    disabled_key = f"_{key}_disabled"
    if data.get(disabled_key, False):
        del data[disabled_key]
        status = "activat"
    else:
        data[disabled_key] = True
        status = "desactivat"
    _save(data)
    return {"ok": True, "key": key, "status": status}


@router.post("/api/secrets/test/{provider}")
async def test_secret(provider: str):
    provider = provider.lower()
    data = _load()

    # Find the matching key
    key_name = None
    api_key = None
    for k in KEY_TYPES:
        if provider in k.lower():
            key_name = k
            api_key = data.get(k)
            break

    if not api_key:
        return {"ok": False, "error": f"No s'ha trobat clau per a {provider}. Configura {key_name or provider.upper() + '_API_KEY'}."}

    test_url = KEY_TYPES.get(key_name, {}).get("test_endpoint", "")
    if not test_url:
        return {"ok": False, "error": f"No test URL for {provider}"}

    import urllib.request
    import urllib.error

    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "anthropic":
            body = json.dumps({"model": "claude-haiku-4-5-20251001", "max_tokens": 10, "messages": [{"role": "user", "content": "ping"}]}).encode()
        elif provider == "deepseek":
            body = json.dumps({"model": "deepseek-chat", "max_tokens": 10, "messages": [{"role": "user", "content": "ping"}]}).encode()
        else:  # openai
            body = None
            req = urllib.request.Request(test_url, headers=headers, method="GET")
            resp = urllib.request.urlopen(req, timeout=15)
            return {"ok": True, "message": f"Connexió a {provider.title()} OK (HTTP {resp.getcode()})"}

        req = urllib.request.Request(test_url, data=body, headers=headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        return {"ok": True, "message": f"Connexió a {provider.title()} OK (HTTP {resp.getcode()})"}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:300]
        return {"ok": False, "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
