"""Smoke tests adaptatius per verificar que els serveis arrencats responen."""

import os
from typing import Any, Dict, List, Optional

from bartolo.types import RepoAnalysis, SmokeResult
from bartolo.shell import verify_http


def _framework_endpoints(svc) -> List[str]:
    """Retorna endpoints canònics segons el framework del servei."""
    fw = (svc.framework or "").lower()
    if fw == "fastapi":
        return ["/docs", "/openapi.json", "/"]
    if fw == "spring":
        return ["/actuator/health", "/"]
    if fw in ("flask", "aspnet"):
        return ["/health", "/"]
    if fw == "express":
        return ["/health", "/api", "/"]
    if fw == "django":
        return ["/admin/", "/api/", "/"]
    if fw == "phoenix":
        return ["/", "/api"]
    if fw == "rails":
        return ["/up", "/health", "/"]
    if fw == "next":
        return ["/", "/api/health"]
    return ["/"]


def run_smoke_tests(emergent: Optional[Dict[str, Any]], analysis: RepoAnalysis, timeout: int = 10) -> List[SmokeResult]:
    results: List[SmokeResult] = []
    tested_urls: set = set()
    if emergent:
        be_path = emergent.get("backend")
        fe_path = emergent.get("frontend")
        svc_by_path = {os.path.realpath(svc.path): svc for svc in analysis.services}
        backend = svc_by_path.get(os.path.realpath(be_path)) if be_path else None
        frontend = svc_by_path.get(os.path.realpath(fe_path)) if fe_path else None
        # Fallback: match by name if path lookup failed
        if not backend:
            for svc in analysis.services:
                if svc.name == "backend":
                    backend = svc
                    break
        if not frontend:
            for svc in analysis.services:
                if svc.name == "frontend":
                    frontend = svc
                    break
        if backend and backend.run_url and backend.run_url not in tested_urls:
            tested_urls.add(backend.run_url)
            for ep in _framework_endpoints(backend):
                url = backend.run_url.rstrip("/") + ep
                if verify_http(url, timeout=timeout):
                    results.append(SmokeResult(name=f"{backend.name} ({ep})", success=True, detail=f"{url} → OK"))
                    break
            else:
                results.append(SmokeResult(name=backend.name, success=False, detail=f"{backend.run_url} → no respon"))
        if frontend and frontend.run_url and frontend.run_url not in tested_urls:
            tested_urls.add(frontend.run_url)
            for ep in _framework_endpoints(frontend):
                url = frontend.run_url.rstrip("/") + ep
                if verify_http(url, timeout=timeout):
                    results.append(SmokeResult(name=f"{frontend.name} ({ep})", success=True, detail=f"{url} → OK"))
                    break
            else:
                results.append(SmokeResult(name=frontend.name, success=False, detail=f"{frontend.run_url} → no respon"))
        return results
    for svc in analysis.services:
        if not svc.run_url or svc.run_url in tested_urls:
            continue
        tested_urls.add(svc.run_url)
        for ep in _framework_endpoints(svc):
            url = svc.run_url.rstrip("/") + ep
            if verify_http(url, timeout=timeout):
                results.append(SmokeResult(name=f"{svc.name} ({ep})", success=True, detail=f"{url} → OK"))
                break
        else:
            results.append(SmokeResult(name=svc.name, success=False, detail=f"{svc.run_url} → no respon"))
    return results


def print_smoke_report(results: List[SmokeResult]) -> None:
    if not results:
        return
    print("\n--- Smoke Tests ---")
    for r in results:
        icon = "✅" if r.success else "❌"
        print(f"  {icon} {r.detail}")
