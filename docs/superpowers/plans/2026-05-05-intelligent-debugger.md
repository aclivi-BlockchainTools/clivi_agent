# Intelligent Debugger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `agents/debugger.py` with `IntelligentDebugger` — a stateful repair orchestrator that replaces the isolated `diagnose_error_with_model`/`ask_model_for_repair` functions in `v5.py` with multi-turn Ollama conversation, a persistent KB, and Anthropic API fallback.

**Architecture:** `IntelligentDebugger` is instantiated inside `execute_plan()` when a step fails, absorbing the diagnosis, repair loop, and ErrorReporter call. It avoids circular imports by using lazy `sys.path` imports from `universal_repo_agent_v5` inside methods (same pattern already used by `agents/error_reporter.py`). `RepairKB` manages two stores: `repair_kb.json` (exact fingerprint match) and `repair_kb_{stack}.md` (injected as model context).

**Tech Stack:** Python 3.8+ stdlib only (`hashlib`, `json`, `os`, `pathlib`, `re`, `datetime`) + optional `anthropic` PyPI package for the Anthropic fallback.

---

### Task 1: `RepairKB` — fingerprinting, JSON persistence, Markdown generation

**Files:**
- Create: `agents/debugger.py`
- Create: `test_repair_kb.py`

- [ ] **Step 1: Write failing tests**

```python
# test_repair_kb.py
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import RepairKB

def test_fingerprint_stable():
    kb = RepairKB.__new__(RepairKB)
    fp1 = kb._fingerprint("python", "missing_dependency", "ModuleNotFoundError requests pip")
    fp2 = kb._fingerprint("python", "missing_dependency", "ModuleNotFoundError requests pip")
    assert fp1 == fp2, "fingerprint must be deterministic"
    assert len(fp1) == 12, f"expected 12 chars, got {len(fp1)}"

def test_fingerprint_different_errors():
    kb = RepairKB.__new__(RepairKB)
    fp1 = kb._fingerprint("python", "missing_dependency", "requests pip install")
    fp2 = kb._fingerprint("python", "port_conflict", "address already in use")
    assert fp1 != fp2

def test_keywords_extraction():
    kb = RepairKB.__new__(RepairKB)
    stderr = "Traceback (most recent call last):\n  File 'main.py', line 42\nModuleNotFoundError: No module named 'requests'"
    kws = kb._extract_keywords(stderr)
    assert "ModuleNotFoundError" in kws or "requests" in kws
    assert len(kws) <= 3

def test_save_and_lookup():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        kb.save("python", "missing_dependency", ["ModuleNotFoundError", "requests"], "pip install requests", "ollama")
        result = kb.lookup("python", "missing_dependency", "ModuleNotFoundError requests pip")
        assert result is not None
        assert result["fix_command"] == "pip install requests"

def test_lookup_miss():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        result = kb.lookup("python", "missing_dependency", "some unknown error xyz")
        assert result is None

def test_markdown_written_on_save():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        kb.save("python", "missing_dependency", ["ModuleNotFoundError", "requests"], "pip install requests", "ollama")
        md_path = os.path.join(tmp, "repair_kb_python.md")
        assert os.path.exists(md_path)
        assert "pip install requests" in open(md_path).read()

def test_markdown_for_stack_empty():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        assert kb.markdown_for_stack("python") == ""

def test_markdown_for_stack_after_save():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        kb.save("python", "missing_dependency", ["requests"], "pip install requests", "ollama")
        md = kb.markdown_for_stack("python")
        assert "pip install requests" in md

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python3 test_repair_kb.py
```
Expected: `ModuleNotFoundError: No module named 'agents.debugger'`

- [ ] **Step 3: Create `agents/debugger.py` with `RepairKB`**

