"""Detector de projectes Makefile."""

import re
from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import read_text


def detect_makefile_service(path: Path) -> Optional[ServiceInfo]:
    makefile = path / "Makefile"
    if not makefile.exists():
        return None
    targets = re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]+)\s*:", read_text(makefile), re.MULTILINE)
    useful = [t for t in targets if t in {"run", "start", "dev", "serve", "up", "build", "install", "all", "setup"}]
    return ServiceInfo(name=path.name, path=str(path), service_type="make", framework="make",
                       entry_hints=useful or targets[:5], manifests=["Makefile"],
                       ports_hint=[], confidence=0.6)
