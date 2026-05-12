"""Detector de projectes PHP (Laravel, Symfony)."""

from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import read_text


def detect_php_service(path: Path) -> Optional[ServiceInfo]:
    if not (path / "composer.json").exists():
        return None
    text = read_text(path / "composer.json").lower()
    fw = "laravel" if "laravel" in text else "symfony" if "symfony" in text else "php"
    return ServiceInfo(name=path.name, path=str(path), service_type="php", framework=fw,
                       entry_hints=["php artisan serve", "php -S localhost:8000"],
                       manifests=["composer.json"], ports_hint=[8000], confidence=0.7,
                       run_url="http://localhost:8000")