```python
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
        kws = "+".join(self._extract_keywords(stderr_text))
        raw = f"{stack}|{error_type}|{kws}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _extract_keywords(self, text: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
        seen: Dict[str, int] = {}
        for t in tokens:
            if t.lower() in _STOP_WORDS or len(t) < 4 or t.isdigit():
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
        self._json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def lookup(self, stack: str, error_type: str, stderr_text: str) -> Optional[Dict[str, Any]]:
        fp = self._fingerprint(stack, error_type, stderr_text)
        return self._load().get(fp)

    def save(self, stack: str, error_type: str, keywords: List[str], fix_command: str, source: str) -> None:
        fp = self._fingerprint(stack, error_type, " ".join(keywords))
        data = self._load()
        entry = data.get(fp, {})
        data[fp] = {
            "stack": stack,
            "error_type": error_type,
            "keywords": keywords,
            "fix_command": fix_command,
            "success_count": entry.get("success_count", 0) + 1,
            "last_seen": datetime.now().isoformat(timespec="seconds"),
            "source": source,
        }
        self._dump(data)
        self._update_markdown(stack, data)

    def markdown_for_stack(self, stack: str) -> str:
        md_path = self._dir / f"repair_kb_{stack}.md"
        if not md_path.exists():
            return ""
        return md_path.read_text()

    def _update_markdown(self, stack: str, data: Dict[str, Any]) -> None:
        entries = [v for v in data.values() if v.get("stack") == stack]
        if not entries:
            return
        lines = [f"# {stack.capitalize()} — fixes coneguts\n"]
        for e in entries:
            lines.append(f"## {e['error_type']} / {' + '.join(e.get('keywords', []))}")
            lines.append(f"Fix: `{e['fix_command']}`")
            lines.append(f"Vist: {e['success_count']} vegades · Font: {e['source']}\n")
        (self._dir / f"repair_kb_{stack}.md").write_text("\n".join(lines))
```

- [ ] **Step 4: Run tests**

```bash
python3 test_repair_kb.py
```
Expected: `7 tests passed.`

- [ ] **Step 5: Commit**

```bash
git add agents/debugger.py test_repair_kb.py
git commit -m "feat: RepairKB — fingerprinting, JSON + Markdown persistence"
```

---

### Task 2: `Diagnosis` + `RepairResult` dataclasses + secrets reader

**Files:**
- Modify: `agents/debugger.py` (append after `RepairKB`)
- Create: `test_debugger_types.py`

- [ ] **Step 1: Write failing test**

```python
# test_debugger_types.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import Diagnosis, RepairResult, _read_api_key

def test_diagnosis_fields():
    d = Diagnosis(error_type="missing_dependency", description="No module requests",
                  can_fix_automatically=True, keywords=["requests"])
    assert d.error_type == "missing_dependency"
    assert d.keywords == ["requests"]

def test_repair_result_defaults():
    r = RepairResult(repaired=False, source="none", fix_command=None,
                     diagnosis=None, execution_results=[], repair_attempts=[])
    assert not r.repaired
    assert r.source == "none"

def test_read_api_key_from_env():
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-123"
    key = _read_api_key()
    assert key == "sk-test-123"
    del os.environ["ANTHROPIC_API_KEY"]

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python3 test_debugger_types.py
```
Expected: `ImportError: cannot import name 'Diagnosis'`

- [ ] **Step 3: Append to `agents/debugger.py` after the `RepairKB` class**

```python
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
        secrets = json.loads(_SECRETS_PATH.read_text())
        return secrets.get("anthropic_api_key")
    except Exception:
        return None


def _make_anthropic_client(api_key: str) -> Any:
    import anthropic
    return anthropic.Anthropic(api_key=api_key)
```

- [ ] **Step 4: Run tests**

```bash
python3 test_debugger_types.py
```
Expected: `3 tests passed.`

- [ ] **Step 5: Commit**

```bash
git add agents/debugger.py test_debugger_types.py
git commit -m "feat: Diagnosis + RepairResult dataclasses + _read_api_key"
```

---

### Task 3: `IntelligentDebugger` init + `_diagnose()` + `_build_system_prompt()`

**Files:**
- Modify: `agents/debugger.py` (append `IntelligentDebugger` class)
- Create: `test_debugger_diagnose.py`

- [ ] **Step 1: Write failing test**

```python
# test_debugger_diagnose.py
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger, Diagnosis

def fake_ollama(model, messages, schema=None, timeout=180):
    return {"diagnosis": "missing requests library", "likely_cause": "missing_dependency",
            "can_be_fixed_automatically": True}

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = ["requirements.txt"]; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install deps"
    command = "pip install -r requirements.txt"
    cwd = "/tmp/repo"; category = "install"; verify_url = None; verify_port = None

class FakeResult:
    command = "pip install -r requirements.txt"; cwd = "/tmp/repo"
    returncode = 1; stdout = ""
    stderr = "ModuleNotFoundError: No module named 'requests'"

def test_diagnose_returns_diagnosis():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=fake_ollama, kb_dir=tmp)
        d = dbg._diagnose(FakeStep(), FakeResult())
        assert isinstance(d, Diagnosis)
        assert d.error_type == "missing_dependency"
        assert "missing requests" in d.description

def test_diagnose_ollama_failure_returns_default():
    def bad_ollama(*a, **kw):
        raise RuntimeError("connection refused")
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=bad_ollama, kb_dir=tmp)
        d = dbg._diagnose(FakeStep(), FakeResult())
        assert isinstance(d, Diagnosis)
        assert d.error_type == "other"

def test_build_system_prompt_contains_stack_and_rules():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=fake_ollama, kb_dir=tmp)
        prompt = dbg._build_system_prompt("python", "")
        assert "python" in prompt.lower()
        assert "Linux" in prompt or "linux" in prompt.lower()
        assert "sudo" in prompt

def test_build_system_prompt_includes_kb():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=fake_ollama, kb_dir=tmp)
        prompt = dbg._build_system_prompt("python", "## missing_dependency\nFix: pip install requests")
        assert "pip install requests" in prompt

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python3 test_debugger_diagnose.py
```
Expected: `ImportError: cannot import name 'IntelligentDebugger'`

