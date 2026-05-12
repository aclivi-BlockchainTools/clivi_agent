"""Detector de projectes Rust."""

from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo


def detect_rust_service(path: Path) -> Optional[ServiceInfo]:
    if not (path / "Cargo.toml").exists():
        return None
    return ServiceInfo(name=path.name, path=str(path), service_type="rust", framework="rust",
                       entry_hints=["cargo run", "cargo build --release"],
                       manifests=["Cargo.toml"], ports_hint=[8080], confidence=0.75)
