"""bartolo/dashboard/databases_routes.py — Containers Docker."""

from __future__ import annotations

import re
import subprocess
from fastapi import APIRouter

router = APIRouter()


def _guess_connect_url(name: str, ports: str) -> tuple:
    m = re.search(r'0\.0\.0\.0:(\d+)', ports)
    host_port = m.group(1) if m else ""
    container_name = name.lower()
    if "postgres" in container_name:
        port = host_port or "5432"
        return (
            f"postgresql://agentuser:agentpass@localhost:{port}/agentdb",
            f"docker exec -it {name} psql -U agentuser -d agentdb",
        )
    if "mongo" in container_name:
        port = host_port or "27017"
        return (f"mongodb://localhost:{port}", f"docker exec -it {name} mongosh")
    if "mysql" in container_name or "mariadb" in container_name:
        port = host_port or "3306"
        return (
            f"mysql://agentuser:agentpass@localhost:{port}/agentdb",
            f"docker exec -it {name} mysql -u agentuser -pagentpass agentdb",
        )
    if "redis" in container_name:
        port = host_port or "6379"
        return (f"redis://localhost:{port}", f"docker exec -it {name} redis-cli")
    return ("", "")


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
                url, cmd = _guess_connect_url(parts[0], parts[3])
                containers.append({
                    "name": parts[0], "image": parts[1], "status": parts[2], "ports": parts[3],
                    "connect_url": url, "connect_cmd": cmd,
                })
        return {"containers": containers, "docker_available": True}
    except Exception:
        return {"containers": [], "docker_available": False}
