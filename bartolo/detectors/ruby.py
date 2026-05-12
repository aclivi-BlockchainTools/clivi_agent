"""Detector de projectes Ruby (Rails, Sinatra)."""

from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import read_text


def detect_ruby_service(path: Path) -> Optional[ServiceInfo]:
    if not (path / "Gemfile").exists():
        return None
    text = read_text(path / "Gemfile").lower()
    fw = "rails" if "rails" in text else "sinatra" if "sinatra" in text else "ruby"
    url = "http://localhost:3000" if fw in {"rails", "sinatra"} else None
    ports_hint = [3000] if fw in {"rails", "sinatra"} else []
    return ServiceInfo(name=path.name, path=str(path), service_type="ruby", framework=fw,
                       entry_hints=["bundle exec rails server", "bundle exec ruby"],
                       manifests=["Gemfile"], ports_hint=ports_hint, confidence=0.7, run_url=url)
