"""bartolo/repair/fallback.py — Plan B fallbacks per errors comuns."""

from __future__ import annotations

from typing import Dict, List

from bartolo.types import CommandStep, ExecutionResult

_FALLBACK_MAP: Dict[str, List[str]] = {
    "pnpm install": ["npm install", "npm install --legacy-peer-deps"],
    "pnpm dev": ["npm run dev"],
    "pnpm start": ["npm start"],
    "pnpm build": ["npm run build"],
    "go mod download": ["go version", "go env GOPATH"],
    "yarn install": ["npm install", "npm install --legacy-peer-deps"],
    "yarn dev": ["npm run dev"],
    "yarn start": ["npm start"],
    "pip install -r requirements.txt": ["pip install --break-system-packages -r requirements.txt"],
}


def _get_fallbacks(step: CommandStep, result: ExecutionResult) -> List[str]:
    if step.command in _FALLBACK_MAP:
        return _FALLBACK_MAP[step.command]
    for k, v in _FALLBACK_MAP.items():
        if step.command.startswith(k):
            return v
    if result.returncode == 127 and step.command.startswith("pnpm"):
        return ["npm install", "npm install --legacy-peer-deps"]
    if result.returncode == 127 and step.command.startswith("yarn"):
        return ["npm install"]
    return []
