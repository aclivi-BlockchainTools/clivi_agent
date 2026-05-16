"""bartolo/dashboard/chat.py — WebSocket xat amb Ollama streaming + router dispatch."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bartolo.llm import OLLAMA_CHAT_URL, DEFAULT_MODEL
from universal_repo_agent_v5 import DEFAULT_WORKSPACE, LOG_DIRNAME  # type: ignore

router = APIRouter()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
TOOL_CALLING_MODELS = {"qwen2.5:14b", "qwen2.5:7b", "llama3.1:8b", "qwen3:8b"}


@dataclass
class PendingSecretsPrompt:
    repo_url: str
    repo_path: str
    missing_secrets: List[str] = field(default_factory=list)
    found_secrets: List[str] = field(default_factory=list)
    cloud_services: List[str] = field(default_factory=list)
    cloud_secrets_map: Dict[str, List[str]] = field(default_factory=dict)

_pending_secrets: Dict[str, PendingSecretsPrompt] = {}

@dataclass
class WizardState:
    """State machine for the interactive mount wizard (form-based steps)."""
    repo_url: str
    repo_path: str
    missing_secrets: List[str] = field(default_factory=list)
    found_secrets: List[str] = field(default_factory=list)
    cloud_services: List[str] = field(default_factory=list)
    cloud_secrets_map: Dict[str, List[str]] = field(default_factory=dict)
    third_party: dict = field(default_factory=dict)
    workspace: str = ""
    collected_secrets: Dict[str, str] = field(default_factory=dict)
    skipped_secrets: List[str] = field(default_factory=list)
    cloud_choices: Dict[str, str] = field(default_factory=dict)
    supabase_migrate: bool = False
    current_step: int = 0
    step_history: List[str] = field(default_factory=list)

_wizard_states: Dict[str, WizardState] = {}


def _analyze_repo_secrets(repo_url: str) -> dict:
    """Clona el repo, detecta vars d'entorn i serveis cloud, comprova la caché.
    Retorna dict amb missing, found, repo_path, cloud_services, cloud_secrets_map."""
    from universal_repo_agent_v5 import (
        acquire_input, detect_env_vars_from_code,
        load_secrets_cache, KNOWN_SECRET_KEYS, ensure_workspace,
        detect_third_party_services,
    )
    from bartolo.provisioner import CLOUD_TO_LOCAL

    ensure_workspace(DEFAULT_WORKSPACE)
    acquired = acquire_input(repo_url, DEFAULT_WORKSPACE)
    detected = detect_env_vars_from_code(acquired)
    cache = load_secrets_cache()

    # Also read existing .env files in the cloned repo + workspace (may have real values)
    existing_env: Dict[str, str] = {}
    # Search the cloned repo and sibling repos in the workspace
    search_roots = [acquired]
    try:
        for d in acquired.parent.iterdir():
            if d.is_dir() and d.name != acquired.name:
                search_roots.append(d)
    except Exception:
        pass
    for root_dir in search_roots[:5]:  # limit to 5 dirs max
        for env_path in root_dir.rglob(".env"):
            if any(p in env_path.parts for p in ("node_modules", ".git", "__pycache__", "venv", ".venv")):
                continue
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if v and v not in ("", "your_", "changeme", "change_me", "example", "placeholder"):
                            existing_env[k] = v
            except Exception:
                pass

    missing = []
    found = []
    for var in sorted(detected):
        if var in KNOWN_SECRET_KEYS:
            if var in cache and cache[var]:
                found.append(var)
            elif var in existing_env and existing_env[var]:
                found.append(var)
                # Also save to cache for future mounts
                cache[var] = existing_env[var]
            else:
                missing.append(var)

    if existing_env:
        from universal_repo_agent_v5 import save_secrets_cache
        save_secrets_cache(cache)

    # Detecta serveis cloud amb alternativa local
    third_party = detect_third_party_services(acquired)
    cloud_services = []
    cloud_secrets_map: Dict[str, List[str]] = {}
    for svc_key, cfg in third_party.items():
        if svc_key in CLOUD_TO_LOCAL:
            secrets_for_svc = [s for s in cfg.get("secrets", []) if s in missing]
            if secrets_for_svc:
                cloud_services.append(svc_key)
                cloud_secrets_map[svc_key] = secrets_for_svc

    return {
        "missing": missing,
        "found": found,
        "repo_path": str(acquired),
        "cloud_services": cloud_services,
        "cloud_secrets_map": cloud_secrets_map,
        "third_party": third_party,
    }


def _build_secrets_prompt_message(prompt: PendingSecretsPrompt) -> str:
    """Construeix el missatge que veu l'usuari demanant credencials o opció local."""
    lines = []
    if prompt.found_secrets:
        lines.append(f"🔐 Secrets trobats a la caché: {', '.join(prompt.found_secrets)}.")
    if prompt.missing_secrets:
        lines.append(f"⚠️ Falten secrets: {', '.join(prompt.missing_secrets)}.")
    if prompt.cloud_services:
        lines.append("")
        lines.append("☁️ Serveis cloud detectats (puc usar alternativa local):")
        from bartolo.provisioner import CLOUD_TO_LOCAL
        for svc in prompt.cloud_services:
            local = CLOUD_TO_LOCAL.get(svc, "local")
            secrets = prompt.cloud_secrets_map.get(svc, [])
            lines.append(f"  • {svc} → {local} local (Docker)")
            if secrets:
                lines.append(f"    Secrets: {', '.join(secrets)}")
            if svc == "supabase":
                lines.append("    ⚠️ Algunes funcions (Auth, Storage) requereixen Supabase cloud igualment.")
    lines.append("")
    lines.append("Respon amb:")
    lines.append('- "local" per usar base de dades local (Docker)')
    lines.append('- "cancel·la" per continuar sense credencials')
    lines.append("- O envia les credencials: CLAU=valor (una per línia)")
    return "\n".join(lines)


def _parse_secret_response(message: str) -> dict:
    """Interpreta la resposta de l'usuari: cancel·la, local, o KEY=VALUE."""
    import re
    msg_lower = message.lower().strip()
    if msg_lower in ("cancel·la", "cancel", "cancela", "skip", "salta", "no", "pass"):
        return {"cancelled": True}
    if msg_lower in ("local", "local docker", "bd local", "base de dades local",
                     "postgresql", "postgres", "docker"):
        return {"use_local": True}
    parsed = {}
    for line in message.strip().split("\n"):
        line = line.strip()
        m = re.match(r'^([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$', line)
        if m:
            parsed[m.group(1)] = m.group(2).strip()
    if parsed:
        return {"parsed": parsed}
    return {"malformed": True}


