#!/usr/bin/env python3
"""Fix Streamlit run-step generation in universal_repo_agent_v5.py.
Amplia la llista d'entry points i afegeix fallback a *.py arrel.
Idempotent. Crea backup .bak_streamlit_fix.
"""
import shutil
import sys
from pathlib import Path

AGENT = Path.home() / "universal-agent" / "universal_repo_agent_v5.py"
MARKER = "# v2.4 streamlit fix:"

OLD_BLOCK = (
    '    if svc.framework == "streamlit":\n'
    '        for e in ["app.py", "main.py", "streamlit_app.py"]:\n'
    '            if (path / e).exists():\n'
    '                return f".venv/bin/streamlit run {e} --server.port {port} --server.address 0.0.0.0 --server.headless true"\n'
)

NEW_BLOCK = (
    '    if svc.framework == "streamlit":\n'
    '        # v2.4 streamlit fix: ampliada llista d\'entries + fallback *.py arrel\n'
    '        candidates = [\n'
    '            "streamlit_app.py", "Hello.py", "Home.py", "app.py", "main.py",\n'
    '            "Main.py", "App.py", "streamlit_main.py", "streamlit.py",\n'
    '        ]\n'
    '        chosen = None\n'
    '        for e in candidates:\n'
    '            if (path / e).exists():\n'
    '                chosen = e\n'
    '                break\n'
    '        if not chosen:\n'
    '            roots = sorted([\n'
    '                p.name for p in path.glob("*.py")\n'
    '                if not p.name.lower().startswith(("test_", "conftest", "setup"))\n'
    '                and p.name.lower() != "__init__.py"\n'
    '            ])\n'
    '            if roots:\n'
    '                chosen = roots[0]\n'
    '        if chosen:\n'
    '            return f".venv/bin/streamlit run {chosen} --server.port {port} --server.address 0.0.0.0 --server.headless true"\n'
)


def main():
    if not AGENT.exists():
        print("[ERR] No trobat:", AGENT); sys.exit(1)
    src = AGENT.read_text(encoding="utf-8")
    if MARKER in src:
        print("[OK] Ja aplicat. Res a fer."); return
    if OLD_BLOCK not in src:
        print("[ERR] No trobat ancoratge OLD_BLOCK. Potser el fitxer ja ha canviat.")
        sys.exit(2)
    bak = AGENT.with_suffix(".py.bak_streamlit_fix")
    shutil.copy2(AGENT, bak)
    print("[OK] Backup:", bak)
    new_src = src.replace(OLD_BLOCK, NEW_BLOCK, 1)
    AGENT.write_text(new_src, encoding="utf-8")
    print("[OK] Pegat aplicat a:", AGENT)


if __name__ == "__main__":
    main()