- [ ] **Step 3: Append `IntelligentDebugger` class to `agents/debugger.py`**

```python
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
```

- [ ] **Step 4: Run tests**

```bash
python3 test_debugger_diagnose.py
```
Expected: `4 tests passed.`

- [ ] **Step 5: Commit**

```bash
git add agents/debugger.py test_debugger_diagnose.py
git commit -m "feat: IntelligentDebugger init + _diagnose + _build_system_prompt"
```

---

### Task 4: `_run_repair_cmd()` + `_repair_loop_ollama()` — multi-turn conversation

**Files:**
- Modify: `agents/debugger.py` (add methods inside `IntelligentDebugger`)
- Create: `test_debugger_ollama_loop.py`

- [ ] **Step 1: Write failing test**

```python
# test_debugger_ollama_loop.py
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger

call_count = [0]
suggested = ["pip install requests", "pip install -r requirements.txt"]

def fake_ollama_seq(model, messages, schema=None, timeout=180):
    i = call_count[0]
    call_count[0] += 1
    return {"command": suggested[i % 2], "reason": "install missing dep"}

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = []; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install"; command = "pip install -r req.txt"
    cwd = "/tmp"; category = "install"; verify_url = None; verify_port = None

class FakeResult:
    command = "pip install -r req.txt"; cwd = "/tmp"; returncode = 1
    stdout = ""; stderr = "ModuleNotFoundError: No module named 'requests'"
    step_id = "py-install"; repaired = False
    started_at = 0.0; finished_at = 0.0

def test_loop_makes_n_attempts_on_failure():
    call_count[0] = 0
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=fake_ollama_seq, kb_dir=tmp, max_repair_attempts=2)
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        attempts = dbg._repair_loop_ollama(FakeStep(), FakeResult(), "python", "")
        assert len(attempts) == 2
        assert call_count[0] == 2

def test_loop_stops_on_success():
    call_count[0] = 0
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=fake_ollama_seq, kb_dir=tmp, max_repair_attempts=2)
        success_result = FakeResult()
        success_result.returncode = 0
        dbg._run_repair_cmd = lambda cmd, step, attempt: (success_result, True)
        attempts = dbg._repair_loop_ollama(FakeStep(), FakeResult(), "python", "")
        assert len(attempts) == 1
        assert attempts[0]["success"] is True
        assert call_count[0] == 1

def test_loop_history_grows():
    call_count[0] = 0
    captured_messages = []
    def capturing_ollama(model, messages, schema=None, timeout=180):
        captured_messages.append(list(messages))
        i = call_count[0]; call_count[0] += 1
        return {"command": suggested[i % 2], "reason": "test"}
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=capturing_ollama, kb_dir=tmp, max_repair_attempts=2)
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        dbg._repair_loop_ollama(FakeStep(), FakeResult(), "python", "")
        assert len(captured_messages[1]) > len(captured_messages[0])

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python3 test_debugger_ollama_loop.py
```
Expected: `AttributeError: 'IntelligentDebugger' object has no attribute '_repair_loop_ollama'`

- [ ] **Step 3: Add `_run_repair_cmd` and `_repair_loop_ollama` inside `IntelligentDebugger` in `agents/debugger.py`**

