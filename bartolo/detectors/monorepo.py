"""Detector de monorepo tools (turbo, nx, lerna, pnpm workspaces)."""

import json
from pathlib import Path
from typing import Optional


def detect_monorepo_tool(path: Path) -> Optional[str]:
    """Detecta si el repo usa eines de monorepo (turbo, nx, workspaces, lerna)."""
    if (path / "turbo.json").exists():
        return "turborepo"
    if (path / "nx.json").exists():
        return "nx"
    if (path / "pnpm-workspace.yaml").exists():
        return "pnpm-workspace"
    if (path / "lerna.json").exists():
        return "lerna"
    pkg = path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            if isinstance(data.get("workspaces"), list) and data["workspaces"]:
                return "npm-workspaces"
        except Exception:
            pass
    return None
