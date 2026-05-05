"""
agents/debugger.py — IntelligentDebugger amb KB persistent + Anthropic fallback
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "is", "it", "to", "and", "or",
    "not", "for", "of", "from", "file", "line", "error", "failed", "no",
    "with", "module", "named", "call", "last", "most", "recent", "traceback",
}
_DEFAULT_KB_DIR = Path.home() / ".universal-agent"


def _tail(text: str, n: int) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-n:]) if len(lines) > n else (text or "")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


class RepairKB:
    def __init__(self, kb_dir: Optional[str] = None):
        self._dir = Path(kb_dir) if kb_dir else _DEFAULT_KB_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._json_path = self._dir / "repair_kb.json"

    def _fingerprint(self, stack: str, error_type: str, stderr_text: str) -> str:
        kws = "+".join(sorted(self._extract_keywords(stderr_text)))
        raw = f"{stack}|{error_type}|{kws}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _extract_keywords(self, text: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
        seen: Dict[str, int] = {}
        for t in tokens:
            if t.lower() in _STOP_WORDS or len(t) < 4:
                continue
            seen[t] = seen.get(t, 0) + 1
        sorted_tokens = sorted(seen, key=lambda k: -seen[k])
        return sorted_tokens[:3]

    def _load(self) -> Dict[str, Any]:
        if not self._json_path.exists():
            return {}
        try:
            return json.loads(self._json_path.read_text())
        except Exception:
            return {}

    def _dump(self, data: Dict[str, Any]) -> None:
        import tempfile
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


@dataclass
class Diagnosis:
    error_type: str
    description: str
    can_fix_automatically: bool
    keywords: List[str] = field(default_factory=list)


@dataclass
class RepairResult:
    repaired: bool
    source: str          # "kb" | "ollama" | "anthropic" | "none"
    fix_command: Optional[str]
    diagnosis: Optional[Diagnosis]
    execution_results: List[Any]          # List[ExecutionResult] from v5.py
    repair_attempts: List[Dict[str, Any]] # [{attempt, command, returncode, stderr_tail}]

    def to_step_error(self, step: Any) -> Any:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from universal_repo_agent_v5 import StepError, tail_lines
        last = self.execution_results[-1] if self.execution_results else None
        return StepError(
            step_id=step.id,
            step_title=step.title,
            command=step.command,
            cwd=step.cwd,
            returncode=last.returncode if last else -1,
            stdout_tail=tail_lines(last.stdout, 8) if last else "",
            stderr_tail=tail_lines(last.stderr, 8) if last else "",
            diagnosis=(
                f"[{self.diagnosis.error_type}] {self.diagnosis.description}"
                if self.diagnosis else ""
            ),
            repaired=self.repaired,
        )


_SECRETS_PATH = Path.home() / ".universal-agent" / "secrets.json"


def _read_api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        secrets = json.loads(_SECRETS_PATH.read_text(encoding="utf-8"))
        return secrets.get("anthropic_api_key")
    except Exception:
        return None


def _make_anthropic_client(api_key: str) -> Any:
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


class IntelligentDebugger:
    """
    Orquestrador de diagnosi i reparació per a passos fallits.
    Manté conversa multi-torn, consulta KB local i fa fallback a Anthropic.
    """

    def __init__(
        self,
        model: str,
        analysis: Any,
        workspace: Any,
        ollama_fn: Optional[Any] = None,
        kb_dir: Optional[str] = None,
        max_repair_attempts: int = 2,
    ):
        self.model = model
        self.analysis = analysis
        self.workspace = Path(workspace)
        self.max_repair_attempts = max_repair_attempts
        self.kb = RepairKB(kb_dir=kb_dir)
        self._ollama_fn = ollama_fn  # injectable for tests; lazy import if None

    def _ollama(self, messages: List[Dict[str, Any]], schema: Optional[Dict] = None, timeout: int = 180) -> Any:
        if self._ollama_fn:
            return self._ollama_fn(self.model, messages, schema=schema, timeout=timeout)
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from universal_repo_agent_v5 import ollama_chat_json
        return ollama_chat_json(self.model, messages, schema=schema, timeout=timeout)

    def _stack(self) -> str:
        services = getattr(self.analysis, "services", [])
        if services:
            return getattr(services[0], "service_type", "unknown")
        return "unknown"

    def _build_system_prompt(self, stack: str, kb_md: str) -> str:
        root = getattr(self.analysis, "root", "")
        manifests = getattr(self.analysis, "top_level_manifests", [])
        manifests_str = ", ".join(manifests[:5]) if manifests else "cap"
        missing = getattr(self.analysis, "missing_system_deps", [])
        missing_str = (f"\nDependències del sistema que falten: {', '.join(missing)}"
                       if missing else "")
        kb_section = f"\nKB de fixes coneguts:\n{kb_md}" if kb_md.strip() else ""
        return (
            f"Ets un expert en desplegar repositoris a Linux.\n"
            f"Stack detectat: {stack}\n"
            f"Arrel del repo: {root}\n"
            f"Fitxers principals: {manifests_str}{missing_str}{kb_section}\n"
            f"Regles: sense sudo, sense comandes destructives, cwd fix, només Linux."
        )

    def _diagnose(self, step: Any, result: Any) -> Diagnosis:
        schema = {
            "type": "object",
            "properties": {
                "diagnosis": {"type": "string"},
                "likely_cause": {"type": "string", "enum": [
                    "missing_dependency", "wrong_config", "missing_env_var",
                    "network_error", "permission_error", "broken_repo",
                    "wrong_version", "port_conflict", "other",
                ]},
                "can_be_fixed_automatically": {"type": "boolean"},
            },
            "required": ["diagnosis", "likely_cause", "can_be_fixed_automatically"],
        }
        stack = self._stack()
        kb_md = self.kb.markdown_for_stack(stack)
        system_prompt = self._build_system_prompt(stack, kb_md)
        try:
            data = self._ollama(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps({
                        "command": result.command,
                        "cwd": result.cwd,
                        "returncode": result.returncode,
                        "stdout": _tail(result.stdout, 20),
                        "stderr": _tail(result.stderr, 20),
                    }, ensure_ascii=False)},
                ],
                schema=schema,
                timeout=60,
            )
            kws_text = f"{result.stderr} {result.stdout}"
            return Diagnosis(
                error_type=data.get("likely_cause", "other"),
                description=data.get("diagnosis", "Error desconegut"),
                can_fix_automatically=data.get("can_be_fixed_automatically", False),
                keywords=RepairKB.__new__(RepairKB)._extract_keywords(kws_text),
            )
        except Exception:
            return Diagnosis(error_type="other", description="No s'ha pogut diagnosticar.",
                             can_fix_automatically=False)