```python
    def _run_repair_cmd(self, command: str, step: Any, attempt: int) -> tuple:
        """Validates and executes a repair command. Returns (ExecutionResult, success: bool)."""
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from universal_repo_agent_v5 import (
            run_shell, validate_command, maybe_background_command,
            register_service, verify_step as _verify_step,
            _extract_agent_pid, ExecutionResult,
        )
        repo_root = Path(self.analysis.root)
        try:
            validate_command(command, repo_root=repo_root)
        except Exception as e:
            _warn(f"Repair command rebutjat pel validator: {e}")
            now = time.time()
            return ExecutionResult(
                step_id=step.id, command=command, cwd=step.cwd,
                returncode=-1, stdout="", stderr=f"Rejected by validator: {e}",
                started_at=now, finished_at=now,
            ), False

        fix_cmd = command
        is_bg = False
        if step.category == "run":
            fix_cmd, is_bg = maybe_background_command(command)

        result = run_shell(fix_cmd, cwd=Path(step.cwd), repo_root=repo_root)
        result.step_id = step.id
        result.repaired = True
        success = result.returncode == 0

        if success and is_bg:
            pid = _extract_agent_pid(result.stdout)
            register_service(
                workspace=self.workspace,
                repo_name=self.analysis.repo_name,
                step_id=step.id,
                cwd=step.cwd,
                command=command,
                pid=pid,
                log_file=str(Path(step.cwd) / ".agent_last_run.log"),
            )
        if success and step.category == "run":
            if not _verify_step(step):
                result.returncode = 1
                result.stderr += "\nVerification failed after repair.\n"
                success = False
        return result, success

    def _repair_loop_ollama(
        self, step: Any, initial_result: Any, stack: str, kb_md: str
    ) -> List[Dict[str, Any]]:
        """Multi-turn repair loop with Ollama. Returns list of attempt dicts."""
        schema = {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["command", "reason"],
        }
        system_prompt = self._build_system_prompt(stack, kb_md)
        history: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({
                "failed_command": step.command,
                "cwd": step.cwd,
                "returncode": initial_result.returncode,
                "stderr": _tail(initial_result.stderr, 15),
                "stdout": _tail(initial_result.stdout, 10),
            }, ensure_ascii=False)},
        ]
        attempts: List[Dict[str, Any]] = []

        for attempt in range(1, self.max_repair_attempts + 1):
            try:
                data = self._ollama(messages=history, schema=schema, timeout=90)
                command = data["command"].strip().splitlines()[0]
            except Exception as e:
                _warn(f"Ollama repair suggestion failed: {e}")
                break

            history.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
            result, success = self._run_repair_cmd(command, step, attempt)
            attempt_record = {
                "attempt": attempt,
                "command": command,
                "returncode": result.returncode,
                "stderr_tail": _tail(result.stderr, 5),
                "result": result,
                "success": success,
            }
            attempts.append(attempt_record)

            if success:
                break

            history.append({"role": "user", "content": json.dumps({
                "executed": command,
                "returncode": result.returncode,
                "stderr": _tail(result.stderr, 15),
                "stdout": _tail(result.stdout, 10),
                "message": "Aquesta comanda ha fallat. Proposa una alternativa diferent.",
            }, ensure_ascii=False)})

        return attempts
```

- [ ] **Step 4: Run tests**

```bash
python3 test_debugger_ollama_loop.py
```
Expected: `3 tests passed.`

- [ ] **Step 5: Commit**

```bash
git add agents/debugger.py test_debugger_ollama_loop.py
git commit -m "feat: _run_repair_cmd + _repair_loop_ollama — multi-turn with history"
```

---

### Task 5: `_repair_with_anthropic()` — Anthropic API fallback

**Files:**
- Modify: `agents/debugger.py` (add method inside `IntelligentDebugger`)
- Create: `test_debugger_anthropic.py`

- [ ] **Step 1: Write failing test**

```python
# test_debugger_anthropic.py
import sys, os, tempfile, unittest.mock
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = []; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install"
    command = "pip install -r req.txt"
    cwd = "/tmp"; category = "install"; verify_url = None; verify_port = None

def test_no_api_key_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=lambda *a, **kw: {}, kb_dir=tmp)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with unittest.mock.patch("agents.debugger._read_api_key", return_value=None):
            result = dbg._repair_with_anthropic(FakeStep(), [], "python", "")
            assert result is None

def test_anthropic_not_installed_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=lambda *a, **kw: {}, kb_dir=tmp)
        with unittest.mock.patch("agents.debugger._read_api_key", return_value="sk-test"):
            with unittest.mock.patch("agents.debugger._make_anthropic_client",
                                     side_effect=ImportError("no anthropic")):
                result = dbg._repair_with_anthropic(FakeStep(), [], "python", "")
                assert result is None

def test_anthropic_called_returns_command():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=lambda *a, **kw: {}, kb_dir=tmp)
        mock_client = unittest.mock.MagicMock()
        mock_client.messages.create.return_value.content = [
            unittest.mock.MagicMock(text='{"command": "pip install requests", "reason": "missing dep"}')
        ]
        prior = [{"attempt": 1, "command": "pip install -r req.txt",
                  "returncode": 1, "stderr_tail": "ModuleNotFoundError", "result": None, "success": False}]
        with unittest.mock.patch("agents.debugger._read_api_key", return_value="sk-test"):
            with unittest.mock.patch("agents.debugger._make_anthropic_client", return_value=mock_client):
                result = dbg._repair_with_anthropic(FakeStep(), prior, "python", "")
                assert result == "pip install requests"
                assert mock_client.messages.create.called

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python3 test_debugger_anthropic.py
```
Expected: `AttributeError: 'IntelligentDebugger' object has no attribute '_repair_with_anthropic'`

