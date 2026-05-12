"""Detector de projectes Docker (Dockerfile, docker-compose)."""

from pathlib import Path
from typing import List, Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import detect_ports_from_text, read_text


def detect_docker_service(path: Path) -> Optional[ServiceInfo]:
    compose_candidates = [path / "docker-compose.yml", path / "docker-compose.yaml", path / "compose.yml"]
    compose_path = next((p for p in compose_candidates if p.exists()), None)
    dockerfile = path / "Dockerfile"
    if not compose_path and not dockerfile.exists():
        return None
    manifests: List[str] = []
    entry_hints: List[str] = []
    ports_hint: List[int] = []
    confidence = 0.75
    if compose_path:
        manifests.append(compose_path.name)
        entry_hints.append("docker compose up")
        confidence += 0.1
        ports_hint = detect_ports_from_text(read_text(compose_path))
    if dockerfile.exists():
        manifests.append("Dockerfile")
        entry_hints.append("docker build")
    run_url = f"http://localhost:{ports_hint[0]}" if ports_hint else None
    return ServiceInfo(name=path.name, path=str(path), service_type="docker", framework="docker", entry_hints=entry_hints, manifests=manifests, ports_hint=sorted(set(ports_hint)), confidence=min(confidence, 0.95), run_url=run_url)
