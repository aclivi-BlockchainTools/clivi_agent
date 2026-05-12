"""Funcions compartides per al descobriment de candidats:
classificació de repo, detecció de llibreries, monorepo workspace expansion."""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from bartolo.types import ServiceInfo

SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "target", ".agent_logs", ".next", "out",
    "__tests__", "__mocks__", "__fixtures__",
    "tests", "test", "spec", "specs",
    "fixtures", "mocks", "__snapshots__",
    "e2e", "cypress", "playwright",
}

EXAMPLE_DIRS = {"examples", "example", "demo", "demos", "samples", "sample", "tutorials", "tutorial", "docs", "documentation"}

MAX_CANDIDATES = 60

_COLLECTION_README_PATTERNS = re.compile(
    r"^#\s*Awesome\s|A curated list of|##\s*Table of Contents|##\s*Contents",
    re.IGNORECASE | re.MULTILINE,
)

_TOOL_REPO_NAMES: set[str] = {
    "turborepo", "turbo", "lerna", "nx", "deno", "phoenix",
}

_TOOL_MARKER_FILES: set[str] = {
    "turbo.json", "pnpm-workspace.yaml", "lerna.json",
}

_RUNNABLE_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "go.mod",
    "Cargo.toml", "mix.exs", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "Gemfile", "Makefile", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "compose.yml",
    "deno.json", "deno.jsonc",
}

_TEST_FILE_PATTERNS = (
    ".test.", ".spec.", "_test.", "_spec.", "test.", "spec.",
    ".fixture.", ".mock.", ".snap.",
)


def read_text(path: Path, max_chars: int = 60000) -> str:
    """Llegeix un fitxer de text fins a max_chars caracters."""
    try:
        content = path.read_text(errors="ignore")
        return content[:max_chars] if len(content) > max_chars else content
    except Exception:
        return ""


def _read_port_from_env_example(path: Path) -> Optional[int]:
    """Llegeix el port d'un .env.example si existeix."""
    for env_name in (".env.example", ".env.sample", ".env"):
        env_file = path / env_name
        if env_file.exists():
            try:
                text = env_file.read_text(errors="ignore")[:2000]
                for line in text.split("\n"):
                    if "PORT" in line.upper() and "=" in line:
                        match = re.search(r"PORT\s*=\s*(\d{4,5})", line, re.IGNORECASE)
                        if match:
                            return int(match.group(1))
            except Exception:
                pass
    return None


def detect_ports_from_text(text: str) -> List[int]:
    """Detecta ports mencionats en text (codi, config, etc.)."""
    ports: List[int] = []
    for m in re.finditer(r'\b([1-9]\d{3,4})\b', text):
        port = int(m.group(1))
        if port not in ports:
            ports.append(port)
    return ports


def is_node_library(pkg_data: dict) -> bool:
    """Detecta si un package.json correspon a una llibreria/tool Node, no una app arrencable.

    Puntuació basada en camps estàtics del manifest (sense llegir codi font):
      +2  "files"          — declara subset npm-publish; apps no necessiten això
      +1  "peerDependencies" no buit — plugins/extensors; apps rarament ho declaren
      +1  "exports"        — mapa ESM explícit; apps rarament el declaren
      +1  "publishConfig"  — configura el registre npm → es publica → és una lib
      +1  cap script runnable (start/dev/serve/preview) → no té punt d'arrencada
      -1  "private": true  → no es publica → probablement app o arrel de monorepo

    Llindar: score >= 2 → és una llibreria (retorna None al detector).
    """
    score = 0
    if "files" in pkg_data:
        score += 2
    if pkg_data.get("peerDependencies"):
        score += 1
    if "exports" in pkg_data:
        score += 1
    if "publishConfig" in pkg_data:
        score += 1
    scripts = pkg_data.get("scripts", {})
    if not any(k in scripts for k in ("start", "dev", "serve", "preview")):
        score += 1
    if pkg_data.get("private"):
        score -= 1
    return score >= 2


def is_library_package_root(root: Path) -> bool:
    """Detecta si el root del repo és una llibreria Python (no una app)."""
    if (root / "setup.py").exists():
        text = read_text(root / "setup.py", max_chars=5000)
        if "setup(" in text and any(kw in text for kw in ["packages=", "find_packages", "name="]):
            return True
    if (root / "pyproject.toml").exists():
        text = read_text(root / "pyproject.toml", max_chars=5000)
        if "[project]" in text or "[tool.poetry]" in text:
            return True
    return False


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


