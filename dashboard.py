#!/usr/bin/env python3
"""
dashboard.py — Bartolo Control Center v2.
Dashboard web complet amb FastAPI: xat, models, repos, API keys, eines, shell.

Us:
    python3 dashboard.py                 # arrenca a http://0.0.0.0:9999
    python3 dashboard.py --port 9000     # port custom
    python3 dashboard.py --workspace ... # workspace custom
    python3 dashboard.py --reload        # hot-reload (development)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Bartolo Control Center v2")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--workspace", default=str(Path.home() / "universal-agent-workspace"))
    parser.add_argument("--reload", action="store_true", help="Hot-reload (development)")
    args = parser.parse_args()

    ws = Path(args.workspace).expanduser().resolve()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".agent_logs").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("UNIVERSAL_AGENT_WORKSPACE", str(ws))

    from bartolo.dashboard import create_app
    app = create_app()

    print(f"  Bartolo Control Center v2")
    print(f"  http://{args.host}:{args.port}")
    print(f"  Workspace: {ws}")
    print(f"  Xat WebSocket: ws://{args.host}:{args.port}/ws/chat")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                reload=args.reload, reload_dirs=[str(THIS_DIR / "bartolo" / "dashboard")] if args.reload else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
