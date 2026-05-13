"""bartolo/dashboard/tools_routes.py — Gestió d'eines OpenWebUI + model params."""

from __future__ import annotations

import json
import subprocess
from fastapi import APIRouter, HTTPException

router = APIRouter()

MODEL_ID = "bartolo"


def _db_query(query: str, params: tuple = ()) -> list:
    """Execute SQL query on OpenWebUI database, return list of sqlite3.Row."""
    import sqlite3
    conn = sqlite3.connect("/dev/shm/openwebui.db")
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def _sync_db():
    """Copy webui.db from container to shared memory so we can read it from host."""
    subprocess.run(
        ["docker", "cp", "open-webui:/app/backend/data/webui.db", "/dev/shm/openwebui.db"],
        capture_output=True, text=True, timeout=10
    )


def _write_back():
    """Copy modified DB back to container."""
    subprocess.run(
        ["docker", "cp", "/dev/shm/openwebui.db", "open-webui:/app/backend/data/webui.db"],
        capture_output=True, text=True, timeout=10
    )


# ── Tools ──────────────────────────────────────────────────────────


@router.get("/api/tools")
async def list_tools():
    _sync_db()
    try:
        rows = _db_query("SELECT id, name, content, specs, meta FROM tool")
        # Get active tool IDs from model
        model_row = _db_query("SELECT meta FROM model WHERE id=?", (MODEL_ID,))
        active_tool_ids = []
        if model_row:
            meta = json.loads(model_row[0]["meta"] or "{}")
            active_tool_ids = meta.get("toolIds", [])

        tools = []
        for r in rows:
            meta = json.loads(r["meta"] or "{}")
            specs = json.loads(r["specs"] or "[]")
            functions = []
            if isinstance(specs, list):
                for s in specs:
                    functions.append({
                        "name": s.get("name", "?"),
                        "description": s.get("description", "")[:200],
                        "parameters": list(s.get("parameters", {}).get("properties", {}).keys()),
                    })
            tools.append({
                "id": r["id"],
                "name": r["name"],
                "description": meta.get("description", ""),
                "functions": functions,
                "function_count": len(functions),
                "is_active": r["id"] in active_tool_ids,
                "content_length": len(r["content"] or ""),
                "specs_count": len(specs) if isinstance(specs, list) else 0,
            })
        return {"tools": tools, "count": len(tools), "active_tool_ids": active_tool_ids}
    except Exception as e:
        return {"tools": [], "count": 0, "error": str(e)}


@router.get("/api/tools/{tool_id}/source")
async def get_tool_source(tool_id: str):
    _sync_db()
    try:
        rows = _db_query("SELECT name, content, specs, meta FROM tool WHERE id=?", (tool_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Tool not found")
        r = rows[0]
        return {
            "id": tool_id,
            "name": r["name"],
            "source": r["content"] or "",
            "specs": json.loads(r["specs"] or "[]"),
            "meta": json.loads(r["meta"] or "{}"),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"id": tool_id, "error": str(e)}


@router.put("/api/tools/{tool_id}/source")
async def update_tool_source(tool_id: str, body: dict):
    source = body.get("source", "")
    if not source:
        return {"ok": False, "error": "source required"}

    _sync_db()
    import sqlite3
    conn = sqlite3.connect("/dev/shm/openwebui.db")
    try:
        conn.execute("UPDATE tool SET content=?, updated_at=strftime('%s','now') WHERE id=?",
                     (source, tool_id))
        conn.commit()
    finally:
        conn.close()
    _write_back()

    return {"ok": True, "message": f"Tool {tool_id} actualitzada. Reinicia OpenWebUI per aplicar."}


@router.post("/api/tools/{tool_id}/toggle")
async def toggle_tool(tool_id: str):
    _sync_db()
    import sqlite3
    conn = sqlite3.connect("/dev/shm/openwebui.db")
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT meta FROM model WHERE id=?", (MODEL_ID,)).fetchone()
        if not row:
            return {"ok": False, "error": "Model Bartolo no trobat"}

        meta = json.loads(row["meta"] or "{}")
        tool_ids = meta.get("toolIds", [])

        if tool_id in tool_ids:
            tool_ids.remove(tool_id)
            status = "desactivat"
        else:
            tool_ids.append(tool_id)
            status = "activat"

        meta["toolIds"] = tool_ids
        conn.execute("UPDATE model SET meta=?, updated_at=strftime('%s','now') WHERE id=?",
                     (json.dumps(meta, ensure_ascii=False), MODEL_ID))
        conn.commit()
    finally:
        conn.close()
    _write_back()

    return {"ok": True, "tool_id": tool_id, "status": status, "active_tool_ids": tool_ids}


# ── Model ──────────────────────────────────────────────────────────


@router.get("/api/model/bartolo")
async def get_model():
    _sync_db()
    try:
        rows = _db_query("SELECT id, name, base_model_id, params, meta, is_active FROM model WHERE id=?", (MODEL_ID,))
        if not rows:
            raise HTTPException(status_code=404, detail="Model not found")
        r = rows[0]
        params = json.loads(r["params"] or "{}")
        meta = json.loads(r["meta"] or "{}")
        return {
            "id": r["id"],
            "name": r["name"],
            "base_model_id": r["base_model_id"],
            "is_active": bool(r["is_active"]),
            "system_prompt": params.get("system", ""),
            "params": {k: v for k, v in params.items() if k != "system"},
            "capabilities": meta.get("capabilities", {}),
            "tool_ids": meta.get("toolIds", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@router.put("/api/model/bartolo")
async def update_model(body: dict):
    _sync_db()
    import sqlite3
    conn = sqlite3.connect("/dev/shm/openwebui.db")
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT params FROM model WHERE id=?", (MODEL_ID,)).fetchone()
        if not row:
            return {"ok": False, "error": "Model Bartolo no trobat"}

        params = json.loads(row["params"] or "{}")

        if "system_prompt" in body:
            params["system"] = body["system_prompt"]
        if "temperature" in body:
            params["temperature"] = body["temperature"]
        if "num_predict" in body:
            params["num_predict"] = body["num_predict"]
        if "top_p" in body:
            params["top_p"] = body["top_p"]

        conn.execute("UPDATE model SET params=?, updated_at=strftime('%s','now') WHERE id=?",
                     (json.dumps(params, ensure_ascii=False), MODEL_ID))
        conn.commit()
    finally:
        conn.close()
    _write_back()

    return {"ok": True, "message": "Model actualitzat. Reinicia OpenWebUI per aplicar."}
