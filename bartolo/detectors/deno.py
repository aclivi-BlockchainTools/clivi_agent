"""Detector de projectes Deno."""

import re
from pathlib import Path
from typing import List, Optional

from bartolo.types import ServiceInfo
from bartolo.detectors.discovery import detect_ports_from_text, read_text


def detect_deno_service(path: Path) -> Optional[ServiceInfo]:
    deno_json = path / "deno.json"
    deno_jsonc = path / "deno.jsonc"
    import_map = path / "import_map.json"
    has_manifest = deno_json.exists() or deno_jsonc.exists()
    manifests: List[str] = []
    if deno_json.exists():
        manifests.append("deno.json")
    if deno_jsonc.exists():
        manifests.append("deno.jsonc")
    if import_map.exists():
        manifests.append("import_map.json")
    if not has_manifest:
        ts_files = list(path.glob("*.ts")) + list(path.glob("*.js"))
        deno_imports = False
        for f in ts_files[:10]:
            try:
                content = f.read_text(errors="ignore")[:2000]
                if re.search(r'\bfrom\s+["\'](?:npm:|jsr:|https?://deno\.land/)', content):
                    deno_imports = True
                    break
            except Exception:
                pass
        if not deno_imports:
            return None
    text = ""
    try:
        if has_manifest:
            text = read_text(deno_json if deno_json.exists() else deno_jsonc)
        else:
            for f in ts_files[:5]:
                try:
                    text = f.read_text(errors="ignore")[:3000]
                    if re.search(r'\b(?:PORT|port|listen)\s*[:=]\s*\d{4,5}', text):
                        break
                except Exception:
                    pass
    except Exception:
        pass
    ports = detect_ports_from_text(text)
    run_url = f"http://localhost:{ports[0]}" if ports else "http://localhost:8001"
    entry_hints = ["deno run -A main.ts", "deno task start"]
    if not has_manifest:
        for candidate in ("server.ts", "main.ts", "index.ts", "app.ts", "mod.ts"):
            if (path / candidate).exists():
                entry_hints[0] = f"deno run -A {candidate}"
                break
    return ServiceInfo(name=path.name, path=str(path), service_type="deno", framework="deno",
                       entry_hints=entry_hints, manifests=manifests,
                       ports_hint=ports, confidence=0.65 if has_manifest else 0.4,
                       run_url=run_url)
