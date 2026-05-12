"""Tipus de dades compartits per tot Bartolo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ServiceInfo:
    name: str
    path: str
    service_type: str
    framework: Optional[str] = None
    entry_hints: List[str] = field(default_factory=list)
    manifests: List[str] = field(default_factory=list)
    package_manager: Optional[str] = None
    scripts: Dict[str, str] = field(default_factory=dict)
    ports_hint: List[int] = field(default_factory=list)
    confidence: float = 0.0
    run_url: Optional[str] = None
    final_run_cmd: Optional[str] = None


@dataclass
class RepoAnalysis:
    root: str
    repo_name: str
    services: List[ServiceInfo] = field(default_factory=list)
    top_level_manifests: List[str] = field(default_factory=list)
    env_files_present: List[str] = field(default_factory=list)
    env_examples_present: List[str] = field(default_factory=list)
    env_vars_needed: Dict[str, str] = field(default_factory=dict)
    likely_fullstack: bool = False
    likely_db_needed: bool = False
    db_hints: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    host_requirements: List[str] = field(default_factory=list)
    missing_system_deps: List[str] = field(default_factory=list)
    setup_scripts_found: List[str] = field(default_factory=list)
    readme_instructions: List[str] = field(default_factory=list)
    db_provisioned: List[str] = field(default_factory=list)
    cloud_services: List[str] = field(default_factory=list)
    runtime_version_warnings: List[str] = field(default_factory=list)
    monorepo_tool: Optional[str] = None
    repo_type: str = "application"


@dataclass
class CommandStep:
    id: str
    title: str
    cwd: str
    command: str
    expected_outcome: str
    critical: bool = True
    category: str = "run"
    verify_url: Optional[str] = None
    verify_port: Optional[int] = None


@dataclass
class ExecutionPlan:
    summary: str
    steps: List[CommandStep] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class StepError:
    step_id: str
    step_title: str
    command: str
    cwd: str
    returncode: int
    stdout_tail: str
    stderr_tail: str
    diagnosis: str = ""
    repaired: bool = False


@dataclass
class ExecutionResult:
    step_id: str
    command: str
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    started_at: float
    finished_at: float
    repaired: bool = False


@dataclass
class SmokeResult:
    name: str
    success: bool
    detail: str