def _detect_credentials_in_message(message: str) -> dict:
    """Detect Supabase/cloud credentials pasted in chat (not necessarily in KEY=VALUE format).
    Returns parsed creds + list of recognized key names."""
    import re as _re
    from universal_repo_agent_v5 import KNOWN_SECRET_KEYS
    found = {}
    lines = message.strip().split("\n")
    # Pattern 1: KEY=VALUE (one per line or inline)
    for line in lines:
        m = _re.match(r'^([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$', line.strip())
        if m and m.group(1) in KNOWN_SECRET_KEYS:
            found[m.group(1)] = m.group(2).strip()
    # Pattern 2: KEY followed by value on next line (user's format)
    for i, line in enumerate(lines):
        line = line.strip()
        if line in KNOWN_SECRET_KEYS and i + 1 < len(lines):
            val = lines[i + 1].strip()
            # Only capture if next line looks like a value (not another key)
            if val and val not in KNOWN_SECRET_KEYS and not val.startswith("#"):
                found[line] = val
    # Pattern 3: Detect Supabase URLs and JWT tokens directly
    for line in lines:
        m = _re.search(r'(https?://[a-z]+\.supabase\.co)', line)
        if m:
            found["SUPABASE_URL"] = m.group(1)
        m = _re.search(r'(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)', line)
        if m:
            token = m.group(1)
            try:
                import base64, json as _json
                payload = token.split(".")[1]
                payload += "=" * (4 - len(payload) % 4)
                decoded = _json.loads(base64.urlsafe_b64decode(payload))
                role = decoded.get("role", "")
                if role == "anon" and "SUPABASE_ANON_KEY" not in found:
                    found["SUPABASE_ANON_KEY"] = token
                elif role == "service_role" and "SUPABASE_SERVICE_ROLE_KEY" not in found:
                    found["SUPABASE_SERVICE_ROLE_KEY"] = token
            except Exception:
                pass
    # Pattern 4: Generic env var names (KEY, TOKEN, SECRET, etc.) followed by a value line
    # Catches keys not in KNOWN_SECRET_KEYS that still look like credentials
    _cred_key_re = _re.compile(r'^[A-Z][A-Z0-9_]*(?:_(?:KEY|TOKEN|SECRET|URL|URI|PASSWORD|PASS|ID|SID))$')
    for i, line in enumerate(lines):
        line = line.strip()
        if _cred_key_re.match(line) and line not in KNOWN_SECRET_KEYS and i + 1 < len(lines):
            val = lines[i + 1].strip()
            if val and not _cred_key_re.match(val) and not val.startswith("#") and not val == line:
                # Value should look like a real credential: URL, JWT, long string
                looks_cred = bool(
                    val.startswith("http") or val.startswith("eyJ") or val.startswith("sk-") or
                    val.startswith("sb_") or val.startswith("pk_") or val.startswith("sk_") or
                    (len(val) > 20 and not " " in val)
                )
                if looks_cred:
                    found[line] = val
    return found if len(found) >= 1 else {}


async def _handle_credential_injection(ws: WebSocket, thread_id: str, creds: dict) -> None:
    """Save detected credentials, update running services, and confirm."""
    from universal_repo_agent_v5 import save_secrets_cache, load_secrets_cache
    from bartolo.executor import load_services_registry
    from bartolo.dashboard.chat_routes import persist_thread_message
    cache = load_secrets_cache()
    updated = {k: v for k, v in creds.items() if cache.get(k) != v}
    if not updated:
        await ws.send_json({"type": "done", "full_text": "Aquestes credencials ja estan guardades a la caché."})
        return
    cache.update(updated)
    save_secrets_cache(cache)
    lines = [f"🔐 {len(updated)} credencials guardades: {', '.join(updated.keys())}"]
    # Update running services' .env files
    services = load_services_registry(DEFAULT_WORKSPACE)
    import re as _re
    updated_repos = set()
    for repo_name, svcs in services.items():
        if not isinstance(svcs, list):
            continue
        for svc in svcs:
            cwd = Path(svc.get("cwd", ""))
            env_file = cwd / ".env"
            if not env_file.exists():
                continue
            env_content = env_file.read_text()
            changed = False
            for k, v in updated.items():
                import shlex
                v_quoted = shlex.quote(v)
                # Replace existing key=value
                pattern = _re.compile(rf'^{_re.escape(k)}\s*=\s*.*$', _re.MULTILINE)
                new_line = f'{k}={v_quoted}'
                if pattern.search(env_content):
                    env_content = pattern.sub(new_line, env_content)
                else:
                    env_content += f"\n{new_line}"
                changed = True
            if changed:
                env_file.write_text(env_content)
                updated_repos.add(repo_name)
    if updated_repos:
        lines.append(f"📁 .env actualitzat a: {', '.join(sorted(updated_repos))}")
        # Restart affected services so they pick up new credentials
        import os as _os, signal as _signal
        restarted = 0
        for repo_name, svcs in services.items():
            if repo_name not in updated_repos:
                continue
            if not isinstance(svcs, list):
                continue
            for svc in svcs:
                pid = svc.get("pid")
                if pid:
                    try:
                        _os.kill(pid, _signal.SIGTERM)
                    except Exception:
                        pass
                # Restart with same command
                cwd = svc.get("cwd", "")
                cmd = svc.get("command", "")
                if cwd and cmd:
                    import subprocess as _sp, threading as _th
                    log_file = Path(cwd) / ".agent_last_run.log"
                    def _restart():
                        try:
                            with log_file.open("a") as lf:
                                lf.write(f"\n--- Reiniciant per injecció de credencials ---\n")
                                lf.flush()
                                # Source .env, start process
                                env_file = Path(cwd) / ".env"
                                full_cmd = f"test -f {env_file} && set -a && . {env_file} && set +a; nohup {cmd} >> {log_file} 2>&1 &"
                                _sp.run(["bash", "-c", full_cmd], cwd=cwd, timeout=30)
                        except Exception:
                            pass
                    _th.Thread(target=_restart, daemon=True).start()
                    restarted += 1
        if restarted:
            lines.append(f"🔄 {restarted} serveis reiniciats amb les noves credencials.")
    lines.append("Per migrar dades de Supabase al PostgreSQL local, envia \"migra supabase\".")
    text = "\n".join(lines)
    persist_thread_message(thread_id, "assistant", text)
    await ws.send_json({"type": "done", "full_text": text})


