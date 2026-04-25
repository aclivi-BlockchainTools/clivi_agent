#!/usr/bin/env python3
"""Patch agent_http_bridge.py v2.3: afegeix rutes /exec_shell, /exec_shell/confirm, POST /upload."""
import shutil
import sys
from pathlib import Path

BRIDGE = Path.home() / "universal-agent" / "agent_http_bridge.py"
MARKER = "# === v2.3 routes ==="

ANCHOR_POST_HEADER = (
    '    def do_POST(self) -> None:\n'
    '        if not self._auth_ok():\n'
    '            self._json(401, {"error": "unauthorized"}); return\n'
)

UPLOAD_INTERCEPT = (
    '    def do_POST(self) -> None:\n'
    '        if not self._auth_ok():\n'
    '            self._json(401, {"error": "unauthorized"}); return\n'
    '        # === v2.3 routes === (multipart intercept)\n'
    '        if urlparse(self.path).path == "/upload":\n'
    '            self._handle_upload_post(); return\n'
)

ANCHOR_TAIL = (
    '        elif parsed.path == "/refresh":\n'
    '            repo = str(body.get("repo", "")).strip()\n'
    '            if not repo:\n'
    '                self._json(400, {"error": "missing \'repo\'"}); return\n'
    '            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--refresh", repo], timeout=60))\n'
    '        else:\n'
    '            self._json(404, {"error": "not found"})\n'
)

NEW_ELIFS = (
    '        elif parsed.path == "/refresh":\n'
    '            repo = str(body.get("repo", "")).strip()\n'
    '            if not repo:\n'
    '                self._json(400, {"error": "missing \'repo\'"}); return\n'
    '            self._json(200, _run_agent(["--workspace", str(WORKSPACE), "--refresh", repo], timeout=60))\n'
    '        elif parsed.path == "/exec_shell":\n'
    '            cmd = str(body.get("cmd", "")).strip()\n'
    '            if not cmd:\n'
    '                self._json(400, {"error": "missing \'cmd\'"}); return\n'
    '            if not _shell_safe(cmd):\n'
    '                self._json(403, {"error": "command blocked by safety filter"}); return\n'
    '            tok = _shell_register(cmd)\n'
    '            self._json(200, {"status": "pending_confirmation", "token": tok, "cmd": cmd,\n'
    '                             "expires_in": _SHELL_TOKEN_TTL,\n'
    '                             "hint": "POST /exec_shell/confirm amb {\\"token\\": tok}"})\n'
    '        elif parsed.path == "/exec_shell/confirm":\n'
    '            tok = str(body.get("token", "")).strip()\n'
    '            if not tok:\n'
    '                self._json(400, {"error": "missing \'token\'"}); return\n'
    '            cmd = _shell_consume(tok)\n'
    '            if cmd is None:\n'
    '                self._json(400, {"error": "invalid or expired token"}); return\n'
    '            try:\n'
    '                timeout = int(body.get("timeout", 60))\n'
    '            except Exception:\n'
    '                timeout = 60\n'
    '            self._json(200, _shell_execute(cmd, timeout=timeout))\n'
    '        else:\n'
    '            self._json(404, {"error": "not found"})\n'
)

UPLOAD_METHOD = '''
    def _handle_upload_post(self):
        try:
            import cgi
            ctype = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ctype:
                self._json(400, {"error": "expected multipart/form-data"}); return
            form = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype},
            )
            if "file" not in form:
                self._json(400, {"error": "missing 'file' field"}); return
            item = form["file"]
            import os as _os23
            fname = _os23.path.basename(item.filename or "")
            if not fname.lower().endswith(".zip"):
                self._json(400, {"error": "only .zip files accepted"}); return
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOAD_DIR / fname
            data = item.file.read()
            dest.write_bytes(data)
            self._json(200, {"status": "uploaded", "path": str(dest), "size": len(data),
                             "hint": "POST /run/async amb input=" + str(dest)})
        except Exception as e:
            self._json(500, {"error": "upload failed: " + str(e)})
'''


def main():
    if not BRIDGE.exists():
        print("[ERR] No trobat:", BRIDGE); sys.exit(1)
    src = BRIDGE.read_text(encoding="utf-8")
    if MARKER in src:
        print("[OK] Ja aplicat. Res a fer."); return

    if ANCHOR_POST_HEADER not in src:
        print("[ERR] No trobat ancoratge do_POST header"); sys.exit(2)
    if ANCHOR_TAIL not in src:
        print("[ERR] No trobat ancoratge tail (refresh+else)"); sys.exit(3)

    bak = BRIDGE.with_suffix(".py.bak_v23b")
    shutil.copy2(BRIDGE, bak)
    print("[OK] Backup:", bak)

    new_src = src.replace(ANCHOR_POST_HEADER, UPLOAD_INTERCEPT, 1)
    new_src = new_src.replace(ANCHOR_TAIL, NEW_ELIFS, 1)
    insert_at = new_src.find("    def do_GET(self) -> None:")
    if insert_at == -1:
        print("[ERR] No trobat do_GET"); sys.exit(4)
    new_src = new_src[:insert_at] + UPLOAD_METHOD.lstrip("\n") + "\n" + new_src[insert_at:]

    BRIDGE.write_text(new_src, encoding="utf-8")
    print("[OK] Pegat aplicat a:", BRIDGE)
    print("[OK] Reinicia el bridge ara.")


if __name__ == "__main__":
    main()
