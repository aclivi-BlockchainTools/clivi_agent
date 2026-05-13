"""bartolo/dashboard/shell_routes.py — Shell exec amb token de seguretat."""

from __future__ import annotations

import secrets
import subprocess
import time
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from urllib.parse import parse_qs
import asyncio

from universal_repo_agent_v5 import DEFAULT_WORKSPACE  # type: ignore

router = APIRouter()
_TOKENS: dict = {}
_TOKEN_TTL = 120


@router.post("/api/exec")
async def exec_generate(request: Request):
    body = await request.body()
    params = parse_qs(body.decode("utf-8"))
    cmd = params.get("cmd", [""])[0].strip()
    if not cmd:
        return {"error": "cmd required"}
    token = secrets.token_hex(4)
    _TOKENS[token] = (time.time() + _TOKEN_TTL, cmd)
    return {"token": token, "expires_in": _TOKEN_TTL}


@router.post("/api/exec/confirm")
async def exec_confirm(request: Request):
    body = await request.body()
    params = parse_qs(body.decode("utf-8"))
    token = params.get("token", [""])[0].strip()
    cmd = params.get("cmd", [""])[0].strip()
    if not token or token not in _TOKENS:
        return {"error": "token invalid o caducat"}
    expiry, stored_cmd = _TOKENS[token]
    if time.time() > expiry:
        del _TOKENS[token]
        return {"error": "token caducat"}
    if cmd != stored_cmd:
        return {"error": "cmd no coincideix amb el token"}
    del _TOKENS[token]
    try:
        result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30, cwd=str(DEFAULT_WORKSPACE))
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[returncode: {result.returncode}]"
        return {"output": output, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "timeout (30s)"}
    except Exception as e:
        return {"error": str(e)}


@router.websocket("/ws/shell")
async def websocket_shell(ws: WebSocket):
    await ws.accept()
    shell_history: list[str] = []
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd", "").strip()
            if not cmd:
                continue
            if not shell_history or shell_history[-1] != cmd:
                shell_history.append(cmd)
                if len(shell_history) > 100:
                    shell_history = shell_history[-100:]
            await ws.send_json({"type": "start", "cmd": cmd})
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(DEFAULT_WORKSPACE),
                )
                try:
                    while True:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                        if not line:
                            break
                        await ws.send_json(
                            {"type": "output", "line": line.decode("utf-8", errors="replace").rstrip("\n")}
                        )
                except asyncio.TimeoutError:
                    proc.kill()
                    await ws.send_json({"type": "output", "line": "[timeout 30s]"})
                await proc.wait()
                await ws.send_json(
                    {"type": "done", "returncode": proc.returncode, "history": shell_history}
                )
            except Exception as e:
                await ws.send_json({"type": "error", "error": str(e)})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
