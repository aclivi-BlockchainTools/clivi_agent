#!/usr/bin/env python3
"""Test unitari per a agents/error_reporter.py"""
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agents.error_reporter import ErrorReport, ErrorReporter

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        print(f"  ✅ {name}")
        PASS += 1
    else:
        print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
        FAIL += 1


# ── Dades sintètiques ─────────────────────────────────────────────────────────

@dataclass
class FakeStepError:
    step_id: str = "install-deps"
    step_title: str = "Install dependencies"
    command: str = "pip install -r requirements.txt"
    cwd: str = "/tmp/fake-repo"
    returncode: int = 1
    stdout_tail: str = ""
    stderr_tail: str = (
        "Collecting opencv-python\n"
        "  ERROR: Could not find a version that satisfies the requirement cv2\n"
        "ModuleNotFoundError: No module named 'cv2'\n"
    )
    diagnosis: str = "[missing_dependency] opencv-python no trobat al sistema"
    repaired: bool = False


REPAIR_ATTEMPTS = [
    {
        "attempt": 1,
        "command": "pip install --user -r requirements.txt",
        "returncode": 1,
        "stderr_tail": "ModuleNotFoundError: No module named 'cv2'\n",
    },
    {
        "attempt": 2,
        "command": "apt-get install -y python3-opencv",
        "returncode": 1,
        "stderr_tail": "E: Permission denied. Are you root?\n",
    },
]


def make_fake_repo(tmp_dir: Path) -> Path:
    repo = tmp_dir / "fake-repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text(
        "flask==2.3.0\nopencv-python==4.8.0\nnumpy>=1.24\nrequests\n"
    )
    (repo / "app.py").write_text("import cv2\nprint('hello')\n")
    (repo / "README.md").write_text("# Fake repo\n")
    subdir = repo / "utils"
    subdir.mkdir()
    (subdir / "helpers.py").write_text("")
    return repo


# ── Tests ─────────────────────────────────────────────────────────────────────

print("\n=== test_error_reporter.py ===\n")

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    repo_root = make_fake_repo(tmp_path)
    escalation_dir = tmp_path / "escalations"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    step_error = FakeStepError()
    reporter = ErrorReporter(workspace=workspace, escalation_dir=escalation_dir)

    print("1. generate() — estructura del report")
    report = reporter.generate(
        step_error=step_error,
        repair_attempts=REPAIR_ATTEMPTS,
        repo_root=repo_root,
        repo_name="fake-repo",
        stack_name="python",
        missing_deps=["opencv-python"],
        full_stderr=(
            "Collecting packages...\n"
            "ERROR: Could not find a version that satisfies the requirement cv2\n"
            "ModuleNotFoundError: No module named 'cv2'\n"
        ),
    )

    check("report és ErrorReport", isinstance(report, ErrorReport))
    check("escalation_id 8 chars", len(report.escalation_id) == 8)
    check("timestamp format", len(report.timestamp) == 15)
    check("repo_name correcte", report.repo_name == "fake-repo")
    check("stack_name", report.stack_name == "python")
    check("missing_deps", report.missing_deps == ["opencv-python"])
    check("failed_step.command", report.failed_step["command"] == step_error.command)
    check("failed_step.returncode", report.failed_step["returncode"] == 1)
    check("error_summary no buit", bool(report.error_summary))
    check("error_summary conté step title", "Install dependencies" in report.error_summary)
    check("diagnosis preservat", report.diagnosis == step_error.diagnosis)
    check("repair_attempts count", len(report.repair_attempts) == 2)
    check("repair attempt 1 command", report.repair_attempts[0]["command"] == REPAIR_ATTEMPTS[0]["command"])
    check("repair attempt 2 returncode", report.repair_attempts[1]["returncode"] == 1)

    print("\n2. repo_tree i deps_preview")
    check("repo_tree no buit", bool(report.repo_tree))
    check("deps_preview conté requirements.txt", "requirements.txt" in report.deps_preview)
    check("deps_preview conté opencv", "opencv" in report.deps_preview)

    print("\n3. claude_code_prompt — contingut")
    prompt = report.claude_code_prompt
    check("prompt conté repo_name", "fake-repo" in prompt)
    check("prompt conté stack", "python" in prompt)
    check("prompt conté missing_deps", "opencv-python" in prompt)
    check("prompt conté command", step_error.command in prompt)
    check("prompt conté stderr", "cv2" in prompt)
    check("prompt conté intent 1", REPAIR_ATTEMPTS[0]["command"] in prompt)
    check("prompt conté intent 2", REPAIR_ATTEMPTS[1]["command"] in prompt)
    check("prompt conté pregunta concreta", "Com puc fer" in prompt)
    check("prompt conté causa del diagnòstic", "missing_dependency" in prompt)
    check("prompt conté deps_preview", "flask" in prompt)

    print("\n4. save_and_print() — fitxer JSON")
    saved_path = reporter.save_and_print(report)
    check("fitxer existeix", saved_path.exists())
    check("fitxer a escalation_dir", saved_path.parent == escalation_dir)

    perms = oct(os.stat(saved_path).st_mode)[-3:]
    check("permisos 600", perms == "600", f"perms={perms}")

    with open(saved_path) as f:
        data = json.load(f)
    check("JSON parsejagle", isinstance(data, dict))
    check("JSON té claude_code_prompt", bool(data.get("claude_code_prompt")))
    check("JSON té repair_attempts", len(data.get("repair_attempts", [])) == 2)
    check("JSON té stack_name", data.get("stack_name") == "python")
    check("JSON té missing_deps", data.get("missing_deps") == ["opencv-python"])
    check("nom fitxer conté escalation_id", report.escalation_id in saved_path.name)

    print("\n5. format_for_bartolo()")
    bartolo_out = reporter.format_for_bartolo(data)
    check("output conté ❌", "❌" in bartolo_out)
    check("output conté step title", "Install dependencies" in bartolo_out)
    check("output conté prompt markdown", "```" in bartolo_out)

    print("\n6. Graceful fallback — repair_attempts buit")
    step2 = FakeStepError(step_title="Run server", command="python app.py", returncode=127)
    report2 = reporter.generate(
        step_error=step2,
        repair_attempts=[],
        repo_root=repo_root,
        repo_name="bare-repo",
        stack_name="",
        missing_deps=[],
    )
    check("report sense repairs és vàlid", isinstance(report2, ErrorReport))
    check("prompt sense repairs menciona 'cap'", "cap" in report2.claude_code_prompt.lower())

# ── Resum ─────────────────────────────────────────────────────────────────────

print(f"\n{'─'*40}")
print(f"Resultat: {PASS} ✅  {FAIL} ❌  (de {PASS + FAIL})")
if FAIL:
    sys.exit(1)
