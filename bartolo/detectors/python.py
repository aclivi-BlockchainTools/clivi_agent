"""Detector de projectes Python (pip, poetry, django, flask, fastapi, streamlit)."""

from pathlib import Path
from typing import List, Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import detect_ports_from_text, read_text


def detect_python_service(path: Path) -> Optional[ServiceInfo]:
    req = path / "requirements.txt"
    pyproject = path / "pyproject.toml"
    candidates = [path / n for n in ("server.py", "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "index.py", "run.py", "api.py", "database.py", "config.py", "settings.py")]
    if not req.exists() and not pyproject.exists() and not any(p.exists() for p in candidates):
        return None
    manifests: List[str] = []
    entry_hints: List[str] = []
    text_sources: List[str] = []
    for m in (req, pyproject):
        if m.exists():
            manifests.append(m.name)
            text_sources.append(read_text(m))
    for c in candidates:
        if c.exists():
            entry_hints.append(c.name)
            text_sources.append(read_text(c))
    combined = "\n".join(text_sources).lower()
    ports = detect_ports_from_text(combined)
    if "fastapi" in combined or "uvicorn" in combined:
        fw, url, conf = "fastapi", "http://localhost:8001", 0.8
    elif "flask" in combined:
        fw, url, conf = "flask", "http://localhost:8001", 0.8
    elif "django" in combined:
        fw, url, conf = "django", "http://localhost:8001", 0.8
    elif "streamlit" in combined:
        fw, url, conf = "streamlit", "http://localhost:8501", 0.75
    else:
        fw, url, conf = "python", None, 0.65
    if ports and not url:
        url = f"http://localhost:{ports[0]}"
    return ServiceInfo(name=path.name, path=str(path), service_type="python", framework=fw, entry_hints=entry_hints, manifests=manifests, ports_hint=ports, confidence=min(conf, 0.95), run_url=url)
