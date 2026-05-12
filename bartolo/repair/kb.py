"""bartolo/repair/kb.py — KB de reparacions basada en signatures d'error."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "is", "it", "to", "and", "or",
    "not", "for", "of", "from", "file", "line", "error", "failed", "no",
    "with", "module", "named", "call", "last", "most", "recent", "traceback",
}
_DEFAULT_KB_DIR = Path.home() / ".universal-agent"


def _extract_keywords(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
    seen: Dict[str, int] = {}
    for t in tokens:
        if t.lower() in _STOP_WORDS or len(t) < 4:
            continue
        seen[t] = seen.get(t, 0) + 1
    sorted_tokens = sorted(seen, key=lambda k: -seen[k])
    return sorted_tokens[:3]


class RepairKB:
    def __init__(self, kb_dir: Optional[str] = None):
        self._dir = Path(kb_dir) if kb_dir else _DEFAULT_KB_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._json_path = self._dir / "repair_kb.json"

    def _extract_keywords(self, text: str) -> List[str]:
        return _extract_keywords(text)

    def _fingerprint(self, stack: str, error_type: str, stderr_text: str) -> str:
        kws = "+".join(sorted(self._extract_keywords(stderr_text)))
        raw = f"{stack}|{error_type}|{kws}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _load(self) -> Dict[str, Any]:
        if not self._json_path.exists():
            return {}
        try:
            return json.loads(self._json_path.read_text())
        except Exception:
            return {}

    def _dump(self, data: Dict[str, Any]) -> None:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        tmp = self._json_path.parent / f".repair_kb_tmp_{os.getpid()}"
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, self._json_path)

    def lookup(self, stack: str, error_type: str, stderr_text: str) -> Optional[Dict[str, Any]]:
        fp = self._fingerprint(stack, error_type, stderr_text)
        return self._load().get(fp)

    def save(self, stack: str, error_type: str, keywords: List[str], fix_command: str, source: str) -> None:
        fp = self._fingerprint(stack, error_type, " ".join(keywords))
        data = self._load()
        entry = data.get(fp, {})
        new_count = entry.get("success_count", 0) + 1
        data[fp] = {
            "stack": stack,
            "error_type": error_type,
            "keywords": keywords,
            "fix_command": fix_command if new_count == 1 else entry.get("fix_command", fix_command),
            "success_count": new_count,
            "last_seen": datetime.now().isoformat(timespec="seconds"),
            "source": source if new_count == 1 else entry.get("source", source),
        }
        self._dump(data)
        self._update_markdown(stack, data)

    def markdown_for_stack(self, stack: str) -> str:
        md_path = self._dir / f"repair_kb_{stack}.md"
        if not md_path.exists():
            return ""
        return md_path.read_text(encoding="utf-8")

    def _update_markdown(self, stack: str, data: Dict[str, Any]) -> None:
        entries = [v for v in data.values() if v.get("stack") == stack]
        if not entries:
            return
        lines = [f"# {stack.capitalize()} — fixes coneguts\n"]
        for e in entries:
            lines.append(f"## {e['error_type']} / {' + '.join(e.get('keywords', []))}")
            lines.append(f"Fix: `{e['fix_command']}`")
            lines.append(f"Vist: {e['success_count']} vegades · Font: {e['source']}\n")
        (self._dir / f"repair_kb_{stack}.md").write_text("\n".join(lines), encoding="utf-8")
