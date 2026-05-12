"""Detector de projectes Node.js (npm, yarn, pnpm)."""

import json
from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import detect_ports_from_text, is_node_library, read_text, _read_port_from_env_example


def detect_node_service(path: Path) -> Optional[ServiceInfo]:
    pkg = path / "package.json"
    if not pkg.exists():
        return None
    pkg_raw = read_text(pkg)
    try:
        pkg_data = json.loads(pkg_raw)
    except Exception:
        pkg_data = {}
    if is_node_library(pkg_data):
        return None
    scripts = pkg_data.get("scripts", {})
    all_deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})} if isinstance(pkg_data, dict) else {}
    dep_names = set(all_deps.keys())
    ports_hint = detect_ports_from_text(pkg_raw)
    if "next" in dep_names:
        framework, run_url = "next", "http://localhost:3000"
    elif "vite" in dep_names:
        framework, run_url = "vite", "http://localhost:5173"
    elif "react" in dep_names:
        framework, run_url = "react", "http://localhost:3000"
    elif "express" in dep_names:
        framework, run_url = "express", "http://localhost:3000"
    else:
        framework, run_url = "node", None
    pm = "pnpm" if (path / "pnpm-lock.yaml").exists() else "yarn" if (path / "yarn.lock").exists() else "npm"
    env_port = _read_port_from_env_example(path)
    if env_port:
        run_url = f"http://localhost:{env_port}"
    elif ports_hint and not run_url:
        run_url = f"http://localhost:{ports_hint[0]}"
    confidence = 0.7 + (0.1 if "dev" in scripts else 0) + (0.1 if "start" in scripts else 0)
    return ServiceInfo(name=path.name, path=str(path), service_type="node", framework=framework, entry_hints=list(scripts.keys()), manifests=["package.json"], package_manager=pm, scripts=scripts, ports_hint=sorted(set(ports_hint)), confidence=min(confidence, 0.95), run_url=run_url)