def _build_access_message(repo_url: str, launch_log: Path,
                          workspace: str = None) -> str:
    """Build a completion message with actual URLs, DB info, and stop instructions."""
    import re as _re, subprocess as _sp
    from bartolo.executor import load_services_registry
    ws = Path(str(workspace or DEFAULT_WORKSPACE)).expanduser().resolve()
    services = load_services_registry(ws)
    repo_name = repo_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    lines = []
    # Case-insensitive lookup — repo_name from URL may differ from directory name
    registry_key = repo_name
    repo_services = services.get(repo_name, [])
    if not repo_services:
        for k in services:
            if k.lower() == repo_name.lower():
                registry_key = k
                repo_services = services[k]
                break
    if repo_services:
        lines.append(f"✅ **{registry_key}** desplegat:")
        for svc in repo_services:
            cmd = svc.get("command", "")
            port = None
            for m in _re.finditer(r'(?:PORT|port|--port)[= ](\d{4,5})', cmd):
                port = m.group(1)
            if not port:
                m = _re.search(r':(\d{4,5})\b', cmd.split()[-1] if cmd.split() else "")
                port = m.group(1) if m else None
            step = svc.get("step_id", "")
            if port:
                lines.append(f"• {step}: http://localhost:{port}")
            else:
                lines.append(f"• {step}: PID {svc.get('pid', '?')}")
        lines.append("")
    try:
        result = _sp.run(["docker", "ps", "--format", "{{.Names}}\\t{{.Ports}}"],
                        capture_output=True, text=True, timeout=5)
        docker_lines = result.stdout.strip().split("\n")
        db_configs = {
            "agent-postgres": ("PostgreSQL", "postgresql://agentuser:agentpass@localhost:{port}/agentdb",
                              "docker exec -it agent-postgres psql -U agentuser -d agentdb"),
            "agent-mongo": ("MongoDB", "mongodb://localhost:{port}",
                           "docker exec -it agent-mongo mongosh"),
            "agent-mysql": ("MySQL", "mysql://agentuser:agentpass@localhost:{port}/agentdb",
                           "docker exec -it agent-mysql mysql -u agentuser -pagentpass agentdb"),
            "agent-redis": ("Redis", "redis://localhost:{port}",
                           "docker exec -it agent-redis redis-cli"),
        }
        for line in docker_lines:
            if not line or "agent-" not in line:
                continue
            parts = line.split("\t")
            container = parts[0]
            ports_col = parts[1] if len(parts) > 1 else ""
            cfg = db_configs.get(container)
            if not cfg:
                continue
            label, url_tpl, connect_cmd = cfg
            m = _re.search(r':(\d+)->', ports_col)
            port = m.group(1) if m else ""
            lines.append(f"🗄️ {label}: {url_tpl.format(port=port)}")
            lines.append(f"   {connect_cmd}")
        if any(line.split("\t")[0] in db_configs for line in docker_lines):
            lines.append("")
    except Exception:
        pass
    lines.append(f"Per aturar: python3 universal_repo_agent_v5.py --stop {registry_key}")
    lines.append(f"Logs: {launch_log}")
    return "\n".join(lines)


async def _send_follow_up(ws: WebSocket, thread_id: str, text: str) -> None:
    """Send a follow-up message on the WebSocket. Safe from background threads."""
    try:
        from bartolo.dashboard.chat_routes import persist_thread_message
        persist_thread_message(thread_id, "assistant", text)
        await ws.send_json({"type": "done", "full_text": text})
    except Exception:
        pass


async def _launch_agent(ws: WebSocket, thread_id: str, repo_url: str,
                          workspace: str = None) -> None:
    """Llença l'agent universal en background i notifica al xat amb URLs i BD."""
    import subprocess, threading, asyncio as _asyncio
    agent = PROJECT_ROOT / "universal_repo_agent_v5.py"
    ws_dir = Path(str(workspace or DEFAULT_WORKSPACE)).expanduser().resolve()
    log_dir = ws_dir / LOG_DIRNAME
    log_dir.mkdir(parents=True, exist_ok=True)
    idx = len(list(log_dir.glob("dashboard-chat-launch-*")))
    launch_log = log_dir / f"dashboard-chat-launch-{idx}.log"
    loop = _asyncio.get_running_loop()
    def _launch():
        try:
            with launch_log.open("w") as f:
                cmd = [sys.executable, str(agent), "--input", repo_url, "--execute",
                       "--approve-all", "--non-interactive", "--no-readme", "--no-model-refine",
                       "--workspace", str(ws_dir)]
                f.write(f"CMD: {' '.join(cmd)}\n\n")
                f.flush()
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                               text=True, timeout=600, cwd=str(PROJECT_ROOT))
            info = _build_access_message(repo_url, launch_log, workspace=str(ws_dir))
            if info:
                _asyncio.run_coroutine_threadsafe(
                    _send_follow_up(ws, thread_id, info), loop
                )
        except subprocess.TimeoutExpired:
            with launch_log.open("a") as f:
                f.write("\n[TIMEOUT] L'agent ha excedit els 10 minuts\n")
            info = _build_access_message(repo_url, launch_log, workspace=str(ws_dir))
            if info:
                _asyncio.run_coroutine_threadsafe(
                    _send_follow_up(ws, thread_id, info), loop
                )
        except Exception as e:
            with launch_log.open("a") as f:
                f.write(f"\n[ERROR] {e}\n")
    threading.Thread(target=_launch, daemon=True).start()
    from bartolo.dashboard.chat_routes import persist_thread_message
    text = f"Muntatge de {repo_url} iniciat. T'aviso quan estigui llest amb les URLs d'accés."
    persist_thread_message(thread_id, "assistant", text)
    await ws.send_json({"type": "done", "full_text": text})


