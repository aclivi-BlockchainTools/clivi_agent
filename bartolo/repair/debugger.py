"""bartolo/repair/debugger.py — IntelligentDebugger amb KB + DeepSeek + Anthropic fallback."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from bartolo.llm import ollama_chat_json
from bartolo.repair.anthropic import repair_with_anthropic
from bartolo.repair.deepseek import repair_with_deepseek
from bartolo.repair.fallback import _get_fallbacks
from bartolo.repair.kb import RepairKB, _extract_keywords
from bartolo.types import ExecutionResult, StepError

_CONVERSATIONAL_PREFIXES = [
    "per arreglar-ho prova:",
    "per assegurar-te",
    "per solucionar",
    "per verificar",
    "per comprovar",
    "la solució és",
    "pots provar",
    "prova amb",
    "executa:",
    "executa",
    "cal fer",
    "caldria",
    "has de fer",
    "podries fer",
    "intenta amb",
    "intenta",
    "suggereixo",
    "recomano",
    "to fix this",
    "try running",
    "try:",
    "run:",
    "you should",
    "you can",
    "the fix is",
    "the solution is",
    "i recommend",
    "let's try",
    "we need to",
    "first,",
    "then,",
    "finally,",
]


def _tail(text: str, n: int) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-n:]) if len(lines) > n else (text or "")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _extract_bash_command(raw: str) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    if not lines:
        return None
    for line in lines:
        lower = line.lower()
        if any(lower.startswith(p) for p in _CONVERSATIONAL_PREFIXES):
            continue
        words = line.split()
        if len(words) >= 4 and all(not w.startswith("-") and "/" not in w for w in words):
            has_known_cmd = any(
                w in {"pip", "npm", "yarn", "pnpm", "docker", "git", "make", "cargo",
                      "go", "deno", "mix", "dotnet", "python", "python3", "node", "npx",
                      "uvicorn", "streamlit", "flask", "django-admin", "bash", "sh",
                      "nc", "curl", "wget", "apt", "apt-get", "systemctl", "kill"}
                for w in words
            )
            if not has_known_cmd:
                continue
        return line
    return lines[0]


def _sanitize_quotes(command: str) -> str:
    if not command:
        return command
    stripped = command.strip()
    if stripped.startswith('"') and not stripped.endswith('"'):
        stripped = stripped[1:]
    if stripped.endswith('"') and not stripped.startswith('"'):
        stripped = stripped[:-1]
    dq_count = stripped.count('"')
    if dq_count % 2 != 0:
        stripped = stripped.replace('"', '')
    return stripped


@dataclass
class Diagnosis:
    error_type: str
    description: str
    can_fix_automatically: bool
    keywords: List[str] = field(default_factory=list)


@dataclass
class RepairResult:
    repaired: bool
    source: str          # "kb" | "ollama" | "deepseek" | "anthropic" | "none"
    fix_command: Optional[str]
    diagnosis: Optional[Diagnosis]
    execution_results: List[Any]
    repair_attempts: List[Dict[str, Any]]

    def to_step_error(self, step: Any) -> Any:
        last = self.execution_results[-1] if self.execution_results else None
        return StepError(
            step_id=step.id,
            step_title=step.title,
            command=step.command,
            cwd=step.cwd,
            returncode=last.returncode if last else -1,
            stdout_tail=_tail(last.stdout, 8) if last else "",
            stderr_tail=_tail(last.stderr, 8) if last else "",
            diagnosis=(
                f"[{self.diagnosis.error_type}] {self.diagnosis.description}"
                if self.diagnosis else ""
            ),
            repaired=self.repaired,
        )


class IntelligentDebugger:
    """Orquestrador de diagnosi i reparació per a passos fallits.
    Loop de 4 nivells: Plan B → KB → DeepSeek → Anthropic → Escalate.
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
        self._ollama_fn = ollama_fn

    def _ollama(self, messages: List[Dict[str, Any]], schema: Optional[Dict] = None, timeout: int = 180) -> Any:
        if self._ollama_fn:
            return self._ollama_fn(self.model, messages, schema=schema, timeout=timeout)
        return ollama_chat_json(self.model, messages, schema=schema, timeout=timeout)

    def _stack(self) -> str:
        services = getattr(self.analysis, "services", [])
        if services:
            return getattr(services[0], "service_type", "unknown")
        return "unknown"

    _BASH_ONLY_INSTRUCTION = (
        "IMPORTANT: El camp 'command' ha de ser UNA sola comanda bash executable, "
        "sense text introductori ni explicacions. Només la comanda crua. "
        "Exemples vàlids: 'pip install requests', 'npm install', 'docker start postgresql'. "
        "Mai: 'Per arreglar-ho prova: npm install' o 'La solució és fer npm install'. "
        "No facis servir cometes dobles dins la comanda — usa cometes simples si cal."
    )

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
            f"Regles: sense sudo, sense comandes destructives, cwd fix, només Linux.\n"
            f"{self._BASH_ONLY_INSTRUCTION}"
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
                keywords=_extract_keywords(kws_text),
            )
        except Exception:
            return Diagnosis(error_type="other", description="No s'ha pogut diagnosticar.",
                             can_fix_automatically=False)

    def _run_repair_cmd(self, command: str, step: Any, attempt: int) -> tuple:
        from bartolo.shell import run_shell, maybe_background_command
        from bartolo.validator import validate_command
        from bartolo.executor import register_service, verify_step as _verify_step, _extract_agent_pid

        command = re.sub(r'\s*(?:2>&1\s*)?\|\s*(?:head|tail)\s+[-\d]+\s*$', '', command).rstrip()
        command = _sanitize_quotes(command)
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
                command = _extract_bash_command(data.get("command", ""))
                if not command:
                    _warn("El model no ha generat una comanda usable.")
                    break
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

    def _kb_scan(self, stack: str, stderr_text: str) -> Optional[Dict[str, Any]]:
        data = self.kb._load()
        stderr_kws = set(_extract_keywords(stderr_text))
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
        """Orquestra: Plan B → KB → Ollama → DeepSeek → Anthropic → Escalate."""
        stack = self._stack()
        kb_md = self.kb.markdown_for_stack(stack)
        all_results: List[Any] = [initial_result]
        all_attempts: List[Dict[str, Any]] = []

        # 1. Plan B fallbacks (local, gratis)
        fallbacks = _get_fallbacks(step, initial_result)
        for fb_cmd in fallbacks:
            _info(f"Plan B: provant '{fb_cmd}'...")
            fb_result, fb_success = self._run_repair_cmd(fb_cmd, step, 0)
            all_results.append(fb_result)
            all_attempts.append({"attempt": 0, "command": fb_cmd,
                                  "returncode": fb_result.returncode,
                                  "stderr_tail": _tail(fb_result.stderr, 5),
                                  "result": fb_result, "success": fb_success})
            if fb_success:
                return RepairResult(repaired=True, source="fallback", fix_command=fb_cmd,
                                    diagnosis=None, execution_results=all_results,
                                    repair_attempts=all_attempts)

        # 2. KB lookup — si hi ha un fix conegut, prova'l primer
        kb_search_text = initial_result.stderr or initial_result.stdout
        kb_entry = self._kb_scan(stack, kb_search_text)
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
                self.kb.save(stack, kb_entry.get("error_type", "kb_hit"), kb_entry.get("keywords", []), kb_cmd, "kb")
                return RepairResult(repaired=True, source="kb", fix_command=kb_cmd,
                                    diagnosis=None, execution_results=all_results,
                                    repair_attempts=all_attempts)

        # 3. Diagnose with repo context
        diagnosis = self._diagnose(step, initial_result)
        _info(f"Diagnosi: [{diagnosis.error_type}] {diagnosis.description}")

        # 4. Ollama multi-turn loop
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

        # 5. DeepSeek API (cheap cloud AI)
        repo_context = {
            "root": str(getattr(self.analysis, "root", "")),
            "manifests": getattr(self.analysis, "top_level_manifests", []),
            "missing_deps": getattr(self.analysis, "missing_system_deps", []),
        }
        deepseek_cmd = repair_with_deepseek(
            stack=stack,
            error=initial_result.stderr or initial_result.stdout,
            step_command=step.command,
            repo_context=repo_context,
        )
        if deepseek_cmd:
            _info(f"DeepSeek suggereix: {deepseek_cmd}")
            ds_result, ds_success = self._run_repair_cmd(deepseek_cmd, step, len(all_attempts) + 1)
            all_results.append(ds_result)
            all_attempts.append({"attempt": len(all_attempts) + 1, "command": deepseek_cmd,
                                  "returncode": ds_result.returncode,
                                  "stderr_tail": _tail(ds_result.stderr, 5),
                                  "result": ds_result, "success": ds_success})
            if ds_success:
                self.kb.save(stack, diagnosis.error_type, diagnosis.keywords,
                             deepseek_cmd, "deepseek")
                return RepairResult(repaired=True, source="deepseek", fix_command=deepseek_cmd,
                                    diagnosis=diagnosis, execution_results=all_results,
                                    repair_attempts=all_attempts)

        # 6. Anthropic API fallback (últim recurs)
        anthropic_cmd = repair_with_anthropic(
            step=step,
            prior_attempts=ollama_attempts,
            stack=stack,
            kb_md=kb_md,
            system_prompt_fn=self._build_system_prompt,
        )
        if anthropic_cmd:
            _info(f"Anthropic suggereix: {anthropic_cmd}")
            ant_result, ant_success = self._run_repair_cmd(anthropic_cmd, step, len(all_attempts) + 1)
            all_results.append(ant_result)
            all_attempts.append({"attempt": len(all_attempts) + 1, "command": anthropic_cmd,
                                  "returncode": ant_result.returncode,
                                  "stderr_tail": _tail(ant_result.stderr, 5),
                                  "result": ant_result, "success": ant_success})
            if ant_success:
                self.kb.save(stack, diagnosis.error_type, diagnosis.keywords,
                             anthropic_cmd, "anthropic")
                return RepairResult(repaired=True, source="anthropic", fix_command=anthropic_cmd,
                                    diagnosis=diagnosis, execution_results=all_results,
                                    repair_attempts=all_attempts)

        # 7. All failed — escalate via ErrorReporter
        self._escalate(step, diagnosis, all_attempts, initial_result)

        return RepairResult(repaired=False, source="none", fix_command=None,
                            diagnosis=diagnosis, execution_results=all_results,
                            repair_attempts=all_attempts)

    def _escalate(self, step: Any, diagnosis: Diagnosis,
                  attempts: List[Dict[str, Any]], initial_result: Any) -> None:
        try:
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