- [ ] **Step 3: Add `_repair_with_anthropic` inside `IntelligentDebugger` in `agents/debugger.py`**

```python
    def _repair_with_anthropic(
        self,
        step: Any,
        prior_attempts: List[Dict[str, Any]],
        stack: str,
        kb_md: str,
    ) -> Optional[str]:
        """
        Fallback: asks Claude (Anthropic API) for a repair command after Ollama exhaustion.
        Returns the command string, or None if unavailable or API call fails.
        """
        api_key = _read_api_key()
        if not api_key:
            _warn("Anthropic API key no configurada — saltant fallback.")
            return None
        try:
            client = _make_anthropic_client(api_key)
        except ImportError:
            _warn("anthropic no instal·lat (pip install anthropic) — saltant fallback.")
            return None

        system_prompt = self._build_system_prompt(stack, kb_md)

        messages: List[Dict[str, Any]] = []
        for a in prior_attempts:
            messages.append({"role": "user", "content": json.dumps({
                "attempt": a["attempt"],
                "tried_command": a["command"],
                "returncode": a["returncode"],
                "stderr": a["stderr_tail"],
            }, ensure_ascii=False)})
            messages.append({"role": "assistant",
                             "content": f"(intent {a['attempt']} ha fallat, cal una altra solució)"})

        messages.append({"role": "user", "content": (
            f"Ollama ha esgotat {len(prior_attempts)} intents sense èxit per al pas: "
            f"'{step.title}' (comanda original: {step.command}). "
            f"Necessito UNA comanda shell alternativa per solucionar-ho. "
            f"Respon NOMÉS en JSON: {{\"command\": \"...\", \"reason\": \"...\"}}"
        )})

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=256,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
            )
            raw = response.content[0].text.strip()
            match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                command = data.get("command", "").strip().splitlines()[0]
                if command:
                    return command
        except Exception as e:
            _warn(f"Anthropic API fallback ha fallat: {e}")
        return None
```

- [ ] **Step 4: Run tests**

```bash
python3 test_debugger_anthropic.py
```
Expected: `3 tests passed.`

- [ ] **Step 5: Commit**

```bash
git add agents/debugger.py test_debugger_anthropic.py
git commit -m "feat: _repair_with_anthropic — Anthropic fallback with prompt caching"
```

---

### Task 6: `repair()` + `_escalate()` — main orchestrator

**Files:**
- Modify: `agents/debugger.py` (add `repair` and `_escalate` methods inside `IntelligentDebugger`)
- Create: `test_debugger_repair.py`

- [ ] **Step 1: Write failing test**

```python
# test_debugger_repair.py
import sys, os, tempfile, time
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger, RepairResult

def make_ollama(response):
    def fn(model, messages, schema=None, timeout=180):
        return response
    return fn

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = []; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install"; command = "pip install -r req.txt"
    cwd = "/tmp"; category = "install"; verify_url = None; verify_port = None

class FakeResult:
    command = "pip install -r req.txt"; cwd = "/tmp"; returncode = 1
    stdout = ""; stderr = "ModuleNotFoundError: requests"
    step_id = "py-install"; repaired = False
    started_at = 0.0; finished_at = 0.0

def make_success_result():
    r = FakeResult(); r.returncode = 0; return r

def test_kb_hit_returns_repaired_source_kb():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "missing_dependency",
                                    "can_be_fixed_automatically": True}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg.kb.save("unknown", "missing_dependency", ["requests"], "pip install requests", "test")
        dbg._run_repair_cmd = lambda cmd, step, attempt: (make_success_result(), True)
        result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert result.repaired is True
        assert result.source == "kb"

def test_ollama_success_returns_repaired_source_ollama():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "missing_dependency",
                                    "can_be_fixed_automatically": True,
                                    "command": "pip install requests", "reason": "dep"}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg._run_repair_cmd = lambda cmd, step, attempt: (make_success_result(), True)
        result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert result.repaired is True
        assert result.source == "ollama"

def test_all_fail_returns_not_repaired():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "missing_dependency",
                                    "can_be_fixed_automatically": True,
                                    "command": "false", "reason": "test"}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        dbg._repair_with_anthropic = lambda *a, **kw: None
        dbg._escalate = lambda *a, **kw: None
        result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert result.repaired is False
        assert result.source == "none"

def test_result_to_step_error_repaired_false():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "other",
                                    "can_be_fixed_automatically": False,
                                    "command": "false", "reason": "test"}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        dbg._repair_with_anthropic = lambda *a, **kw: None
        dbg._escalate = lambda *a, **kw: None
        repair_result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert isinstance(repair_result, RepairResult)
        assert repair_result.repaired is False

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python3 test_debugger_repair.py
```
Expected: `AttributeError: 'IntelligentDebugger' object has no attribute 'repair'`