async def _handle_secret_response(ws: WebSocket, thread_id: str,
                                  prompt: PendingSecretsPrompt, parsed: dict) -> bool:
    """Processa la resposta de l'usuari a la petició de secrets.
    Retorna True si encara hi ha secrets pendents, False si s'ha resolt."""
    if parsed.get("cancelled"):
        _pending_secrets.pop(thread_id, None)
        await ws.send_json({"type": "done",
                           "full_text": "D'acord. Continuo sense secrets. Pot ser que alguns serveis no funcionin."})
        await _launch_agent(ws, thread_id, prompt.repo_url)
        return False

    if parsed.get("use_local"):
        _pending_secrets.pop(thread_id, None)
        # Save placeholder values for cloud secrets so imports don't crash
        # (e.g. supabase-py requires supabase_url at module level)
        from universal_repo_agent_v5 import save_secrets_cache, load_secrets_cache
        import secrets as _sec, uuid as _uuid
        cache = load_secrets_cache()
        placeholders: Dict[str, str] = {}
        for svc, svc_secrets in prompt.cloud_secrets_map.items():
            for s in svc_secrets:
                if s not in cache:
                    # Use a valid URL-like placeholder so SDKs that validate URL format don't crash
                    placeholders[s] = f"http://localhost:54321" if "URL" in s else f"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJsb2NhbC1wbGFjZWhvbGRlciJ9.{_uuid.uuid4().hex}"
        # Also generate random values for non-cloud missing secrets (e.g. JWT_SECRET)
        all_cloud = set()
        for v in prompt.cloud_secrets_map.values():
            all_cloud.update(v)
        for s in prompt.missing_secrets:
            if s not in cache and s not in all_cloud:
                if "SUPABASE" in s and "KEY" in s:
                    placeholders[s] = f"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJsb2NhbC1wbGFjZWhvbGRlciJ9.{_uuid.uuid4().hex}"
                else:
                    placeholders[s] = _sec.token_hex(32)
        if placeholders:
            cache.update(placeholders)
            save_secrets_cache(cache)

        local_msg = "Usaré base de dades local (PostgreSQL Docker) en lloc dels serveis cloud."
        if prompt.cloud_services:
            from bartolo.provisioner import CLOUD_TO_LOCAL
            locals_used = [f"{svc} → {CLOUD_TO_LOCAL.get(svc, 'local')}" for svc in prompt.cloud_services]
            local_msg = f"Usaré BD local: {', '.join(locals_used)}."
        if placeholders:
            local_msg += f"\n🔐 Secrets autogenerats: {', '.join(placeholders)}."
        from bartolo.dashboard.chat_routes import persist_thread_message
        persist_thread_message(thread_id, "assistant", local_msg)
        await ws.send_json({"type": "done", "full_text": local_msg})
        await _launch_agent(ws, thread_id, prompt.repo_url)
        return False

    if parsed.get("malformed"):
        retry_msg = "No he entès la resposta.\n\n" + _build_secrets_prompt_message(prompt)
        await ws.send_json({"type": "done", "full_text": retry_msg})
        return True  # still pending

    # parsed credentials
    from universal_repo_agent_v5 import save_secrets_cache, load_secrets_cache
    cache = load_secrets_cache()
    for k, v in parsed["parsed"].items():
        cache[k] = v
    save_secrets_cache(cache)

    # Re-check: queden secrets pendents?
    newly_found = [k for k in parsed["parsed"] if k in prompt.missing_secrets]
    still_missing = [s for s in prompt.missing_secrets if s not in parsed["parsed"]]
    unresolved_cloud = {}
    for svc, secrets in list(prompt.cloud_secrets_map.items()):
        unresolved = [s for s in secrets if s not in parsed["parsed"]]
        if unresolved:
            unresolved_cloud[svc] = unresolved

    if still_missing or unresolved_cloud:
        prompt.missing_secrets = still_missing
        prompt.found_secrets = prompt.found_secrets + newly_found
        prompt.cloud_secrets_map = unresolved_cloud
        prompt.cloud_services = [svc for svc in prompt.cloud_services if svc in unresolved_cloud]
        saved_msg = f"✅ Credencials desades: {', '.join(newly_found)}.\n\n"
        saved_msg += _build_secrets_prompt_message(prompt)
        await ws.send_json({"type": "done", "full_text": saved_msg})
        return True  # still pending

    _pending_secrets.pop(thread_id, None)
    await ws.send_json({"type": "done",
                       "full_text": f"✅ Totes les credencials desades ({', '.join(parsed['parsed'])}). Començo el muntatge!"})
    await _launch_agent(ws, thread_id, prompt.repo_url)
    return False


# ── Wizard functions ──────────────────────────────────────────────

def _get_current_step_name(wiz: WizardState) -> str:
    """Return the step name for the wizard's current position."""
    remaining = [s for s in wiz.missing_secrets if s not in wiz.collected_secrets and s not in wiz.skipped_secrets]
    if wiz.current_step == 0 or (wiz.current_step == 1 and not wiz.workspace):
        return "workspace"
    if remaining:
        return "secret"
    if wiz.cloud_services and not wiz.cloud_choices:
        return "cloud_choice"
    if wiz.cloud_services and "supabase" in wiz.cloud_services and not wiz.supabase_migrate and wiz.cloud_choices:
        return "supabase_migrate"
    return "confirm"


def _compute_total_steps(wiz: WizardState) -> int:
    total = 1  # workspace
    total += len([s for s in wiz.missing_secrets if s not in wiz.collected_secrets and s not in wiz.skipped_secrets])
    if wiz.cloud_services:
        total += 1  # cloud_choice
        if "supabase" in wiz.cloud_services:
            total += 1  # supabase_migrate
    total += 1  # confirm
    return total


