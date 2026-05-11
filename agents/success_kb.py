"""
agents/success_kb.py — Registre de plans que han funcionat per stack.
Cada cop que un repo es munta OK, guarda la recepta per reutilitzar-la.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_KB_DIR = Path.home() / ".universal-agent"
_SUCCESS_KB_FILE = "success_kb.json"


def _kb_path() -> Path:
    _DEFAULT_KB_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_KB_DIR / _SUCCESS_KB_FILE


def _stack_key(service_type: str, manifests: List[str], repo_name: str = "") -> str:
    """Clau única per stack + repo. Inclou repo_name per diferenciar plans de repos diferents."""
    manifests_sorted = sorted(manifests.split(", ") if isinstance(manifests, str) else manifests)
    raw = f"{repo_name}|{service_type}|{'|'.join(manifests_sorted)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def _stack_label(service_type: str, manifests: List[str], repo_name: str = "") -> str:
    manifests_sorted = sorted(manifests.split(", ") if isinstance(manifests, str) else manifests)
    m_str = "+".join(m.replace("package.json", "npm").replace("requirements.txt", "pip")
                      .replace("setup.py", "pip").replace("pyproject.toml", "pip")
                      .replace("setup.cfg", "pip").replace("go.mod", "go")
                      .replace("Cargo.toml", "rust").replace("Gemfile", "ruby")
                      for m in manifests_sorted)
    label = f"{service_type}/{m_str}" if m_str else service_type
    return f"{repo_name}::{label}" if repo_name else label


def load_success_kb() -> Dict[str, Any]:
    """Carrega la KB d'èxits."""
    path = _kb_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_success_kb(data: Dict[str, Any]) -> None:
    """Guarda la KB d'èxits."""
    _kb_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def lookup_plan(service_type: str, manifests: List[str],
                repo_name: str = "") -> Optional[List[Dict[str, Any]]]:
    """Busca un pla validat per a un stack + repo concret. Retorna None si no n'hi ha."""
    kb = load_success_kb()
    key = _stack_key(service_type, manifests, repo_name)
    entry = kb.get(key)
    if not entry:
        return None
    return entry.get("plan")


def record_success(service_type: str, manifests: List[str],
                   steps: List[Dict[str, Any]], repo_name: str = "") -> None:
    """Registra un pla que ha funcionat per a un repo concret."""
    kb = load_success_kb()
    key = _stack_key(service_type, manifests, repo_name)
    label = _stack_label(service_type, manifests, repo_name)
    existing = kb.get(key, {})
    kb[key] = {
        "label": label,
        "service_type": service_type,
        "manifests": sorted(manifests),
        "plan": steps,
        "success_count": existing.get("success_count", 0) + 1,
        "last_success": datetime.now().isoformat(),
    }
    save_success_kb(kb)