- [ ] **Step 3: Add `repair()` and `_escalate()` inside `IntelligentDebugger` in `agents/debugger.py`**

```python
    def repair(self, step: Any, initial_result: Any, approve_all: bool = True) -> RepairResult:
        """
        Main entry point. Orchestrates: KB lookup → Ollama multi-turn → Anthropic fallback.
        Returns RepairResult with all execution details.
        """
        stack = self._stack()
        kb_md = self.kb.markdown_for_stack(stack)
        all_results: List[Any] = [initial_result]
        all_attempts: List[Dict[str, Any]] = []

        # 1. KB lookup — if known fix exists, try it first
        kb_entry = self.kb.lookup(stack, "unknown", initial_result.stderr)
        if kb_entry:
            kb_cmd = kb_entry["fix_command"]
            _info(f"KB hit: {kb_cmd}")
            kb_result, kb_success = self._run_repair_cmd(kb_cmd, step, 0)
            all_results.append(kb_result)
            all_attempts.append({"attempt": 0, "command": kb_cmd,
                                  "returncode": kb_result.returncode,
                                  "stderr_tail": _tail(kb_result.stderr, 5),
                                  "result": kb_result, "success": kb_success})
            if kb_success:
                self.kb.save(stack, "kb_hit", kb_entry.get("keywords", []), kb_cmd, "kb")
                return RepairResult(repaired=True, source="kb", fix_command=kb_cmd,
                                    diagnosis=None, execution_results=all_results,
                                    repair_attempts=all_attempts)

        # 2. Diagnose with repo context
        diagnosis = self._diagnose(step, initial_result)
        _info(f"Diagnosi: [{diagnosis.error_type}] {diagnosis.description}")

        # 3. Ollama multi-turn loop
        ollama_attempts = self._repair_loop_ollama(step, initial_result, stack, kb_md)
        all_attempts.extend(ollama_attempts)
        all_results.extend(a["result"] for a in ollama_attempts if a.get("result") is not None)

        successful = next((a for a in ollama_attempts if a.get("success")), None)
        if successful:
            self.kb.save(stack, diagnosis.error_type, diagnosis.keywords,
                         successful["command"], "ollama")
            return RepairResult(repaired=True, source="ollama", fix_command=successful["command"],
                                diagnosis=diagnosis, execution_results=all_results,
                                repair_attempts=all_attempts)

        # 4. Anthropic API fallback
        anthropic_cmd = self._repair_with_anthropic(step, ollama_attempts, stack, kb_md)
        if anthropic_cmd:
            _info(f"Anthropic suggereix: {anthropic_cmd}")
            ant_result, ant_success = self._run_repair_cmd(anthropic_cmd, step, 99)
            all_results.append(ant_result)
            all_attempts.append({"attempt": 99, "command": anthropic_cmd,
                                  "returncode": ant_result.returncode,
                                  "stderr_tail": _tail(ant_result.stderr, 5),
                                  "result": ant_result, "success": ant_success})
            if ant_success:
                self.kb.save(stack, diagnosis.error_type, diagnosis.keywords,
                             anthropic_cmd, "anthropic")
                return RepairResult(repaired=True, source="anthropic", fix_command=anthropic_cmd,
                                    diagnosis=diagnosis, execution_results=all_results,
                                    repair_attempts=all_attempts)

        # 5. All failed — escalate via ErrorReporter
        self._escalate(step, diagnosis, all_attempts, initial_result)

        return RepairResult(repaired=False, source="none", fix_command=None,
                            diagnosis=diagnosis, execution_results=all_results,
                            repair_attempts=all_attempts)

    def _escalate(self, step: Any, diagnosis: Diagnosis,
                  attempts: List[Dict[str, Any]], initial_result: Any) -> None:
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent))
            from agents.error_reporter import ErrorReporter
            stack = self._stack()
            reporter = ErrorReporter(workspace=self.workspace)
            step_error_proxy = type("SE", (), {
                "step_title": step.title,
                "command": step.command,
                "cwd": step.cwd,
                "returncode": initial_result.returncode,
                "stderr_tail": _tail(initial_result.stderr, 8),
                "stdout_tail": _tail(initial_result.stdout, 8),
                "diagnosis": f"[{diagnosis.error_type}] {diagnosis.description}",
                "repaired": False,
            })()
            clean_attempts = [{k: v for k, v in a.items() if k != "result"} for a in attempts]
            report = reporter.generate(
                step_error=step_error_proxy,
                repair_attempts=clean_attempts,
                repo_root=Path(self.analysis.root),
                repo_name=self.analysis.repo_name,
                stack_name=stack,
                missing_deps=list(getattr(self.analysis, "missing_system_deps", [])),
                full_stderr=_tail(initial_result.stderr, 20),
            )
            reporter.save_and_print(report)
        except Exception as e:
            _warn(f"ErrorReporter: {e}")
```