def _build_wizard_step(step_name: str, wiz: WizardState) -> dict:
    """Build the wizard_step WebSocket message for a given step."""
    total = _compute_total_steps(wiz)
    remaining = [s for s in wiz.missing_secrets if s not in wiz.collected_secrets and s not in wiz.skipped_secrets]

    # Calculate step_index
    if step_name == "workspace":
        idx = 0
    elif step_name == "secret":
        done_secrets = len(wiz.missing_secrets) - len(remaining)
        idx = 1 + done_secrets
    elif step_name == "cloud_choice":
        idx = 1 + len(wiz.missing_secrets)
    elif step_name == "supabase_migrate":
        idx = 2 + len(wiz.missing_secrets)
    elif step_name == "confirm":
        idx = total - 1
    else:
        idx = 0

    payload = {}
    if step_name == "workspace":
        payload = {
            "default_value": str(Path(wiz.workspace or "~/Projects/agent-workspace").expanduser()),
            "repo_url": wiz.repo_url,
        }
    elif step_name == "secret":
        if remaining:
            key = remaining[0]
            meta = _secret_meta(key)
            payload = {
                "key": key,
                "label": key.replace("_", " ").title(),
                "hint": _secret_hint(key),
                "description": meta["description"],
                "required": meta["required"],
                "remaining": [s for s in remaining if s != key],
                "found": wiz.found_secrets,
            }
    elif step_name == "cloud_choice":
        from bartolo.provisioner import CLOUD_TO_LOCAL
        services = []
        for svc in wiz.cloud_services:
            local = CLOUD_TO_LOCAL.get(svc, "local")
            services.append({
                "key": svc,
                "label": svc.replace("_", " ").title(),
                "local": local,
                "secrets_affected": [s for s in wiz.cloud_secrets_map.get(svc, []) if s in remaining],
            })
        payload = {"services": services}
    elif step_name == "supabase_migrate":
        payload = {
            "question": "Vols replicar les dades de Supabase al PostgreSQL local?",
            "description": "Això copiarà l'esquema i les dades de Supabase al teu PostgreSQL local."
        }
    elif step_name == "confirm":
        payload = {
            "workspace": wiz.workspace,
            "secrets": {k: "••••••••" for k in wiz.collected_secrets},
            "cloud_choices": wiz.cloud_choices,
            "supabase_migrate": wiz.supabase_migrate,
            "repo_url": wiz.repo_url,
        }

    return {
        "type": "wizard_step",
        "step": step_name,
        "step_index": idx,
        "total_steps": total,
        "payload": payload,
    }


def _secret_hint(key: str) -> str:
    """Return a human-readable format hint for a secret key."""
    hints = {
        "SUPABASE_URL": "https://xxxxx.supabase.co",
        "SUPABASE_ANON_KEY": "eyJhbG... (JWT anon key)",
        "SUPABASE_SERVICE_ROLE_KEY": "eyJhbG... (JWT service_role key)",
        "SUPABASE_SERVICE_KEY": "eyJhbG... (JWT service key)",
        "DATABASE_URL": "postgresql://user:pass@host:5432/db",
        "MONGODB_URI": "mongodb+srv://user:pass@cluster.mongodb.net/...",
        "STRIPE_SECRET_KEY": "sk_live_...",
        "JWT_SECRET": "clau-secreta-aleatoria",
        "SECRET_KEY": "clau-secreta-django",
        "ENCRYPTION_KEY": "clau-fernet-32-bytes-base64",
        "OPENAI_API_KEY": "sk-...",
        "ANTHROPIC_API_KEY": "sk-ant-...",
    }
    return hints.get(key, f"Valor per a {key}")


def _secret_meta(key: str) -> dict:
    """Return {description, required} for a secret key."""
    meta = {
        "SUPABASE_URL": {
            "description": "URL del projecte Supabase. Necessari per connectar-se a la base de dades, auth i storage.",
            "required": True,
        },
        "SUPABASE_ANON_KEY": {
            "description": "Clau pública de Supabase per operacions de client (frontend).",
            "required": True,
        },
        "SUPABASE_SERVICE_ROLE_KEY": {
            "description": "Clau secreta de Supabase amb accés total al projecte (bypass Row Level Security).",
            "required": True,
        },
        "SUPABASE_SERVICE_KEY": {
            "description": "Clau de servei de Supabase. Alternativa a la service_role key.",
            "required": True,
        },
        "DATABASE_URL": {
            "description": "URL de connexió a la base de dades principal.",
            "required": True,
        },
        "MONGODB_URI": {
            "description": "URI de connexió a MongoDB Atlas.",
            "required": True,
        },
        "STRIPE_SECRET_KEY": {
            "description": "Clau secreta de Stripe per processar pagaments. Opcional si no uses pagaments.",
            "required": False,
        },
        "STRIPE_PUBLISHABLE_KEY": {
            "description": "Clau pública de Stripe pel frontend. Opcional si no uses pagaments.",
            "required": False,
        },
        "STRIPE_WEBHOOK_SECRET": {
            "description": "Secret per verificar webhooks de Stripe. Opcional si no uses webhooks.",
            "required": False,
        },
        "JWT_SECRET": {
            "description": "Clau per signar tokens JWT d'autenticació. Sense això els usuaris no poden iniciar sessió.",
            "required": True,
        },
        "SECRET_KEY": {
            "description": "Clau secreta de Django per xifrar sessions, CSRF, etc.",
            "required": True,
        },
        "DJANGO_SECRET_KEY": {
            "description": "Clau secreta de Django per xifrar sessions, CSRF, etc.",
            "required": True,
        },
        "NEXTAUTH_SECRET": {
            "description": "Clau per xifrar tokens de NextAuth.js. Necessari per autenticació.",
            "required": True,
        },
        "ENCRYPTION_KEY": {
            "description": "Clau Fernet (AES-256) per xifrar dades sensibles a la base de dades. Si no la poses, les dades xifrades no es podran llegir.",
            "required": True,
        },
        "OPENAI_API_KEY": {
            "description": "Clau API d'OpenAI per funcions d'IA. Opcional si no uses GPT.",
            "required": False,
        },
        "ANTHROPIC_API_KEY": {
            "description": "Clau API d'Anthropic (Claude). Opcional si no uses Claude.",
            "required": False,
        },
        "SENDGRID_API_KEY": {
            "description": "Clau API de SendGrid per enviar correus. Opcional si no envies emails.",
            "required": False,
        },
        "RESEND_API_KEY": {
            "description": "Clau API de Resend per enviar correus. Opcional si no envies emails.",
            "required": False,
        },
        "TWILIO_ACCOUNT_SID": {
            "description": "SID del compte Twilio per SMS/trucades. Opcional si no uses Twilio.",
            "required": False,
        },
        "TWILIO_AUTH_TOKEN": {
            "description": "Token d'autenticació de Twilio. Opcional si no uses Twilio.",
            "required": False,
        },
        "AWS_ACCESS_KEY_ID": {
            "description": "Clau d'accés AWS per S3, Lambda, etc. Opcional si no uses AWS.",
            "required": False,
        },
        "AWS_SECRET_ACCESS_KEY": {
            "description": "Clau secreta AWS. Opcional si no uses AWS.",
            "required": False,
        },
        "GOOGLE_CLIENT_ID": {
            "description": "Client ID de Google OAuth per login social. Opcional si no uses Google login.",
            "required": False,
        },
        "GOOGLE_CLIENT_SECRET": {
            "description": "Client Secret de Google OAuth. Opcional si no uses Google login.",
            "required": False,
        },
        "GITHUB_CLIENT_ID": {
            "description": "Client ID de GitHub OAuth per login social. Opcional si no uses GitHub login.",
            "required": False,
        },
        "GITHUB_CLIENT_SECRET": {
            "description": "Client Secret de GitHub OAuth. Opcional si no uses GitHub login.",
            "required": False,
        },
        "GOOGLE_API_KEY": {
            "description": "Clau API de Google (Gemini). Opcional si no uses Gemini.",
            "required": False,
        },
        "HUGGINGFACE_API_KEY": {
            "description": "Clau API de HuggingFace per models d'IA. Opcional si no uses HuggingFace.",
            "required": False,
        },
        "FAL_KEY": {
            "description": "Clau API de Fal.ai per generació d'imatges. Opcional si no uses Fal.ai.",
            "required": False,
        },
        "EMERGENT_LLM_KEY": {
            "description": "Clau per l'LLM d'Emergent. Opcional si no uses stack Emergent.",
            "required": False,
        },
    }
    return meta.get(key, {
        "description": f"Valor de configuració per a {key}.",
        "required": False,
    })


