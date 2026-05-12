"""Detector de projectes .NET (csproj, fsproj, sln)."""

from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import detect_ports_from_text, read_text


def detect_dotnet_service(path: Path) -> Optional[ServiceInfo]:
    csproj = list(path.glob("*.csproj"))
    fsproj = list(path.glob("*.fsproj"))
    sln = list(path.glob("*.sln"))
    if not csproj and not fsproj and not sln:
        return None
    manifests = [p.name for p in csproj + fsproj + sln]
    project_file = (csproj or fsproj)[0] if (csproj or fsproj) else None
    text = ""
    if project_file:
        try:
            text = read_text(project_file).lower()
        except Exception:
            pass
    is_web = any(kw in text for kw in ("microsoft.aspnetcore", "web", 'sdk="microsoft.net.sdk.web"'))
    fw = "aspnet" if is_web else "dotnet"
    ports = detect_ports_from_text(text)
    run_url = f"http://localhost:{ports[0]}" if ports else "http://localhost:5000" if is_web else None
    return ServiceInfo(name=path.name, path=str(path), service_type="dotnet", framework=fw,
                       entry_hints=["dotnet run", "dotnet watch run"],
                       manifests=manifests, ports_hint=ports, confidence=0.7, run_url=run_url)
