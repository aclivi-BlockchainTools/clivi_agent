"""Registre de detectors de stack.

Cada detector exporta una funció `detect(path: Path) -> Optional[ServiceInfo]`.
Afegir un nou stack és tan simple com crear un fitxer aquí i registrar-lo a ALL_DETECTORS.
"""

from pathlib import Path
from typing import List, Optional, Set

from bartolo.detectors.node import detect_node_service
from bartolo.detectors.python import detect_python_service
from bartolo.detectors.docker import detect_docker_service
from bartolo.detectors.go import detect_go_service
from bartolo.detectors.rust import detect_rust_service
from bartolo.detectors.ruby import detect_ruby_service
from bartolo.detectors.php import detect_php_service
from bartolo.detectors.java import detect_java_service
from bartolo.detectors.makefile import detect_makefile_service
from bartolo.detectors.monorepo import detect_monorepo_tool
from bartolo.detectors.deno import detect_deno_service
from bartolo.detectors.elixir import detect_elixir_service
from bartolo.detectors.dotnet import detect_dotnet_service

from bartolo.detectors.discovery import (
    discover_candidate_dirs,
    classify_repo_type,
    is_library_package_root,
    is_node_library,
    SKIP_DIRS,
    EXAMPLE_DIRS,
    MAX_CANDIDATES,
)

ALL_DETECTORS = [
    detect_node_service,
    detect_python_service,
    detect_docker_service,
    detect_go_service,
    detect_rust_service,
    detect_ruby_service,
    detect_php_service,
    detect_java_service,
    detect_makefile_service,
    detect_deno_service,
    detect_elixir_service,
    detect_dotnet_service,
]