async def _advance_wizard(ws: WebSocket, thread_id: str, wiz: WizardState,
                          from_step: str) -> None:
    """Calculate next step and send it to the frontend."""
    remaining = [s for s in wiz.missing_secrets if s not in wiz.collected_secrets and s not in wiz.skipped_secrets]
    total = _compute_total_steps(wiz)

    if from_step == "workspace":
        if remaining:
            next_step = "secret"
        elif wiz.cloud_services:
            next_step = "cloud_choice"
        else:
            next_step = "confirm"
    elif from_step == "secret":
        if remaining:
            next_step = "secret"  # still more secrets
        elif wiz.cloud_services:
            next_step = "cloud_choice"
        else:
            next_step = "confirm"
    elif from_step == "cloud_choice":
        if "supabase" in wiz.cloud_services:
            next_step = "supabase_migrate"
        else:
            next_step = "confirm"
    elif from_step == "supabase_migrate":
        next_step = "confirm"
    elif from_step == "start":
        next_step = "workspace"
    else:
        next_step = "confirm"

    wiz.step_history.append(next_step)
    msg = _build_wizard_step(next_step, wiz)
    await ws.send_json(msg)


async def _wizard_back(ws: WebSocket, thread_id: str, wiz: WizardState) -> None:
    """Go back to the previous wizard step, reverting state so the step shows correctly."""
    if wiz.step_history:
        wiz.step_history.pop()
    prev = wiz.step_history[-1] if wiz.step_history else "workspace"

    # Revert state so the target step has data to show
    if prev == "workspace":
        wiz.collected_secrets.clear()
        wiz.skipped_secrets.clear()
        wiz.cloud_choices.clear()
        wiz.supabase_migrate = False
    elif prev == "secret":
        # Un-handle the most recent secret so it shows in the form
        if wiz.collected_secrets:
            wiz.collected_secrets.popitem()
        elif wiz.skipped_secrets:
            wiz.skipped_secrets.pop()
    elif prev == "cloud_choice":
        wiz.cloud_choices.clear()
        wiz.supabase_migrate = False

    msg = _build_wizard_step(prev, wiz)
    await ws.send_json(msg)


async def _finalize_wizard(ws: WebSocket, thread_id: str, wiz: WizardState) -> None:
    """Apply wizard choices, generate placeholders, persist and launch agent."""
    from bartolo.dashboard.chat_routes import persist_thread_message
    from universal_repo_agent_v5 import save_secrets_cache, load_secrets_cache
    import secrets as _sec, uuid as _uuid

    cache = load_secrets_cache()
    placeholders: Dict[str, str] = {}

    # Save collected secrets
    for k, v in wiz.collected_secrets.items():
        cache[k] = v

    # Generate placeholders for cloud services set to "local"
    all_cloud = set()
    for v in wiz.cloud_secrets_map.values():
        all_cloud.update(v)
    for svc, choice in wiz.cloud_choices.items():
        if choice == "local":
            for s in wiz.cloud_secrets_map.get(svc, []):
                if s not in cache:
                    if "URL" in s:
                        placeholders[s] = "http://localhost:54321"
                    else:
                        placeholders[s] = f"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJsb2NhbC1wbGFjZWhvbGRlciJ9.{_uuid.uuid4().hex}"

    # Placeholders for remaining non-cloud missing secrets
    for s in wiz.missing_secrets:
        if s not in cache and s not in all_cloud and s not in wiz.collected_secrets:
            if "SUPABASE" in s and "KEY" in s:
                placeholders[s] = f"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJsb2NhbC1wbGFjZWhvbGRlciJ9.{_uuid.uuid4().hex}"
            else:
                placeholders[s] = _sec.token_hex(32)

    if placeholders:
        cache.update(placeholders)
    save_secrets_cache(cache)

    # Clear wizard state
    _wizard_states.pop(thread_id, None)

    # Build summary
    from bartolo.provisioner import CLOUD_TO_LOCAL
    lines = ["✅ **Configuració del muntatge:**"]
    lines.append(f"📁 Workspace: {wiz.workspace}")
    if wiz.collected_secrets:
        lines.append(f"🔐 Secrets: {', '.join(wiz.collected_secrets)}")
    if wiz.cloud_choices:
        for svc, choice in wiz.cloud_choices.items():
            local_name = CLOUD_TO_LOCAL.get(svc, "local")
            icon = "🖥️" if choice == "local" else "☁️"
            lines.append(f"{icon} {svc}: {'BD local Docker' if choice == 'local' else 'Cloud'}")
    if wiz.supabase_migrate:
        lines.append(f"🔄 Migració Supabase → PostgreSQL local: Sí")
    persist_thread_message(thread_id, "assistant", "\n".join(lines))
    await ws.send_json({"type": "wizard_done", "message": "\n".join(lines)})

    # Launch the agent
    await _launch_agent(ws, thread_id, wiz.repo_url, workspace=wiz.workspace or str(DEFAULT_WORKSPACE))


