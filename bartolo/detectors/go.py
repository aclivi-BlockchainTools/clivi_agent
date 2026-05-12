"""Detector de projectes Go."""

from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import detect_ports_from_text


def detect_go_service(path: Path) -> Optional[ServiceInfo]:
    go_mod = path / "go.mod"
    if not go_mod.exists():
        return None
    port = 8080
    go_files = list(path.glob("*.go")) + list(path.glob("*/*.go"))[:5]
    for gf in go_files:
        try:
            text = gf.read_text(errors="ignore")[:4000]
            ports = detect_ports_from_text(text)
            if ports:
                port = ports[0]
                break
        except Exception:
            pass
    for env_name in (".env.example", ".env.sample", ".env"):
        env_file = path / env_name
        if env_file.exists():
            try:
                ports = detect_ports_from_text(env_file.read_text(errors="ignore")[:2000])
                if ports:
                    port = ports[0]
                    break
            except Exception:
                pass
    return ServiceInfo(name=path.name, path=str(path), service_type="go", framework="go",
                       entry_hints=["go run ./...", "go build"], manifests=["go.mod"],
                       ports_hint=[port], confidence=0.75, run_url=f"http://localhost:{port}")
