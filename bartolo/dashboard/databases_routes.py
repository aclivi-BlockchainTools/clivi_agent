"""bartolo/dashboard/databases_routes.py — Containers Docker."""

from __future__ import annotations

import re
import subprocess
from fastapi import APIRouter

router = APIRouter()


def _guess_connect_url(name: str, ports: str) -> str:
    port_map = {"postgres": "5432", "postgresql": "5432", "mongodb": "27017", "mongo": "27017",
                "redis": "6379", "mysql": "3306", "mariadb": "3306"}
    for db_type, default_port in port_map.items():
        if db_type in name.lower():
            m = re.search(r'0\.0\.0\.0:(\d+)', ports)
            host_port = m.group(1) if m else default_port
            return f"{db_type}://localhost:{host_port}"
    return ""


@router.get("/api/databases")
async def get_databases():
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=agent-", "--format", "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"],
            capture_output=True, text=True, timeout=5
        )
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                containers.append({
                    "name": parts[0], "image": parts[1], "status": parts[2], "ports": parts[3],
                    "connect_url": _guess_connect_url(parts[0], parts[3]),
                })
        return {"containers": containers, "docker_available": True}
    except Exception:
        return {"containers": [], "docker_available": False}