async def _handle_wizard_response(ws: WebSocket, thread_id: str,
                                   wiz: WizardState, step: str, data: dict) -> None:
    """Process a wizard_response from the frontend."""
    if data.get("action") == "back":
        await _wizard_back(ws, thread_id, wiz)
        return

    if step == "workspace":
        ws_dir = data.get("workspace", "").strip()
        if ws_dir:
            wiz.workspace = str(Path(ws_dir).expanduser())
        else:
            wiz.workspace = str(DEFAULT_WORKSPACE)
        wiz.current_step = 1
        await _advance_wizard(ws, thread_id, wiz, step)

    elif step == "secret":
        key = data.get("key", "")
        value = data.get("value", "")
        skipped = data.get("skipped", False)
        if not skipped and value:
            wiz.collected_secrets[key] = value
        else:
            wiz.skipped_secrets.append(key)
        await _advance_wizard(ws, thread_id, wiz, step)

    elif step == "cloud_choice":
        choices = data.get("choices", {})
        wiz.cloud_choices = choices
        await _advance_wizard(ws, thread_id, wiz, step)

    elif step == "supabase_migrate":
        wiz.supabase_migrate = data.get("migrate", False)
        await _advance_wizard(ws, thread_id, wiz, step)

    elif step == "confirm":
        await _finalize_wizard(ws, thread_id, wiz)


async def stream_ollama_chat(ws: WebSocket, messages: list, model: str):
    import aiohttp
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.7, "num_predict": 1024},
    }
    full = ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                buffer = ""
                async for chunk in resp.content.iter_chunked(256):
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="ignore")
                    while True:
                        nl = buffer.find("\n")
                        if nl < 0:
                            break
                        line = buffer[:nl].strip()
                        buffer = buffer[nl + 1:]
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if "message" in obj and "content" in obj.get("message", {}):
                            token = obj["message"]["content"]
                            full += token
                            await ws.send_json({"type": "token", "token": token})
                        if obj.get("done"):
                            await ws.send_json({"type": "done", "full_text": full})
                            return full
    except Exception as e:
        if full:
            await ws.send_json({"type": "done", "full_text": full})
        else:
            await ws.send_json({"type": "error", "error": f"No s'ha pogut connectar a Ollama: {e}"})
    return full


def classify_intent(text: str) -> dict:
    try:
        from bartolo_router import classify
        result = classify(text, ollama_url=OLLAMA_URL)
        return {"intent": result.get("intent", "conversa"),
                "source": result.get("source", "l1"),
                "cmd": result.get("cmd"),
                "repo_url": result.get("repo_url"),
                "repo_name": result.get("repo_name")}
    except Exception:
        return {"intent": "conversa", "source": "fallback"}