def classify_repo_type(root: Path) -> str:
    """Classifica el repositori abans d'escanejar serveis.

    Retorna: 'collection', 'documentation', 'tool', 'library', 'monorepo', 'unknown', 'application'
    """
    name = root.name.lower()
    readme = root / "README.md"
    readme_text = read_text(readme, max_chars=3000) if readme.exists() else ""

    if name.startswith("awesome-") or (readme_text and _COLLECTION_README_PATTERNS.search(readme_text)):
        return "collection"

    top_files = list(root.glob("*"))
    top_manifests = [m for m in _RUNNABLE_MANIFESTS if (root / m).exists()]
    sub_manifests: List[Path] = []
    for d in root.iterdir():
        if d.is_dir() and d.name not in SKIP_DIRS:
            for m in _RUNNABLE_MANIFESTS:
                if (d / m).exists():
                    sub_manifests.append(d / m)
            for sd in d.iterdir():
                if sd.is_dir() and sd.name not in SKIP_DIRS:
                    for m in _RUNNABLE_MANIFESTS:
                        if (sd / m).exists():
                            sub_manifests.append(sd / m)
    has_runnable = bool(top_manifests) or bool(sub_manifests)
    md_count = sum(1 for f in top_files if f.suffix == ".md")
    if not has_runnable and md_count >= 5:
        return "documentation"

    if name in _TOOL_REPO_NAMES:
        return "tool"
    tool_markers = any((root / m).exists() for m in _TOOL_MARKER_FILES)
    other_markers = any((root / m).exists() for m in _RUNNABLE_MANIFESTS if m not in _TOOL_MARKER_FILES)
    if tool_markers and not other_markers:
        return "tool"

    if is_library_package_root(root):
        return "library"
    pkg = root / "package.json"
    other_runnable = any((root / m).exists() for m in _RUNNABLE_MANIFESTS if m != "package.json")
    if pkg.exists() and not other_runnable:
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            if is_node_library(data):
                return "library"
        except Exception:
            pass

    if detect_monorepo_tool(root):
        return "monorepo"

    if not has_runnable:
        return "unknown"

    return "application"


def _parse_pnpm_workspace_packages(root: Path) -> List[str]:
    """Extreu la llista de globs de packages d'un pnpm-workspace.yaml."""
    ws = root / "pnpm-workspace.yaml"
    if not ws.exists():
        return []
    globs: List[str] = []
    in_packages = False
    for line in ws.read_text().splitlines():
        stripped = line.strip()
        if re.match(r'^packages\s*:', stripped):
            in_packages = True
            continue
        if in_packages:
            m = re.match(r'\s*[-*]\s+["\']?([^"\'\s#]+)', line)
            if m:
                globs.append(m.group(1))
            elif stripped and not stripped.startswith('#') and not stripped.startswith('-'):
                if not line.startswith('  ') and not line.startswith('\t'):
                    break
    return globs


def _expand_workspace_globs(root: Path, globs: List[str]) -> Set[Path]:
    """Expandeix globs de workspace a un set de directoris concrets existents."""
    dirs: Set[Path] = set()
    for g in globs:
        if g.startswith('!'):
            continue
        if '/' not in g:
            p = root / g
            if p.is_dir():
                dirs.add(p)
        elif g.endswith('/*'):
            parent = root / g[:-2]
            if parent.is_dir():
                dirs.add(parent)
                for child in parent.iterdir():
                    if child.is_dir() and child.name not in SKIP_DIRS:
                        dirs.add(child)
        elif '*' in g:
            idx = g.index('*')
            prefix = g[:idx].rstrip('/')
            suffix = g[idx+1:].lstrip('/')
            parent = root / prefix
            if parent.is_dir():
                for child in parent.iterdir():
                    if child.is_dir() and child.name not in SKIP_DIRS:
                        target = child / suffix if suffix else child
                        if target.is_dir():
                            dirs.add(target)
        elif '/' in g:
            p = root / g
            if p.is_dir():
                dirs.add(p)
    return dirs


def _get_monorepo_workspace_dirs(root: Path) -> Optional[Set[Path]]:
    """Calcula el set de directoris permesos per a un monorepo."""
    globs = _parse_pnpm_workspace_packages(root)
    if not globs:
        pkg = root / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(errors="ignore"))
                ws = data.get("workspaces")
                if isinstance(ws, list) and ws:
                    globs = [str(w) for w in ws]
            except Exception:
                pass
    if not globs:
        lerna = root / "lerna.json"
        if lerna.exists():
            try:
                data = json.loads(lerna.read_text(errors="ignore"))
                pkgs = data.get("packages")
                if isinstance(pkgs, list) and pkgs:
                    globs = [str(p) for p in pkgs]
            except Exception:
                pass
    if not globs:
        return None
    dirs = _expand_workspace_globs(root, globs)
    dirs.add(root)
    return dirs


def _is_test_or_fixture_file(filename: str) -> bool:
    return any(pat in filename for pat in _TEST_FILE_PATTERNS)


def discover_candidate_dirs(root: Path) -> List[Path]:
    manifest_files = {"package.json", "requirements.txt", "pyproject.toml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "Makefile", "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts", "turbo.json", "nx.json", "pnpm-workspace.yaml", "lerna.json", "deno.json", "deno.jsonc", "mix.exs"}
    is_library = is_library_package_root(root)
    is_monorepo = detect_monorepo_tool(root) is not None
    allowed_dirs = _get_monorepo_workspace_dirs(root) if is_monorepo else None
    candidates: List[Path] = [root]
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if is_library:
            rel = Path(current_root).relative_to(root)
            if rel.parts and rel.parts[0] in EXAMPLE_DIRS:
                dirs[:] = []
                continue
        if is_monorepo:
            cur = Path(current_root)
            if allowed_dirs is not None:
                if cur not in allowed_dirs:
                    is_ancestor = False
                    cur_s = str(cur) + os.sep
                    for ad in allowed_dirs:
                        if str(ad).startswith(cur_s):
                            is_ancestor = True
                            break
                    if not is_ancestor:
                        dirs[:] = []
                elif cur != root:
                    cur_s = str(cur) + os.sep
                    has_children = any(str(ad).startswith(cur_s) for ad in allowed_dirs if ad != cur)
                    if not has_children:
                        dirs[:] = []
            else:
                depth = len(Path(current_root).relative_to(root).parts)
                if depth >= 2:
                    dirs[:] = []
        if any(f in manifest_files for f in files):
            if Path(current_root) not in candidates:
                candidates.append(Path(current_root))
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates
