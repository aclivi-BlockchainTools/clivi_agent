"""Detector de projectes Java (Maven, Gradle, Spring)."""

from pathlib import Path
from typing import Optional

from bartolo.types import ServiceInfo


def detect_java_service(path: Path) -> Optional[ServiceInfo]:
    pom = path / "pom.xml"
    gradle = path / "build.gradle"
    gradk = path / "build.gradle.kts"
    if not pom.exists() and not gradle.exists() and not gradk.exists():
        return None
    manifests = [pom.name] if pom.exists() else [gradle.name if gradle.exists() else gradk.name]
    entry_hint = "mvn spring-boot:run" if pom.exists() else "./gradlew bootRun"
    return ServiceInfo(name=path.name, path=str(path), service_type="java", framework="spring",
                       entry_hints=[entry_hint], manifests=manifests, ports_hint=[8080],
                       confidence=0.7, run_url="http://localhost:8080")
