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

    def _kb_scan(self, stack: str, stderr_text: str) -> Optional[Dict[str, Any]]:
        """Scan KB for an entry whose keywords are a subset of those in stderr_text."""
        data = self.kb._load()
        stderr_kws = set(self.kb._extract_keywords(stderr_text))
        best: Optional[Dict[str, Any]] = None
        best_score = 0
        for entry in data.values():
            if entry.get("stack") != stack:
                continue
            entry_kws = set(entry.get("keywords", []))
            if entry_kws and entry_kws.issubset(stderr_kws):
                score = len(entry_kws)
                if score > best_score:
                    best_score = score
                    best = entry
        return best

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
        kb_entry = self._kb_scan(stack, initial_result.stderr)
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