@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    model = DEFAULT_MODEL
    history: list = []
    thread_id = None
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "chat")
            message = data.get("message", "").strip()

            if msg_type == "set_thread":
                # Client requests to switch thread — send history
                thread_id = data.get("thread_id", "")
                if thread_id:
                    from bartolo.dashboard.chat_routes import ensure_thread_exists, get_thread_messages
                    ensure_thread_exists(thread_id)
                    msgs = get_thread_messages(thread_id)
                    history = [{"role": m["role"], "content": m["content"]} for m in msgs]
                    await ws.send_json({"type": "history", "messages": msgs})
                    # Re-send current wizard step if wizard is active for this thread
                    wiz = _wizard_states.get(thread_id)
                    if wiz:
                        step_name = _get_current_step_name(wiz)
                        msg = _build_wizard_step(step_name, wiz)
                        await ws.send_json(msg)
                continue

            if msg_type == "wizard_response":
                wiz = _wizard_states.get(thread_id) if thread_id else None
                if wiz:
                    step = data.get("step", "")
                    step_data = data.get("data", {})
                    await _handle_wizard_response(ws, thread_id, wiz, step, step_data)
                continue

            if not message:
                continue

            if msg_type == "chat":
                # Ensure thread exists
                if not thread_id:
                    from bartolo.dashboard.chat_routes import ensure_thread_exists
                    import uuid
                    thread_id = "t-" + uuid.uuid4().hex[:12]
                    t = ensure_thread_exists(thread_id)
                    await ws.send_json({"type": "thread_created", "thread": t})

                # Persist user message
                from bartolo.dashboard.chat_routes import persist_thread_message, append_input_to_history
                persist_thread_message(thread_id, "user", message)
                append_input_to_history(message)

                # Intercept if there's an active wizard for this thread
                wiz = _wizard_states.get(thread_id) if thread_id else None
                if wiz:
                    await ws.send_json({"type": "done", "full_text": "Ja hi ha un wizard de muntatge actiu. Completa'l o recarrega la pàgina."})
                    continue

                # Detect Supabase/cloud credentials pasted outside of a secrets prompt
                creds = _detect_credentials_in_message(message)
                if creds:
                    await _handle_credential_injection(ws, thread_id, creds)
                    continue

                intent_info = classify_intent(message)
                intent = intent_info["intent"]
                await ws.send_json({"type": "intent", "intent": intent, "source": intent_info["source"]})
                if intent == "info_sistema":
                    cmd = intent_info.get("cmd") or _extract_cmd(message)
                    if cmd:
                        await ws.send_json({"type": "action", "action": cmd})
                        import subprocess
                        try:
                            result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=15, cwd=str(DEFAULT_WORKSPACE))
                            output = result.stdout + result.stderr
                            persist_thread_message(thread_id, "assistant", output[:4000])
                            await ws.send_json({"type": "done", "full_text": output[:4000]})
                        except Exception as e:
                            persist_thread_message(thread_id, "assistant", f"Error: {e}")
                            await ws.send_json({"type": "done", "full_text": f"Error: {e}"})
                    else:
                        await ws.send_json({"type": "done", "full_text": "No s'ha pogut extreure una comanda per a aquesta consulta."})
                elif intent == "estat_workspace":
                    await ws.send_json({"type": "action", "action": "Consultant estat del workspace..."})
                    from bartolo.executor import load_services_registry
                    services = load_services_registry(DEFAULT_WORKSPACE)
                    repos = {k: v for k, v in services.items() if not k.startswith("_") and v}
                    if repos:
                        lines = ["**Repos actius:**"]
                        for repo, svcs in repos.items():
                            for s in svcs:
                                pid = s.get("pid", "?")
                                lines.append(f"- {repo}: {s.get('step_id','')} (PID {pid})")
                    else:
                        lines = ["Cap repo arrencat."]
                    text = "\n".join(lines)
                    persist_thread_message(thread_id, "assistant", text)
                    await ws.send_json({"type": "done", "full_text": text})
                elif intent == "temps_data":
                    from datetime import datetime, timezone as tz, timedelta
                    now_utc = datetime.now(tz.utc)
                    mar31 = datetime(now_utc.year, 3, 31, tzinfo=tz.utc)
                    last_sun_mar = mar31 - timedelta(days=(mar31.weekday() + 1) % 7)
                    oct31 = datetime(now_utc.year, 10, 31, tzinfo=tz.utc)
                    last_sun_oct = oct31 - timedelta(days=(oct31.weekday() + 1) % 7)
                    is_dst = last_sun_mar <= now_utc < last_sun_oct
                    cat_offset = timedelta(hours=2 if is_dst else 1)
                    cat_tz = "CEST (UTC+2)" if is_dst else "CET (UTC+1)"
                    cat_time = now_utc + cat_offset
                    lines = [
                        f"**Hora actual a Catalunya:**",
                        f"- Hora: **{cat_time.strftime('%H:%M:%S')}**",
                        f"- Data: {cat_time.strftime('%d/%m/%Y')}",
                        f"- Dia: {cat_time.strftime('%A')}",
                        f"- Zona: {cat_tz}",
                    ]
                    text = "\n".join(lines)
                    persist_thread_message(thread_id, "assistant", text)
                    await ws.send_json({"type": "done", "full_text": text})
                elif intent == "atura_repo":
                    await ws.send_json({"type": "action", "action": "Aturant serveis..."})
                    from bartolo.executor import stop_services
                    repo_hint = intent_info.get("repo_name") or _extract_repo(message)
                    stop_services(DEFAULT_WORKSPACE, repo_name=repo_hint or "all")
                    text = f"Aturats serveis de: {repo_hint or 'tots'}."
                    persist_thread_message(thread_id, "assistant", text)
                    await ws.send_json({"type": "done", "full_text": text})
                elif intent in ("munta_repo", "start_servei"):
                    repo_url = intent_info.get("repo_url") or _extract_url(message)
                    if repo_url:
                        await ws.send_json({"type": "action", "action": f"Analitzant {repo_url}..."})
                        import asyncio, concurrent.futures
                        loop = asyncio.get_running_loop()
                        try:
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                analysis = await loop.run_in_executor(
                                    pool, _analyze_repo_secrets, repo_url
                                )
                        except Exception as e:
                            await ws.send_json({"type": "done", "full_text": f"Error analitzant el repo: {e}"})
                            continue

                        found = analysis.get("found", [])
                        missing = analysis.get("missing", [])
                        cloud_services = analysis.get("cloud_services", [])
                        cloud_secrets_map = analysis.get("cloud_secrets_map", {})

                        # Show found secrets
                        if found:
                            found_msg = f"🔐 Secrets trobats a la caché: {', '.join(found)}."
                            persist_thread_message(thread_id, "assistant", found_msg)
                            await ws.send_json({"type": "done", "full_text": found_msg})

                        # If missing secrets or cloud services → wizard
                        if missing or cloud_services:
                            wiz = WizardState(
                                repo_url=repo_url,
                                repo_path=analysis["repo_path"],
                                missing_secrets=missing,
                                found_secrets=found,
                                cloud_services=cloud_services,
                                cloud_secrets_map=cloud_secrets_map,
                                third_party=analysis.get("third_party", {}),
                            )
                            _wizard_states[thread_id] = wiz
                            await _advance_wizard(ws, thread_id, wiz, "start")
                        else:
                            # No missing secrets, launch directly
                            await _launch_agent(ws, thread_id, repo_url)
                    else:
                        await ws.send_json({"type": "done", "full_text": "No s'ha detectat cap URL. Prova: munta https://github.com/usuari/repo.git"})
                else:
                    history.append({"role": "user", "content": message})
                    full_response = await stream_ollama_chat(ws, history, model)
                    if history and history[-1]["role"] == "user":
                        history.append({"role": "assistant", "content": full_response})
                    if len(history) > 20:
                        history = history[-20:]
                    # Persist assistant response
                    if full_response:
                        persist_thread_message(thread_id, "assistant", full_response)
                if intent in ("estat_workspace", "atura_repo"):
                    await ws.send_json({"type": "action", "done": "Acció completada. Ves a Repos per veure l'estat."})
    except WebSocketDisconnect:
        if thread_id:
            _pending_secrets.pop(thread_id, None)
            _wizard_states.pop(thread_id, None)
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


def _extract_cmd(text: str) -> str:
    import re
    cmd_map = [
        (r"ollama\s+list", "ollama list"),
        (r"ollama\s+ps", "ollama ps"),
        (r"docker\s+ps", "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"),
        (r"docker\s+logs?\s+(\S+)", None),
        (r"ps\s+aux", "ps aux --sort=-%mem | head -20"),
        (r"df\s+-h", "df -h"),
        (r"free\s+-h", "free -h"),
        (r"lsof\s+-i", "lsof -i -P -n | grep LISTEN"),
    ]
    for pattern, cmd in cmd_map:
        m = re.search(pattern, text)
        if m:
            if cmd:
                return cmd
            return f"docker logs {m.group(1)} --tail 50"
    if re.search(r"(docker|ollama|ps|df|free|lsof)", text.lower()):
        return text.strip()
    return ""


def _extract_url(text: str) -> str:
    import re
    m = re.search(r'(https?://[^\s]+|github\.com/[^\s]+|gitlab\.com/[^\s]+|bitbucket\.org/[^\s]+)', text)
    if m:
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        return url
    return ""


def _extract_repo(text: str) -> str:
    import re
    stop_verbs = r"(?i)(atura|para|apaga|stop|mata|frena)\s+(el\s+|la\s+|l'|els\s+|les\s+)?"
    text_after = re.sub(stop_verbs, "", text).strip()
    words = text_after.split()
    for w in words:
        w = w.strip(".,;:!?\"'()[]{}")
        if len(w) >= 3 and not w.lower() in ("el", "la", "els", "les", "l'", "un", "una", "de", "del", "tot", "tots", "totes", "all"):
            return w
    return ""