- [ ] **Step 4: Run tests**

```bash
python3 test_debugger_repair.py
```
Expected: `4 tests passed.`

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
python3 test_repair_kb.py && python3 test_debugger_types.py && \
python3 test_debugger_diagnose.py && python3 test_debugger_ollama_loop.py && \
python3 test_debugger_anthropic.py && python3 test_debugger_repair.py
```
Expected: all files report all tests passed.

- [ ] **Step 6: Commit**

```bash
git add agents/debugger.py test_debugger_repair.py
git commit -m "feat: repair() orchestrator + _escalate — KB + Ollama + Anthropic + ErrorReporter"
```

---

### Task 7: Integration in `v5.py` — replace old functions and loop

**Files:**
- Modify: `universal_repo_agent_v5.py`

- [ ] **Step 1: Backup**

```bash
cp universal_repo_agent_v5.py universal_repo_agent_v5.py.bak_debugger
```

- [ ] **Step 2: Delete `diagnose_error_with_model` (~lines 2416–2422)**

Remove this entire function:

```python
def diagnose_error_with_model(model: str, step: CommandStep, result: ExecutionResult) -> str:
    schema = {"type": "object", "properties": {"diagnosis": {"type": "string"}, "likely_cause": {"type": "string", "enum": ["missing_dependency", "wrong_config", "missing_env_var", "network_error", "permission_error", "broken_repo", "wrong_version", "port_conflict", "other"]}, "can_be_fixed_automatically": {"type": "boolean"}}, "required": ["diagnosis", "likely_cause", "can_be_fixed_automatically"]}
    try:
        data = ollama_chat_json(model=model, messages=[{"role": "system", "content": "Diagnose this failed deployment command. Be concise and specific. Output JSON only."}, {"role": "user", "content": json.dumps({"command": result.command, "cwd": result.cwd, "returncode": result.returncode, "stdout": tail_lines(result.stdout, 20), "stderr": tail_lines(result.stderr, 20)}, ensure_ascii=False)}], schema=schema, timeout=60)
        return f"[{data.get('likely_cause', 'other')}] {data.get('diagnosis', 'Error desconegut')}"
    except Exception:
        return "No s'ha pogut diagnosticar l'error automàticament."
```

- [ ] **Step 3: Delete `ask_model_for_repair` (~lines 2425–2434)**

Remove this entire function:

```python
def ask_model_for_repair(model: str, analysis: RepoAnalysis, step: CommandStep, result: ExecutionResult) -> Optional[str]:
    schema = {"type": "object", "properties": {"command": {"type": "string"}, "reason": {"type": "string"}}, "required": ["command", "reason"]}
    try:
        data = ollama_chat_json(model=model, messages=[{"role": "system", "content": "Suggest ONE replacement shell command to fix this failed deployment step. Constraints: no sudo, no destructive changes, Linux only, must run in given cwd. Output JSON only."}, {"role": "user", "content": json.dumps({"failed_command": step.command, "cwd": step.cwd, "returncode": result.returncode, "stderr": tail_lines(result.stderr, 15), "stdout": tail_lines(result.stdout, 10)}, ensure_ascii=False)}], schema=schema, timeout=90)
        command = data["command"].strip().splitlines()[0]
        validate_command(command, repo_root=Path(analysis.root))
        return command
    except Exception as e:
        warn(f"Suggeriment de reparació ha fallat: {e}")
        return None
