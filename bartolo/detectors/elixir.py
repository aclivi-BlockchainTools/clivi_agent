"""Detector de projectes Elixir/Phoenix."""

from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import detect_ports_from_text, read_text


def detect_elixir_service(path: Path) -> Optional[ServiceInfo]:
    mix_exs = path / "mix.exs"
    if not mix_exs.exists():
        return None
    try:
        text = read_text(mix_exs).lower()
    except Exception:
        text = ""
    fw = "phoenix" if "phoenix" in text else "elixir"
    ports = detect_ports_from_text(text)
    run_url = f"http://localhost:{ports[0]}" if ports else "http://localhost:4000" if fw == "phoenix" else None
    return ServiceInfo(name=path.name, path=str(path), service_type="elixir", framework=fw,
                       entry_hints=["mix phx.server" if fw == "phoenix" else "mix run --no-halt"],
                       manifests=["mix.exs"], ports_hint=ports, confidence=0.75, run_url=run_url)
