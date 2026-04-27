"""
ErrorReporter — genera informes estructurats d'errors no reparats
i els guarda per facilitar l'escalació a Claude Code.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class ErrorReport:
    escalation_id: str
    timestamp: str
    repo_name: str
    stack_name: str
    missing_deps: List[str]
    failed_step: dict        # {title, command, cwd, returncode}
    error_summary: str
    diagnosis: str
    repair_attempts: List[dict]  # [{attempt, command, returncode, stderr_tail}]
    repo_tree: str
    deps_preview: str
    claude_code_prompt: str


class ErrorReporter:
    DEFAULT_ESCALATION_DIR = Path.home() / ".universal-agent" / "escalations"

    def __init__(self, workspace: Path, escalation_dir: Optional[Path] = None):
        self.workspace = workspace
        self.escalation_dir = escalation_dir or self.DEFAULT_ESCALATION_DIR

    def generate(
        self,
        step_error,
        repair_attempts: list,
        repo_root: Path,
        repo_name: str,
        stack_name: str = "",
        missing_deps: Optional[List[str]] = None,
        full_stderr: str = "",
    ) -> ErrorReport:
        repo_tree = self._get_repo_tree(repo_root)
        deps_preview = self._get_deps_preview(repo_root)
        stderr_for_prompt = full_stderr or step_error.stderr_tail

        report = ErrorReport(
            escalation_id=uuid.uuid4().hex[:8],
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
            repo_name=repo_name,
            stack_name=stack_name,
            missing_deps=list(missing_deps or []),
            failed_step={
                "title": step_error.step_title,
                "command": step_error.command,
                "cwd": step_error.cwd,
                "returncode": step_error.returncode,
            },
            error_summary=self._build_summary(step_error, stderr_for_prompt),
            diagnosis=step_error.diagnosis,
            repair_attempts=[
                {
                    "attempt": r["attempt"],
                    "command": r["command"],
                    "returncode": r["returncode"],
                    "stderr_tail": r["stderr_tail"],
                }
                for r in repair_attempts
            ],
            repo_tree=repo_tree,
            deps_preview=deps_preview,
            claude_code_prompt="",
        )
        report.claude_code_prompt = self._build_claude_prompt(report, stderr_for_prompt)
        return report

    def _build_summary(self, step_error, full_stderr: str = "") -> str:
        stderr = full_stderr or step_error.stderr_tail
        last_line = next(
            (l.strip() for l in reversed(stderr.strip().splitlines()) if l.strip()),
            "Error desconegut",
        )
        return (
            f"El step '{step_error.step_title}' ha fallat amb codi {step_error.returncode}. "
            f"Error principal: {last_line[:120]}"
        )

    def _get_repo_tree(self, repo_root: Path) -> str:
        try:
            r = subprocess.run(
                ["tree", "-L", "2", "--gitignore",
                 "-I", "node_modules|.venv|__pycache__|.git|*.pyc|dist|build"],
                cwd=repo_root, capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        try:
            r = subprocess.run(
                ["find", ".", "-maxdepth", "2",
                 "-not", "-path", "*/node_modules/*",
                 "-not", "-path", "*/.venv/*",
                 "-not", "-path", "*/__pycache__/*",
                 "-not", "-path", "*/.git/*"],
                cwd=repo_root, capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                lines = sorted(r.stdout.strip().splitlines())
                return "\n".join(lines[:60])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return "(no s'ha pogut obtenir l'estructura del repo)"

    def _get_deps_preview(self, repo_root: Path) -> str:
        candidates = [
            "requirements.txt", "package.json", "Pipfile",
            "pyproject.toml", "Gemfile", "go.mod",
        ]
        for fname in candidates:
            fpath = repo_root / fname
            if fpath.exists():
                try:
                    lines = fpath.read_text(errors="replace").splitlines()
                    preview = "\n".join(lines[:6])
                    return f"--- {fname} (primeres línies) ---\n{preview}"
                except Exception:
                    continue
        return ""

    def _build_claude_prompt(self, report: ErrorReport, full_stderr: str) -> str:
        parts: List[str] = []

        parts.append(
            f"Context: l'agent universal ha fallat desplegant el repo `{report.repo_name}`."
        )
        if report.stack_name:
            parts.append(f"Stack detectat: {report.stack_name}")
        if report.missing_deps:
            parts.append(
                f"Dependencies del sistema detectades com a absents: "
                f"{', '.join(report.missing_deps)}"
            )
        parts.append("")
        parts.append(f"**Step fallit**: {report.failed_step['title']}")
        parts.append(f"**Comanda**: `{report.failed_step['command']}`")
        parts.append(f"**CWD**: `{report.failed_step['cwd']}`")
        parts.append(f"**Returncode**: {report.failed_step['returncode']}")
        parts.append("")

        stderr_lines = full_stderr.strip().splitlines()
        relevant = [l for l in stderr_lines if l.strip()][-20:]
        parts.append("**Stderr (últimes 20 línies rellevants)**:")
        parts.append("```")
        parts.extend(relevant)
        parts.append("```")

        if report.repair_attempts:
            parts.append("")
            n = len(report.repair_attempts)
            parts.append(f"**Intents de reparació automàtica ({n})**:")
            for r in report.repair_attempts:
                parts.append(f"  {r['attempt']}. `{r['command']}`")
                if r["stderr_tail"].strip():
                    last_err = next(
                        (l.strip() for l in reversed(r["stderr_tail"].splitlines()) if l.strip()),
                        "",
                    )
                    if last_err:
                        parts.append(f"     → {last_err[:100]}")
        else:
            parts.append("")
            parts.append(
                "**Intents de reparació automàtica**: cap "
                "(l'agent no ha pogut suggerir cap fix)"
            )

        if report.deps_preview:
            parts.append("")
            parts.append(report.deps_preview)

        if report.diagnosis:
            parts.append("")
            parts.append(f"**Diagnòstic de l'agent (Qwen)**: {report.diagnosis}")

        cause = "error desconegut"
        if report.diagnosis and "]" in report.diagnosis:
            cause = report.diagnosis.split("]")[0].strip("[")

        parts.append("")
        parts.append("**Pregunta concreta**:")
        parts.append(
            f"Com puc fer que l'agent detecti i resolgui automàticament aquest tipus "
            f"d'error ({cause}) en el futur, idealment sense intervenció manual?"
        )

        return "\n".join(parts)

    def save_and_print(self, report: ErrorReport) -> Path:
        self.escalation_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in report.repo_name)[:20]
        fname = f"{report.timestamp}_{report.escalation_id}_{safe_name}.json"
        fpath = self.escalation_dir / fname

        data = {
            "escalation_id": report.escalation_id,
            "timestamp": report.timestamp,
            "repo_name": report.repo_name,
            "stack_name": report.stack_name,
            "missing_deps": report.missing_deps,
            "failed_step": report.failed_step,
            "error_summary": report.error_summary,
            "diagnosis": report.diagnosis,
            "repair_attempts": report.repair_attempts,
            "repo_tree": report.repo_tree,
            "deps_preview": report.deps_preview,
            "claude_code_prompt": report.claude_code_prompt,
        }
        fpath.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        os.chmod(fpath, 0o600)

        n = len(report.repair_attempts)
        sep = "─" * 60
        print(f"\n{sep}")
        print("❌ No he pogut arreglar l'error automàticament.")
        print()
        print(f"**Step fallit**: {report.failed_step['title']} ({report.failed_step['command']})")
        print(f"**Error**: {report.error_summary}")
        print(f"**Intentat**: {n} reparació{'ns' if n != 1 else ''}")
        print(f"**Diagnòstic Qwen**: {report.diagnosis}")
        print()
        print("**Per escalar a Claude Code**, copia aquest prompt:")
        print("─" * 40)
        print(report.claude_code_prompt)
        print("─" * 40)
        print(f"[Escalació guardada: {fpath}]")
        print(f"__ESCALATION_REPORT__={fpath}")
        return fpath

    def format_for_bartolo(self, report_dict: dict) -> str:
        n = len(report_dict.get("repair_attempts", []))
        step = report_dict.get("failed_step", {})
        return (
            f"❌ No he pogut arreglar l'error automàticament.\n\n"
            f"**Step fallit**: {step.get('title', '?')} "
            f"(`{step.get('command', '?')}`)\n"
            f"**Error**: {report_dict.get('error_summary', '')}\n"
            f"**Intentat**: {n} reparació{'ns' if n != 1 else ''}\n"
            f"**Diagnòstic Qwen**: {report_dict.get('diagnosis', '')}\n\n"
            f"**Per escalar a Claude Code**, copia aquest prompt:\n"
            f"```\n{report_dict.get('claude_code_prompt', '')}\n```"
        )