```

- [ ] **Step 4: Replace the repair block inside `execute_plan()` (~lines 2549–2607)**

Find this block (starts at `warn(f"Step failed with code {current_result.returncode}.")`, ends just before `if step.critical and not repaired:`):

```python
        warn(f"Step failed with code {current_result.returncode}.")
        diagnosis = diagnose_error_with_model(model, step, current_result)
        repaired = False
        _repair_attempts: list = []
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            fix_cmd = ask_model_for_repair(model, analysis, step, current_result)
            if not fix_cmd:
                break
            warn(f"Repair attempt {attempt}: {fix_cmd}")
            if not approve_all:
                answer = input("Execute repair command? [y/N]: ").strip().lower()
                if answer not in {"y", "yes", "s", "si"}:
                    warn("Repair skipped by user.")
                    break
            if step.category == "run":
                fix_to_run, fix_bg = maybe_background_command(fix_cmd)
            else:
                fix_to_run, fix_bg = fix_cmd, False
            repair_result = run_shell(fix_to_run, cwd=Path(step.cwd), repo_root=repo_root)
            repair_result.step_id = step.id
            repair_result.repaired = True
            results.append(repair_result)
            write_log(log_dir, f"{idx:02d}_{slugify(step.id)}_repair{attempt}.log", f"REPAIR COMMAND: {fix_to_run}\nCWD: {repair_result.cwd}\nRETURNCODE: {repair_result.returncode}\n\nSTDOUT:\n{repair_result.stdout}\n\nSTDERR:\n{repair_result.stderr}\n")
            _repair_attempts.append({"attempt": attempt, "command": fix_cmd, "returncode": repair_result.returncode, "stderr_tail": tail_lines(repair_result.stderr, 5)})
            success = repair_result.returncode == 0
            if success and fix_bg:
                pid = _extract_agent_pid(repair_result.stdout)
                register_service(workspace=workspace, repo_name=analysis.repo_name, step_id=step.id,
                                 cwd=step.cwd, command=fix_cmd, pid=pid,
                                 log_file=str(Path(step.cwd) / ".agent_last_run.log"))
            if success and step.category == "run":
                success = verify_step(step)
                if not success:
                    repair_result.returncode = 1
                    repair_result.stderr += "\nVerification failed after repair: service did not become reachable.\n"
            if success:
                info("Repair succeeded.")
                repaired = True
                break
            current_result = repair_result
        errors.append(StepError(step_id=step.id, step_title=step.title, command=step.command, cwd=step.cwd, returncode=current_result.returncode, stdout_tail=tail_lines(current_result.stdout, 8), stderr_tail=tail_lines(current_result.stderr, 8), diagnosis=diagnosis, repaired=repaired))
        if not repaired:
            try:
                import sys as _sys
                _sys.path.insert(0, str(Path(__file__).parent))
                from agents.error_reporter import ErrorReporter as _ER
                _stack = ", ".join(sorted({s.service_type for s in analysis.services}))
                _reporter = _ER(workspace=workspace)
                _report = _reporter.generate(
                    step_error=errors[-1],
                    repair_attempts=_repair_attempts,
                    repo_root=repo_root,
                    repo_name=analysis.repo_name,
                    stack_name=_stack,
                    missing_deps=list(analysis.missing_system_deps),
                    full_stderr=tail_lines(current_result.stderr, 20),
                )
                _reporter.save_and_print(_report)
            except Exception as _re:
                warn(f"ErrorReporter: {_re}")
```

Replace with:

```python
        warn(f"Step failed with code {current_result.returncode}.")
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from agents.debugger import IntelligentDebugger
        _debugger = IntelligentDebugger(
            model=model,
            analysis=analysis,
            workspace=workspace,
            max_repair_attempts=MAX_REPAIR_ATTEMPTS,
        )
        _repair = _debugger.repair(step, current_result, approve_all=approve_all)
        results.extend(r for r in _repair.execution_results if r is not current_result)
        errors.append(_repair.to_step_error(step))
        repaired = _repair.repaired
```

- [ ] **Step 5: Run pre-existing tests to confirm no regressions**

```bash
python3 test_node_library_detection.py && python3 test_error_reporter.py
```
Expected: all tests pass.

- [ ] **Step 6: Run the full new test suite**

```bash
python3 test_repair_kb.py && python3 test_debugger_types.py && \
python3 test_debugger_diagnose.py && python3 test_debugger_ollama_loop.py && \
python3 test_debugger_anthropic.py && python3 test_debugger_repair.py
```
Expected: all files report all tests passed.

- [ ] **Step 7: Commit**

```bash
git add universal_repo_agent_v5.py
git commit -m "refactor: integrate IntelligentDebugger into execute_plan — remove diagnose_error_with_model + ask_model_for_repair"
```
