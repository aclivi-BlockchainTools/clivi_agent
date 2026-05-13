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

_SEED_ENTRIES = [
    # (stack, error_type, keywords, fix_command)
    # Keywords han de ser tokens que SEMPRE apareixen a l'error (1-2, molt distintius)
    ("python", "missing_dependency", ["ModuleNotFoundError"],
     "pip install --break-system-packages <missing_pkg>"),
    ("python", "missing_dependency", ["ImportError"],
     "pip install --break-system-packages <missing_pkg>"),
    ("python", "wrong_version", ["SyntaxError"],
     "python3 --version && pip list 2>/dev/null | head -20"),
    ("python", "permission_error", ["PermissionError"],
     "chmod -R u+rw ."),
    ("python", "missing_env_var", ["KeyError"],
     "test -f .env && set -a && . ./.env && set +a; python3 -c 'import os; print(os.environ)'"),
    ("python", "port_conflict", ["Address", "already"],
     "fuser -k <port>/tcp 2>/dev/null; sleep 1"),
    ("python", "broken_repo", ["requirements.txt"],
     "find . -name 'requirements*.txt' -type f"),
    ("node", "missing_dependency", ["Cannot", "find"],
     "npm install"),
    ("node", "missing_dependency", ["MODULE_NOT_FOUND"],
     "npm install"),
    ("node", "wrong_version", ["requires", "node"],
     "node --version && npm --version"),
    ("node", "port_conflict", ["EADDRINUSE"],
     "fuser -k <port>/tcp 2>/dev/null; sleep 1"),
    ("node", "wrong_config", ["ENOENT"],
     "npm install --legacy-peer-deps"),
    ("go", "missing_dependency", ["cannot", "find"],
     "go mod tidy && go mod download"),
    ("go", "wrong_version", ["go.mod", "incompatible"],
     "go mod tidy"),
    ("generic", "network_error", ["Connection", "refused"],
     "sleep 3 && nc -z localhost <port> && echo 'ready' || echo 'still down'"),
    ("generic", "missing_dependency", ["command", "found"],
     "which <binary> 2>/dev/null || apt list --installed 2>/dev/null | grep <binary>"),
    ("generic", "port_conflict", ["already", "use"],
     "fuser -k <port>/tcp 2>/dev/null; sleep 1"),
    ("generic", "permission_error", ["EACCES"],
     "chmod -R u+rw ."),
]


def _extract_keywords(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
    seen: Dict[str, int] = {}
    for t in tokens:
        if t.lower() in _STOP_WORDS or len(t) < 4:
            continue
        seen[t] = seen.get(t, 0) + 1
    sorted_tokens = sorted(seen, key=lambda k: -seen[k])
    return sorted_tokens[:5]


class RepairKB:
    def __init__(self, kb_dir: Optional[str] = None):
        self._dir = Path(kb_dir) if kb_dir else _DEFAULT_KB_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._json_path = self._dir / "repair_kb.json"
        self._seed()

    def _seed(self) -> None:
        data = self._load()
        if data:
            return
        for stack, error_type, keywords, fix_command in _SEED_ENTRIES:
            self.save(stack, error_type, keywords, fix_command, source="builtin")

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
        filtered_kws = _extract_keywords(" ".join(keywords))
        data[fp] = {
            "stack": stack,
            "error_type": error_type,
            "keywords": filtered_kws if filtered_kws else keywords,
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
