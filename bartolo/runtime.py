"""Detecció de versions de runtime requerides pel repo."""

import json
from pathlib import Path
from typing import Dict, List, Tuple

from bartolo.shell import run_check_version

_RUNTIME_VERSION_FILES = {
    ".python-version": "python3",
    ".nvmrc": "node",
    ".node-version": "node",
}

_RUNTIME_CHECK_TOOLS: Dict[str, str] = {}  # s'inicialitza lazy per evitar import circular


def parse_version(version_str: str) -> Tuple[int, ...]:
    v = version_str.strip().lstrip("vV").lstrip("go").strip()
    v = v.lstrip("^~>=<").strip()
    parts = v.replace("-", ".").replace("_", ".").split(".")[:3]
    nums: List[int] = []
    for p in parts:
        try:
            nums.append(int(p.split("+")[0]))
        except ValueError:
            break
    return tuple(nums) if nums else ()


def read_runtime_versions(root: Path) -> Dict[str, str]:
    constraints: Dict[str, str] = {}
    for filename, tool in _RUNTIME_VERSION_FILES.items():
        f = root / filename
        if f.is_file():
            v = f.read_text().strip().split("\n")[0].split("#")[0].strip()
            if v:
                constraints[tool] = v
    for f in (root / ".go-version",):
        if f.is_file():
            v = f.read_text().strip().split("\n")[0].strip()
            if v:
                constraints["go"] = v
    go_mod = root / "go.mod"
    if go_mod.is_file():
        first = go_mod.read_text().split("\n")[0].strip()
        if first.startswith("module ") or first.startswith("go "):
            for line in go_mod.read_text().split("\n")[:5]:
                line = line.strip()
                if line.startswith("go "):
                    constraints["go"] = line[3:].strip()
                    break
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            engines = data.get("engines", {})
            if isinstance(engines, dict):
                if engines.get("node"):
                    constraints["node"] = str(engines["node"])
                if engines.get("pnpm"):
                    constraints["pnpm"] = str(engines["pnpm"])
        except Exception:
            pass
    asdf = root / ".tool-versions"
    if asdf.is_file():
        for line in asdf.read_text().splitlines()[:20]:
            parts = line.strip().split()
            if len(parts) >= 2:
                tool = parts[0]
                version = parts[1]
                if tool in ("python", "python3"):
                    constraints.setdefault("python3", version)
                elif tool == "nodejs":
                    constraints.setdefault("node", version)
                elif tool in ("golang", "go"):
                    constraints.setdefault("go", version)
                elif tool not in constraints:
                    constraints[tool] = version
    return constraints


def check_runtime_versions(constraints: Dict[str, str]) -> List[str]:
    if not _RUNTIME_CHECK_TOOLS:
        # Inicialització lazy per evitar import circular amb preflight
        from bartolo.preflight import SYSTEM_DEPS
        _RUNTIME_CHECK_TOOLS.update({
            "python3": SYSTEM_DEPS["python3"]["check"] if "python3" in SYSTEM_DEPS else "python3 --version",
            "node": SYSTEM_DEPS.get("node", {}).get("check", "node --version"),
            "go": SYSTEM_DEPS.get("go", {}).get("check", "go version"),
            "pnpm": SYSTEM_DEPS.get("pnpm", {}).get("check", "pnpm --version"),
            "ruby": SYSTEM_DEPS.get("ruby", {}).get("check", "ruby --version"),
        })
    warnings: List[str] = []
    for tool, constraint in constraints.items():
        check_cmd = _RUNTIME_CHECK_TOOLS.get(tool)
        if not check_cmd:
            continue
        actual = run_check_version(check_cmd)
        if not actual:
            warnings.append(f"{tool}: requereix {constraint}, pero no s'ha pogut detectar la versio instal·lada")
            continue
        req = parse_version(constraint)
        cur = parse_version(actual)
        if not req or not cur:
            continue
        if cur < req:
            warnings.append(f"{tool}: requereix {constraint}, instal·lat {actual}")
    return warnings
