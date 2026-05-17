# Bartolo / Universal Repo Agent — Context per a Claude Code

## Què és aquest projecte

Sistema d'arrencada universal de repositoris a Ubuntu. Clona repos de GitHub/GitLab/Bitbucket (o ZIPs locals), detecta el stack, instal·la dependències i arrenca els serveis automàticament. Inclou integració amb OpenWebUI (xat amb LLM Qwen 14B local) per controlar-ho via llenguatge natural.

L'usuari final coneix el sistema com **"Bartolo"** (el nom del model d'OpenWebUI configurat).

## Arquitectura actual (3 capes + paquet modular)

```
[Usuari] → OpenWebUI :3001 → Tools (function calling) → agent_http_bridge.py :9090 → universal_repo_agent_v5.py
                                                       ↓
                                              dashboard.py :9999 (control alternatiu sense LLM)
```

- **OpenWebUI**: xat amb Qwen2.5:14b via Ollama, function calling nadiu
- **Bridge HTTP** (`agent_http_bridge.py`): exposa l'agent com REST API al port 9090
- **Agent CLI** (`universal_repo_agent_v5.py`): punt d'entrada — 1225 línies, delega a `bartolo/`
- **Paquet `bartolo/`** (18 mòduls, ~4400 línies): tota la lògica — detectors, planner, executor, repair, CLI, validació, tipus
- **Dashboard** (`dashboard.py`): UI web a 9999, sense dependències extra
- **Tool OpenWebUI** (`openwebui_tool_repo_agent.py`): client Python pur (urllib) que el container OpenWebUI carrega

## Fitxers principals

| Fitxer | Què fa | Línies |
|---|---|---|
| `universal_repo_agent_v5.py` | Punt d'entrada CLI, delega a `bartolo/` | 1225 |
| `agent_http_bridge.py` | REST API al port 9090, jobs async, shell exec amb token, upload ZIP, wizard, router dispatch | 1408 |
| `openwebui_tool_repo_agent.py` | Tool per OpenWebUI (v2.4, 10 funcions) | 403 |
| `openwebui_tool_web_search.py` | Tool DuckDuckGo per cerques | 112 |
| `bartolo_router.py` | Classificador d'intencions L1 (regex) + L2 (LLM) — 8 intents | 257 |
| `bartolo_init.py` | CLI interactiva per muntar repos sense flags (reutilitza l'agent) | 168 |
| `bartolo/types.py` | Dataclasses: RepoAnalysis, ServiceInfo, ExecutionPlan, CommandStep... | 80 |
| `bartolo/validator.py` | Validador de comandes shell (whitelist + blacklist) | 145 |
| `bartolo/shell.py` | Execució shell, background, port checking, verify HTTP | 135 |
| `bartolo/exceptions.py` | Excepcions: AgentError, ConfigError, DetectorError | 15 |
| `bartolo/detectors/` | 12 detectors de stack + discovery + monorepo | ~900 |
| `bartolo/planner.py` | Generació de plans d'execució deterministes | ~1000 |
| `bartolo/provisioner.py` | Provisió automàtica de BDs via Docker | 150 |
| `bartolo/executor.py` | Execució de plans, registry de serveis, rollback | 282 |
| `bartolo/smoke.py` | Smoke tests adaptatius per framework | 90 |
| `bartolo/preflight.py` | Pre-flight check (deps, disk, ports) | 80 |
| `bartolo/runtime.py` | Detecció de versions runtime (.python-version, .nvmrc...) | 70 |
| `bartolo/llm.py` | Client Ollama (ollama_chat_json, safe_json_loads) | 48 |
| `bartolo/reporter.py` | Formatació de sortida (print_analysis, print_plan, print_final_summary) | 130 |
| `bartolo/cli.py` | CLI (parse_args, main, show_logs, refresh_repo_config) | 320 |
| `bartolo/repair/` | Debugger intel·ligent + KB reparacions + DeepSeek + Anthropic | ~700 |
| `bartolo/kb/` | KB d'èxits (success_kb) | 90 |
| `agents/debugger.py` | Compatibility shim → bartolo.repair | 16 |
| `agents/success_kb.py` | Compatibility shim → bartolo.kb | 3 |
| `dashboard.py` | Entry point :9999 | 54 |
| `bartolo/dashboard/chat.py` | WebSocket xat + wizard interactiu + router dispatch | 1427 |
| `bartolo/dashboard/templates.py` | HTML+CSS+JS inline (wizard forms, chat UI, threads) | 2253 |
| `bartolo/dashboard/repos_routes.py` | API status/logs/stop/launch/timeline/WS + escàner serveis sistema | 356 |
| `bartolo/dashboard/chat_routes.py` | API xat, historial, reparacions | 217 |
| `bartolo-goal.mjs` | Playwright: muntatge automatitzat via dashboard :9999, wizard, captura sessió | 430 |
| `bench.sh` | Bateria de proves automatitzada (11 repos complets, 6 quick) | 85 |
| `stress_test.sh` | Bateria d'estrès amb repos complexos (7 repos, detecció) | 110 |
| `setup_ubuntu.sh` | Instal·lador Node/Docker/Ollama/qwen2.5:14b | 190 |
| `bartolo_prompts.md` | Catàleg de prompts naturals que entén Bartolo | 131 |
| `INFORME_BATERIA.md` | Resultats de la bateria amb taxes d'èxit per stack | 101 |

## Fitxers que cal NETEJAR (legacy o aplicats)

- `universal_repo_agent_v4.py` (1345 línies) — versió antiga, moure a `legacy/`
- `patch_streamlit_fix.py` — JA APLICAT al v5.py (busca `# v2.4 streamlit fix:`)
- `patch_bridge_v23.py` — JA APLICAT al bridge (busca `# === v2.3 routes ===`)

## Stack tècnic

- **Python 3.8+** (només biblioteca estàndard al bridge i dashboard, `requests` opcional)
- **Ollama** + `qwen2.5:14b` corrent al host port 11434
  (model actiu a Bartolo — vegeu "Models compatibles amb tool calling")
- **OpenWebUI** en Docker, accedeix al host via `host.docker.internal:9090` i `:11434`
- **Docker** opcional, només per `--dockerize` mode i auto-provisioning de BDs
- **Workspace**: `~/universal-agent-workspace/` — repos clonats, logs, registry de PIDs
- **Secrets**: `~/.universal-agent/secrets.json` (chmod 600, plain JSON)

## Convencions de codi importants

### Validador de comandes (CRÍTIC)
A `universal_repo_agent_v5.py`, `validate_command()` és la capa de seguretat principal:
- Whitelist de prefixos a `SAFE_COMMAND_PREFIXES` (pip, npm, yarn, uvicorn, streamlit, ...)
- Blacklist de patrons perillosos (sudo, rm -rf /, curl|bash, ...)
- Accepta wrappers: `nohup`, `setsid`, env vars al davant (`PORT=3000 yarn start`)
- Accepta camins relatius dins del repo (`.venv/bin/pip`, `./scripts/start.sh`)

**MAI tocar el validador sense provar amb `bench.sh` després.**

### Registry de serveis
- Format JSON a `~/universal-agent-workspace/.agent_services.json`
- Cada servei té: pid, repo_name, step_id, command, cwd, log_file
- Comprovació RUNNING/STOPPED via `os.kill(pid, 0)`
- Aturada amb `killpg(os.getpgid(pid), SIGTERM)` per matar fills

### Bridge async jobs
- `_JOBS` dict thread-safe, max 50 jobs (auto-evicts older done/failed)
- Output capturat línia a línia (max 2000 línies en memòria)
- Estats: `queued`, `running`, `done`, `failed`

### Shell exec amb token (v2.3)
- `POST /exec_shell {cmd}` → retorna token de 8 chars
- Token caduca 120s, single-use
- `POST /exec_shell/confirm {token, timeout}` → executa
- Blacklist: `rm -rf /`, `mkfs`, `dd if=`, `shutdown`, `reboot`, etc.

## Models compatibles amb tool calling (Bartolo)

Validat durant sessió de debug 2026-04-26. El function calling natiu d'OpenWebUI
REQUEREIX que el model emeti el camp `tool_calls` en la resposta JSON d'Ollama.
Alguns models emeten la crida com a **text al camp `content`** (fals positiu visual:
sembla que funciona però la tool no s'executa).

| Model | VRAM | Tool calling | Notes |
|---|---|---|---|
| `qwen2.5:14b` | ~8.5 GB | ✅ | Emet `tool_calls` correctament. **Model actiu a Bartolo.** Verificat 2026-05-04 amb RTX 3080 (9.4 GB lliures → cap en VRAM sense offloading). |
| `qwen2.5:7b` | ~4.4 GB | ✅ | Bo per a RTX 3080 si hi ha poca VRAM lliure. |
| `llama3.1:8b` | ~4.7 GB | ✅ | Excel·lent amb tools. |
| `llama3:latest` | 4.7 GB | ❌ | No suporta tool calling. |
| `qwen2.5-coder:14b` | ~8.5 GB | ❌ | Emet la crida com a text al `content`. No funciona. |
| `qwen2.5-coder:7b` | ~4.4 GB | ❌ | Mateix problema que coder:14b. |
| `mistral-nemo:12b` | ~7 GB | ❌ | Mateix problema que coder:14b. |
| `qwen3:8b` | ~5 GB | ⚠️ | No verificat amb tools. |

### Snippet de validació per a models nous

Abans d'integrar un model nou a Bartolo, valida el tool calling directament
contra l'API d'Ollama (sense OpenWebUI):

```bash
curl -s http://localhost:11434/api/chat -d '{
  "model": "NOM_DEL_MODEL",
  "stream": false,
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_status",
      "description": "Retorna lestat del sistema",
      "parameters": {"type": "object", "properties": {}}
    }
  }],
  "messages": [{"role": "user", "content": "Crida la tool get_status ara"}]
}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
msg = d.get('message', {})
tool_calls = msg.get('tool_calls')
content = msg.get('content', '')
if tool_calls:
    print('✅ tool_calls correctes:', json.dumps(tool_calls, indent=2))
elif 'get_status' in content:
    print('❌ crida com a TEXT al content (no funciona amb OpenWebUI)')
else:
    print('⚠️  resposta inesperada:', content[:200])
"
```

## Taxa d'èxit actual

Bench quick: **6/6 (100%)** — 2 execucions reals (streamlit-example, node-js-sample), 4 deteccions (flask, express, fastapi, django).
Bench complet: **11/11 (100%)**.

Taxa d'èxit realista per a repos nous ben estructurats: **~80-85%**.
Els fallos típics són repos molt antics amb dependències trencades o monorepos complexos.

## Problemes resolts

### ✅ [RESOLT 2026-05-12] v6.0 — Refactor modular complet (3 fases)

El monòlit `universal_repo_agent_v5.py` ha passat de 4067 → 1225 línies (-70%).
Tota la lògica s'ha extret a 18 mòduls dins del paquet `bartolo/` (~4400 línies).

**Fase 1 — Tipus, validador, shell, excepcions:**
- `bartolo/types.py`: dataclasses (`RepoAnalysis`, `ServiceInfo`, `ExecutionPlan`, `CommandStep`, `ExecutionResult`, `StepError`)
- `bartolo/validator.py`: `validate_command()`, `ShellCommand`, whitelist/blacklist
- `bartolo/shell.py`: `run_shell()`, `maybe_background_command()`, `verify_http()`, `verify_port()`, `find_free_port()`
- `bartolo/exceptions.py`: `AgentError`, `ConfigError`, `DetectorError`

**Fase 2 — Detectors, planner, executor, provisioner:**
- `bartolo/detectors/` (13 fitxers): 12 detectors de stack + `discovery.py` + `monorepo.py` + `__init__.py`
- `bartolo/planner.py` (~1000 línies): `build_deterministic_plan()`, `choose_python_run_cmd()`, `choose_node_run_cmd()`, `choose_service_verify()`
- `bartolo/provisioner.py`: `build_db_provision_steps()`, `inject_db_env_vars()`, `DB_DOCKER_CONFIGS`, `CLOUD_TO_LOCAL`
- `bartolo/executor.py` (282 línies): `execute_plan()`, `register_service()`, `stop_services()`, `load_services_registry()`
- `bartolo/smoke.py`: `run_smoke_tests()`, `_framework_endpoints()`
- `bartolo/preflight.py`: `preflight_check()`
- `bartolo/runtime.py`: `read_runtime_versions()`, `check_runtime_versions()`

**Fase 3 — Repair, LLM, CLI, reporter:**
- `bartolo/llm.py` (48 línies): `ollama_chat_json()`, `safe_json_loads()`, `OLLAMA_CHAT_URL`, `DEFAULT_MODEL`
- `bartolo/reporter.py` (130 línies): `print_analysis()`, `print_plan()`, `print_final_summary()`
- `bartolo/cli.py` (320 línies): `parse_args()`, `main()`, `show_logs()`, `refresh_repo_config()`
- `bartolo/repair/kb.py` (80 línies): `RepairKB` — KB de reparacions basada en signatures d'error
- `bartolo/repair/fallback.py` (60 línies): `_FALLBACK_MAP`, `_get_fallbacks()` — Plan B per errors comuns
- `bartolo/repair/anthropic.py` (90 línies): `repair_with_anthropic()` — fallback a Claude API
- `bartolo/repair/deepseek.py` (140 línies): `repair_with_deepseek()`, `repair_signature()` — reparació barata via DeepSeek
- `bartolo/repair/debugger.py` (395 línies): `IntelligentDebugger` — loop de reparació 4 nivells (Plan B → KB → DeepSeek → Anthropic → Escalate)
- `bartolo/kb/success.py` (82 línies): `lookup_plan()`, `record_success()` — KB d'èxits per stack
- `agents/debugger.py` → compatibility shim (16 línies)
- `agents/success_kb.py` → compatibility shim (3 línies)

**Shims de compatibilitat:** `agents/debugger.py` i `agents/success_kb.py` re-exporten
des de `bartolo.repair` i `bartolo.kb` per no trencar tests existents.

**4 bugs corregits durant la Fase 3:**
1. `.env` amb `xargs` fallava amb URLs (`://`) → `set -a && . ./.env && set +a`
2. `inject_db_env_vars()` escrivia URLs sense `KEY=` → `KEY=VALUE` sempre
3. Falsos positius de ports (`2009/06/25`, `to_list(1000)`) → `run_url` prioritari sobre `ports_hint`
4. Test anthropic desfasat → actualitzat a nova API `repair_with_anthropic()`

### ✅ [RESOLT 2026-05-11] v5.2 — 7 fixes de fiabilitat

**F1 — Docker health check timeout:**
`build_db_provision_steps()` feia 30×2s = 60s de health check, insuficient per
primer pull d'imatge + init de PostgreSQL. **Fix:** `sleep 3` inicial + 90×2s = 183s màx.

**F2 — LLM repair "No closing quotation":**
qwen2.5 generava text conversacional amb cometes desbalancejades al camp `command`
→ `shlex.split()` petava amb ValueError. **Fix:** `_extract_bash_command()` neteja
prefixos conversacionals (català i anglès), `_sanitize_quotes()` elimina cometes
senars, system prompt reforçat amb `_BASH_ONLY_INSTRUCTION`.

**F3 — Port conflict resolution per a tots els stacks:**
`choose_service_verify()` només injectava `PORT=` per a `node` i `python`.
**Fix:** suport per a tots els stacks: `deno`, `elixir`, `dotnet`, `go`, `ruby`,
`php`, `java` + fallback genèric `PORT={free_port}`. Amb flags específics per
framework (`--port`, `--urls`, `-Dserver.port`, `ASPNETCORE_URLS`...).

**F4 — Background service markers per a tots els stacks:**
`maybe_background_command()` només reconeixia `npm/yarn/uvicorn/streamlit/rails...`.
Sense `deno run` o `dotnet run`, els serveis es quedaven bloquejats en foreground.
**Fix:** afegits `deno run`, `deno task`, `dotnet run`, `dotnet watch`,
`mix phx.server`, `mix run`, `bundle exec`.

**F5 — Deno detection sense manifest:**
`detect_deno_service()` requeria `deno.json` o `deno.jsonc`. Repos com
`deno-rest-greet` (només `server.ts` amb imports `npm:`/`jsr:`) no es detectaven.
**Fix:** escaneja `.ts` buscant `from "npm:"` / `from "jsr:"`, llegeix el port
real del codi font, tria el millor entry point (`server.ts`, `main.ts`...).

**F6 — Pre-flight check cec per 10/12 stacks:**
Només `detect_node_service` i `detect_docker_service` passaven `ports_hint` al
`ServiceInfo`. `preflight_check()` no veia els ports de la resta d'stacks i no
avisava de conflictes. **Fix:** tots 12 detectors passen `ports_hint`.

**F7 — `fuser` rebutjat pel validador:**
El debugger suggeria `fuser -k 3000/tcp` per alliberar ports però `fuser` no
era a `SAFE_COMMAND_PREFIXES`. **Fix:** afegit.

### ✅ [RESOLT 2026-05-11] v5.2 — Deno `-A` (allow-all)
Default Deno run de `--allow-net` a `-A` (allow-all) per auto-deployment robust.
La majoria d'apps Deno necessiten read + env + net com a mínim.

### ✅ [RESOLT 2026-05-11] v5.2 — Docker compose auto-detecció
Nova funció `get_docker_compose_cmd()` que detecta `docker compose` (plugin) vs
`docker-compose` (standalone). Totes les referències hardcodejades substituïdes.

### ✅ [RESOLT 2026-05-11] v5.2 — sudo amb contrasenya
`_install_system_dep()` usa `getpass.getpass()` + `sudo -S` per instal·lar
dependències del sistema amb contrasenya. Suporta mode `--non-interactive`.

### ✅ [RESOLT 2026-04-26] Fix #1 — Tool 2.3 NO enviava X-Auth-Token
`openwebui_tool_repo_agent.py` llegeix `BRIDGE_AUTH_TOKEN` des de l'entorn i l'afegeix
com `X-Auth-Token` a tots els `_post`/`_get` via nou helper `_headers()`. Versió 2.3→2.4.

### ✅ [RESOLT 2026-04-26] Fix #2 — IP hardcoded a `url_pujada_de_zips()`
El bridge exposa `public_url` al `/health` (IP LAN via socket UDP a 8.8.8.8,
override via `BRIDGE_PUBLIC_URL`). La tool consulta `/health` en runtime; fallback
genèric si el bridge és antic (compatibilitat enrere).

### ✅ [RESOLT 2026-04-26] Fix #3 — Llibreries Node detectades com apps
Nova funció `is_node_library(pkg_data)` amb scoring basat en camps de `package.json`
(files +2, peerDeps +1, exports +1, publishConfig +1, sense script runnable +1, private -1).
Llindar ≥ 2 → `detect_node_service()` retorna `None`. Express: 0 passos de run (correcte).
Tests: `test_node_library_detection.py` (11/11). Branca: `fix/node-library-detection`.

### ✅ [RESOLT 2026-04-26] Fix #4 — Registry desincronitzat (serveis zombi)
**Causa-arrel exacta:** `stop_services()` fa `data[name] = []` incondicionalment
després d'intentar matar processos. Si el PID registrat és el del shell intermediari
del `&` (que ja ha mort), `os.getpgid(pid)` llança `ProcessLookupError` → silenciat
per `except Exception` → el fill real (uvicorn/yarn, en nova sessió setsid) sobreviu
sense rebre SIGTERM. El registry queda buit però els processos OS continuen.
`show_status` salta entrades buides → Bartolo reporta "res corre" incorrectament.
**Fix:** `del data[name]` en lloc de `data[name] = []` + neteja defensiva a
`load_services_registry`. Verificació E2E via Bartolo amb streamlit-example.

### ✅ [RESOLT 2026-05-06] Fix #5 — `refresca_repo` fallava per stacks no-Emergent
**Causa-arrel exacta:** `refresh_repo_config()` (`--refresh`) cridava `detect_emergent_stack()`
i retornava error si el resultat era `None`. Repos com wavebox-mail (Node.js backend + Vite
frontend) tenen `backend/` i `frontend/` però no `backend/server.py` (FastAPI) ni MongoDB
→ `detect_emergent_stack()` retornava `None` → error "no sembla un stack Emergent".
**Fix** a `universal_repo_agent_v5.py`: si no és Emergent però el repo té `start.sh`,
fa `bash start.sh stop` + `stop_services()` + `bash start.sh` (stop + restart complet).
Si no té `start.sh` tampoc, retorna missatge d'error informatiu en lloc del missatge confús
sobre `backend/` + `frontend/`.

### ✅ [RESOLT 2026-05-10] Fix #7 — `atura_repo` sense regla L1 ni handler L3
**Causa-arrel exacta:** Ni `bartolo_router.py` ni `agent_http_bridge.py` tenien cap
regla per classificar o gestionar peticions d'aturar serveis ("atura X", "para X",
"stop X"). Les peticions queien a L2 com a "conversa". El `POST /stop` existia com a
endpoint però el router no hi arribava.
**Fix:**
- `bartolo_router.py`: Afegida regla L1 amb 9 verbs (atura, para, stop, apaga, mata, frena...),
  `atura_repo` a `_L2_INTENTS` i prompt L2, `_REPO_NAME_RE` actualitzada.
- `agent_http_bridge.py`: Handler L3 complet amb cerca de repo al workspace, suport per
  "atura tot"/"atura tots" → `_workspace_stop("all")`.

### ✅ [RESOLT 2026-05-10] Fix #8 — `start_servei` fallava amb repos no-Emergent
**Causa-arrel exacta:** El handler `start_servei` cridava `_run_agent(["--refresh", ...])`
que internament usa `refresh_repo_config()`. Aquesta funció només suporta stacks Emergent
o repos amb `start.sh`. Repos com streamlit-example (muntats per Bartolo) no tenen cap
dels dos → error "no és Emergent ni té start.sh".
**Fix:** El handler ara primer atura el servei (`_workspace_stop`) i després re-executa
el pla complet via `--input <path> --execute --approve-all --non-interactive --no-readme
--no-model-refine`. Timeout pujat a 300s.

### ✅ [RESOLT 2026-05-10] Fix #9 — Flask detectat com "Desconegut" al wizard
**Causa-arrel exacta:** `_analyze_repo_quick()` al bridge només mirava `requirements.txt`
i `*.py` per detectar Python. Flask (i molts paquets Python) usen `setup.py`, `setup.cfg`
o `pyproject.toml` sense `requirements.txt` al root.
**Fix:** Afegits `setup.py`, `setup.cfg`, `pyproject.toml` a la detecció Python del wizard.

### ✅ [RESOLT 2026-05-10] Fix #10 — `pnpm`/`yarn` no es comprovaven al sistema
**Causa-arrel exacta:** `SYSTEM_DEPS` no incloïa `pnpm` ni `yarn`. Quan `detect_node_service`
detectava un `pnpm-lock.yaml` i generava `pnpm install` com a pas, el sistema no verificava
si `pnpm` estava instal·lat → error 127 en executar.
**Fix:**
- `pnpm` i `yarn` afegits a `SYSTEM_DEPS` amb check (`pnpm --version`) i install hint.
- `analyze_repo()`: ara afegeix el `package_manager` del servei a `host_requirements`
  (ex: si el servei usa pnpm, afegeix `pnpm` als requisits del host).

### ✅ [RESOLT 2026-05-10] Fix #11 — Missatge genèric per repos llibreria
**Causa-arrel exacta:** Quan un repo era una llibreria (0 serveis), el missatge era
"⚠️ No s'ha pogut derivar cap pla d'execució automàticament", que no ajudava l'usuari
a entendre per què.
**Fix:** Si el repo té manifests de paquet (package.json, setup.py, go.mod...) però
0 serveis, ara diu: "ℹ️ El repo sembla una llibreria/package, no una aplicació executable."

### ✅ [RESOLT 2026-05-10] Fix #12 — Bridge no veia serveis arrencats per l'agent
**Causa-arrel exacta:** `_workspace_services()` i `_workspace_stop()` al bridge escanegen
`.logs/*.pid`. Però `register_service()` de l'agent només guardava PIDs a `.agent_services.json`,
sense crear `.logs/*.pid`. Conseqüència: serveis arrencats via `--execute` (streamlit, node...)
eren invisibles al bridge. Només els serveis amb `start.sh` (wavebox-mail) creaven PID files.
**Fix:**
- `register_service()`: ara també crea `.logs/<step_id>.pid` amb el PID del procés.
- `stop_services()`: ara neteja els `.logs/<step_id>.pid` en aturar serveis.
El bridge ja no necessita canvis — els seus `_workspace_services`/`_workspace_stop`
funcionen correctament amb els PID files creats per l'agent.

### ✅ [RESOLT 2026-05-10] Bloc A — Millores de fiabilitat (A1, A2, A3)

**A1 — Pre-flight check abans de clonar:**
Nova funció `preflight_check()` a l'agent que comprova abans de generar el pla:
- Dependències del sistema (`SYSTEM_DEPS`) — avisa quines cal instal·lar
- Espai lliure al disc — avorta si < 500 MB
- Conflictes de ports — detecta si els ports del servei ja estan ocupats
Retorna `bool`: `True` = continuar, `False` = cancel·lar. Integrada a `main()`.

**A2 — Plan B per step fallit:**
Nou diccionari `_FALLBACK_MAP` amb alternatives predefinides per errors comuns:
- `pnpm install` → `npm install`, `yarn install`
- `yarn install` → `npm install`
- `go mod tidy` / `go build` → `go env` (diagnòstic)
- `pip install -r requirements.txt` → `pip install --break-system-packages -r requirements.txt`
Funció `_get_fallbacks()` busca coincidències exactes, per prefix, o suggereix
alternatives si el returncode és 127 (command not found).
Integrat a `execute_plan()`: prova fallbacks ABANS d'escalar al debugger LLM.

**A3 — Registre d'èxits per stack (`agents/success_kb.py`):**
Nou mòdul que guarda plans que han funcionat a `~/.universal-agent/success_kb.json`.
- `lookup_plan(service_type, manifests)`: busca un pla validat per a un stack concret
- `record_success(service_type, manifests, steps)`: guarda un pla que ha funcionat
- Claus tipus `node+npm`, `python+streamlit+pip`, etc.
Integrat a `build_deterministic_plan()` (consulta primer) i `execute_plan()` (guarda si OK).

### ✅ [RESOLT 2026-05-10] C1 — `bartolo init` CLI interactiu

Nou fitxer `bartolo_init.py` (168 línies). Guia interactiva per muntar repos sense flags:
1. Demana URL/Path del repo
2. Demana directori de treball (default `~/universal-agent-workspace`)
3. Adquireix el repo (clona/descomprimeix)
4. Analitza el stack
5. Pre-flight check (deps, disk, ports)
6. Genera i mostra el pla
7. Demana confirmació
8. Executa i mostra resultats
Reutilitza `acquire_input()`, `analyze_repo()`, `preflight_check()`, `build_deterministic_plan()`,
`execute_plan()` de l'agent. Ideal per usuaris que no volen recordar flags.

### ✅ [RESOLT 2026-05-10] Bloc B — Info de connexió a BD (B1, B2, B3, B4)

**B1 — `print_final_summary()` millorat:**
Mostra estructuradament per cada BD: contenidor Docker, host:port, usuari/password,
nom de la BD, URL de connexió, comanda `docker exec` per connectar, i CLI local
(`psql`, `mongosh`, `redis-cli`) si estan instal·lades.

**B2 — Detecció de BD al wizard del bridge:**
`_wizard_analyze()` escaneja vars d'entorn de BD (`MONGO_URL`, `DATABASE_URL`,
`POSTGRES_*`, `MYSQL_*`, `REDIS_URL`). Retorna `db_hints` al diccionari d'anàlisi.
CONFIRM_PATH mostra `| BD: MongoDB` i SUMMARY mostra `BD: MongoDB (localhost:27017)`.

**B3 — Info de BD a `_workspace_services()` i `estat_serveis()`:**
El bridge escaneja `docker ps --filter name=agent-` i retorna clau `_databases` amb
type, container, port, connection_url per cada BD activa. La tool d'OpenWebUI
formata aquesta info a `estat_serveis()`.

**B4 — Guia post-desplegament:**
Després de `print_final_summary()`, mostra el camí al fitxer `.env` i les variables
de BD injectades. Per stacks Emergent, afegeix la connexió MongoDB explícita.

### ✅ [RESOLT 2026-05-10] Bloc E — Estrès amb repos complexos (E1, E2, E4, E3)

**E1 — Detecció bàsica de monorepos:**
Nova funció `detect_monorepo_tool()` que detecta `turbo.json`, `nx.json`,
`pnpm-workspace.yaml`, `lerna.json` i `workspaces` a `package.json`.
Warning a `analyze_repo()`: "Monorepo detectat (turborepo) — cada package
es tracta com a servei independent." Warnings visibles a `print_analysis()`.
Fitxers de monorepo afegits a `discover_candidate_dirs()`.

**E2 — Nous detectors de stacks:**
3 detectors nous a `ALL_DETECTORS` (12 total):
- `detect_deno_service()`: `deno.json`, `deno.jsonc`, `import_map.json` + fallback a `.ts` amb imports Deno
- `detect_elixir_service()`: `mix.exs` (detecta Phoenix vs Elixir genèric)
- `detect_dotnet_service()`: `*.csproj`, `*.fsproj`, `*.sln` (detecta ASP.NET vs genèric)
Amb passos d'instal·lació i execució a `build_deterministic_plan()`.
`req_map` actualitzat amb deno, elixir, dotnet.

**E4 — Correcció de limitacions:**
- `detect_python_service()`: afegits `wsgi.py`, `asgi.py`, `index.py`, `run.py`, `api.py`
- `detect_go_service()`: escaneja fitxers `.go` i `.env.example` per trobar el port real
  en lloc d'assumir 8080

**E3 — `stress_test.sh`:**
Nou script de bateria amb 7 repos complexos en mode `analyze` (detecció):
turborepo, nx-examples, phoenix, deno, dotnet-samples, microservices-demo, lerna.
Mostra stack detectat, tipus, i warnings de monorepo.

### ✅ [RESOLT 2026-05-10] Cloud Services — Serveis cloud amb fallback local

**`CLOUD_TO_LOCAL`** (al costat de `DB_DOCKER_CONFIGS`):
```python
CLOUD_TO_LOCAL = {
    "supabase": "postgresql",      # Supabase → PostgreSQL local
    "mongodb_atlas": "mongodb",    # MongoDB Atlas → MongoDB local
}
```

Quan l'agent detecta un servei cloud (`DB_HINT_PATTERNS`, README, o codi),
resol automàticament a l'alternativa local via Docker. L'usuari veu:
- Al `print_final_summary()`: "☁️ Supabase detectat → PostgreSQL local"
- Al wizard: "BD: supabase → postgresql local"
- Per canviar a cloud: definir les vars d'entorn reals al `.env`

### ✅ [RESOLT 2026-05-11] Debugger unificat (`IntelligentDebugger`)
Les funcions `diagnose_error_with_model` i `ask_model_for_repair` eren dues crides
desconnectades (sense memòria entre intents ni context del repo). Substituïdes per
la classe `IntelligentDebugger` a `agents/debugger.py` (commit `e13df6e`):
- `_diagnose()`: sistema de prompting amb stack, root, manifests, deps, KB markdown
- `_repair_loop_ollama()`: conversa multi-turn amb historial complet d'intents previs
- `_repair_with_anthropic()`: fallback a Anthropic API
- `_kb_scan()`: cerca prèvia a la KB de reparacions
- `_escalate()`: delega a `ErrorReporter` si s'esgoten tots els intents

### ✅ [RESOLT 2026-05-11] bench.sh ja passa --non-interactive
Ambdós modes (`analyze` i `run`) ja inclouen `--non-interactive --no-readme --no-model-refine`.

### ✅ [RESOLT 2026-05-10] 5 Millores de fiabilitat (versions runtime, pre-classificador, monorepo, smoke tests, rollback)

**Versions runtime:** `read_runtime_versions()` llegeix `.python-version`, `.nvmrc`, `.node-version`,
`go.mod`, `package.json` (`engines.node`), `.tool-versions`. `check_runtime_versions()` compara amb
les versions instal·lades i genera warnings (mai bloquegen).

**Pre-classificador:** `classify_repo_type()` identifica `collection`, `documentation`, `library`,
`monorepo`, `unknown`, `application`. Evita generar 60+ passos per a repos-col·lecció.

**Orquestració monorepo:** `detect_monorepo_tool()` guarda resultat a `analysis.monorepo_tool`.
`build_deterministic_plan()` afegeix pas d'instal·lació workspace al root (`pnpm install -r`,
`npm install -ws`, `npx lerna bootstrap`). Reordena passos: `install`/`migrate` abans de `run`.

**Smoke tests adaptatius:** `_framework_endpoints(svc)` retorna endpoints canònics per framework
(`/docs` per FastAPI, `/actuator/health` per Spring, `/health` per Flask/ASP.NET...).
`run_smoke_tests()` prova fins a 3 endpoints per servei, primer 2xx/3xx = OK.

**Rollback en error:** `_backup_env_files()` còpia `.env` → `.env.agent-backup`. Si un pas crític
falla, `_execute_rollback()` atura processos, contenidors BD i restaura `.env` dels backups.

### ✅ [RESOLT 2026-05-10] 3 Millores per repos complexos (tool detection, auto-install, noise filter)

**Tool detection:** `_TOOL_REPO_NAMES` (turborepo, deno, lerna, phoenix, nx) i `_TOOL_MARKER_FILES`
(turbo.json, pnpm-workspace.yaml, lerna.json). `classify_repo_type()` retorna `"tool"` per tools
i `analyze_repo()` salta la detecció de serveis.

**Auto-install runtimes:** `_install_system_dep()` instal·la automàticament deps amb
`--approve-all`. Nous runtimes a `SYSTEM_DEPS`: deno, elixir, mix. pnpm/yarn usen `corepack`.

**Noise filter:** `SKIP_DIRS` ampliat amb `__tests__`, `tests`, `test`, `spec`, `fixtures`,
`mocks`, `e2e`, `cypress`, `playwright`. `_is_test_or_fixture_file()` filtra `*.test.*`,
`*.spec.*`, `*_test.*` a `discover_candidate_dirs()`.

### ✅ [RESOLT 2026-05-10] KB d'èxits: clau inclou repo_name

`_stack_key()` a `agents/success_kb.py` ara inclou `repo_name` a la clau hash. Abans dos repos
Node amb `package.json` compartien pla (ex: node-js-sample i Mantine rebien el mateix pla).
Ara `node-js-sample::node/npm` i `mantine::node/npm` són entrades separades.

### ✅ [RESOLT 2026-05-11] Build + Migracions + DB Health

**Build step Node:** `build_deterministic_plan()` detecta `"build"` a `package.json` scripts
i afegeix pas `pnpm build`/`yarn build`/`npm run build` entre install i run.

**Migrations Node/PHP:** Prisma (`prisma/schema.prisma` → `npx prisma migrate deploy`),
Knex (`knexfile.js` → `npx knex migrate:latest`), Sequelize (`.sequelizerc` →
`npx sequelize-cli db:migrate`), Laravel (`php artisan migrate --force`).

**DB Health + ordre:** `"db": -1` a `_CATEGORY_ORDER` (contenidors s'arrenquen primer).
`verify_step` activat per `category in ("run", "db")`. Health check `nc -z` amb
`sleep 3` + 90 intents de 2s (183s màx). Rollback atura contenidors en cas d'error.

### ✅ [RESOLT 2026-05-10] bartolo-doctor.sh: 2 bugs menors
1. **Pas 2 — `/proc/PID/environ` Permission denied:** El codi ja ho gestiona correctament.
2. **Pas 7 — `docker port` parsing fràgil amb IPv6:** `grep -oP '0\.0\.0\.0:\K\d+'` per
   extreure només el port de la línia IPv4.

### ✅ [RESOLT 2026-05-11] Fix #13 — `estat_serveis` crash amb `_databases`

**Causa-arrel exacta:** `estat_serveis()` a `openwebui_tool_repo_agent.py` iterava
`ws.items()` incloent la clau `_databases` (llista), causant `svcs.items()` → AttributeError.
L'usuari veia: "Els serveis del repositori estan actualment en una condició que impedeix
la recollida d'estatus correctament."

**Fix:** `if repo.startswith("_"): continue` al bucle `for repo, svcs in ws.items()`.
La tool actualitzada a OpenWebUI via SQLite (`/app/backend/data/webui.db`).

### ✅ [RESOLT 2026-05-16] Wizard interactiu al xat del dashboard

Quan l'usuari demana muntar un repo que requereix secrets o té serveis cloud,
el dashboard ara mostra un wizard pas a pas amb formularis HTML dins les bombolles
de xat (vanilla JS + DOM, sense dependències).

**Passos del wizard (dinàmics segons el repo):**
1. **workspace** — input text amb default `~/Projects/agent-workspace`
2. **secret** — un pas per cada secret missing. Input password + toggle visibilitat + hint. "Ometre" / "Continua"
3. **cloud_choice** — toggles per serveis cloud (local Docker vs cloud original)
4. **supabase_migrate** — només si Supabase detectat. "Sí, replica dades" / "No, gràcies"
5. **confirm** — targeta resum amb totes les opcions. Botó "Munta"

**Funcionalitats:**
- Botó "Tornar" a tots els passos (reversió d'estat correcta)
- Barra de progrés (`wizard-progress-bar`) amb percentatge
- Reconnexió WebSocket: si es recarrega la pàgina, es reenvia el pas actual
- Neteja d'estat al `WebSocketDisconnect`
- `SELF_CONFIGURED_KEYS` (WhatsApp, etc.) i `NON_SECRET_CONFIG_KEYS` (BASE_URL, PORT...) exclosos del wizard

**Fitxers modificats:**
- `bartolo/dashboard/chat.py`: `WizardState` dataclass, 8 funcions de state machine, handler `wizard_response`
- `bartolo/dashboard/templates.py`: CSS + JS (5 builders, `renderWizardStep`, `submitWizardResponse`, `clearWizard`)
- `universal_repo_agent_v5.py`: `KNOWN_SECRET_KEYS`, `SELF_CONFIGURED_KEYS`, `NON_SECRET_CONFIG_KEYS`

**Nous tipus WebSocket:** `wizard_step`, `wizard_response`, `wizard_done`, `wizard_error`

### ✅ [RESOLT 2026-05-16] Escàner de serveis del sistema

Nova funció `_scan_system_services()` a `repos_routes.py`:
- Executa `ss -tlnp` i identifica tots els ports TCP escoltant al sistema
- Llegeix `/proc/PID/cmdline` per identificar el nom real del procés (dashboard.py, agent_http_bridge, etc.)
- Mapa de ports coneguts `_KNOWN_PORTS` (MongoDB :27017, MySQL :3306, PostgreSQL :5432, etc.)
- Retorna llista de dicts: `{port, pid, process, name, address, known, service_type}`
- S'inclou a `/api/status` com a clau `_system`

**Frontend:**
- Visio overview: mostra nombre de ports oberts i quants són coneguts
- Repos tab: nova secció "Sistema" amb tots els serveis detectats (icona verd si conegut, gris si no)
- CSS: `.sys-svc`, `.sys-svc-header`, `.sys-svc-name`, `.sys-svc-port`, `.sys-svc-pid`

### ✅ [RESOLT 2026-05-16] Fix #14 — Wizard es saltava secrets (doble enviament)

**Causa-arrel exacta:** `submitWizardResponse()` a `templates.py` enviava el missatge
WebSocket sense deshabilitar els botons. Un doble clic (o doble Enter al camp de secret)
enviava dos `wizard_response`, avançant dues passes del wizard d'un sol cop. La passa
intermèdia semblava "saltada". En tornar enrere, `_wizard_back()` treia la clau de
`collected_secrets` i la mostrava — per això "al tornar enrera sí que surt".

**Fix:** Flag `_wizardProcessing` a `submitWizardResponse()`. En enviar, deshabilita
tots els botons del wizard i l'input. `renderWizardStep()` reseteja el flag quan
arriba un nou pas. Segon clic/Enter és ignorat.

### ✅ [RESOLT 2026-05-16] AUTO_GENERATED_KEYS — Claus auto-generables mai al wizard

Nou set `AUTO_GENERATED_KEYS` a `universal_repo_agent_v5.py`:
`ENCRYPTION_KEY`, `JWT_SECRET`, `SECRET_KEY`, `DJANGO_SECRET_KEY`, `NEXTAUTH_SECRET`

`_analyze_repo_secrets()` les genera automàticament amb `_auto_generate_key()`:
- `ENCRYPTION_KEY`: `cryptography.fernet.Fernet.generate_key()`
- `NEXTAUTH_SECRET`: `openssl rand -base64 32` (fallback: `secrets.token_bytes(32)`)
- Altres: `secrets.token_urlsafe(32)`

Es guarden al cache automàticament i **mai** apareixen al wizard.

### ✅ [RESOLT 2026-05-16] Agent output streaming al xat del dashboard

**Causa-arrel:** `print()` de Python fa buffering quan stdout és un pipe (no TTY).
El subprocess de l'agent no enviava línies fins que el buffer s'omplia o el procés
acabava. L'usuari veia "Muntant..." sense progrés.

**Fix:** `_launch_agent()` a `chat.py`:
- Afegit flag `-u` (unbuffered) a la comanda Python
- `select.select()` amb timeout 200ms per llegir stdout sense bloquejar
- Buffer intermedi (`out_buf`) amb flush cada 200ms encara que no arribi `\n`
- Events `agent_output` enviats via `asyncio.run_coroutine_threadsafe()`

### ✅ [RESOLT 2026-05-16] Container Docker auto-provisioning per Supabase→local

Quan l'usuari tria Supabase→local al wizard, `_finalize_wizard()` ara crea el
contenidor Docker PostgreSQL automàticament:
- Comprova si `agent-postgres` existeix (el crea si no)
- Espera health check (fins a 60s)
- Actualitza el cache de secrets amb la URL de connexió local
- Mostra línia al resum: "🗄️ PostgreSQL local creat al port 5432"
- El contenidor apareix a `/api/status` → `_databases` i a la pestanya Databases

### ✅ [RESOLT 2026-05-16] Telemetria de reparació + historial

- `__REPAIR_EVENT__=<json>`: events estructurats al log de l'agent per cada etapa
  de reparació (stage, command, error_type, repo_name)
- `repair_history.jsonl`: historial de reparacions a `~/.universal-agent/repair_history.jsonl`
- KB de reparació (`repair/kb.py`): entrades ara guarden `repo_name`
- Nou endpoint `/api/repair-history` al dashboard (chat_routes.py)

### ✅ [RESOLT 2026-05-16] Router reconeix rutes locals

`_URL_RE` a `bartolo_router.py` ampliada per detectar rutes locals:
`~?/[/\w.\-]+` (ex: `/home/usuari/Projects/wa-desk`, `~/projecte`)
El prompt L2 distingeix `munta_repo` (URL o ruta local) vs `start_servei` (nom).

### ✅ [RESOLT 2026-05-16] Workspace del wizard per defecte = DEFAULT_WORKSPACE

Abans el wizard usava `~/Projects/agent-workspace` per defecte però el dashboard
i la pestanya Repos usen `DEFAULT_WORKSPACE` (`~/universal-agent-workspace`).
Els serveis muntats no apareixien a Repos perquè estaven a un workspace diferent.
Fix: `str(Path(wiz.workspace or str(DEFAULT_WORKSPACE)).expanduser())`

### ✅ [RESOLT 2026-05-17] Fix #15 — `[` (test) rebutjat pel validador

La comanda de reparació del symlink craco (`[ -f node_modules/.bin/craco ] && ...`)
era rebutjada perquè `[` no estava a `SAFE_COMMAND_PREFIXES`.
Fix: afegit `"["` a la whitelist de `validator.py`.

### ✅ [RESOLT 2026-05-17] Etiquetatge de BDs amb nom del repo

Les bases de dades Docker al dashboard ara mostren a quin repo pertanyen.
- `_container_owners.json` al workspace: mapeig `{container_name: repo_name}`
- `_finalize_wizard()` a `chat.py` guarda el mapeig després de crear contenidors
- `api_status()` a `repos_routes.py` inclou `repo` a cada entrada de BD
- Frontend `renderRepos()` mostra `[repo_name]` en verd al costat del nom del contenidor

### ✅ [RESOLT 2026-05-17] Fix #16 — Missatges del xat desapareixien al canviar de pestanya

**Causa-arrel:** En canviar de pestanya, el navegador suspèn el WebSocket. En tornar,
el dashboard es reconecta i rep `history` del servidor. Si el servidor retorna buit,
`chat-messages.innerHTML = ''` esborrava tots els missatges.
**Fix:** Buffer `_localMessages` al JS del dashboard. Totes les funcions que manipulen
missatges (`addChatMessage`, `finishMessage`, `selectThread`, `deleteThread`, clear-all)
sincronitzen el buffer. El handler `history` preserva missatges locals si el servidor
retorna buit.

### ✅ [RESOLT 2026-05-17] `bartolo-goal.mjs` — Automatització Playwright del muntatge

Script Node.js que automatitza el muntatge de repos via el dashboard :9999:
- Llegeix `.env.local` (format `KEY=VALUE`), verifica 9 claus requerides
- Pobla la cache de secrets (`~/.universal-agent/secrets.json`)
- Obre Chromium, navega al dashboard, crea xat nou
- Envia `munta <repo_path>`, gestiona wizard pas a pas (workspace, secrets, cloud_choice, confirm)
- Captura tota la sessió: transcript markdown (sanititzat), screenshots cada 60s, meta.json
- Sanitització: JWTs, claus Supabase, strings alta entropia → `<REDACTED>`
- Timeout 6h, detecció de finalització per patrons + 15s quiescència
- Sortida a `runs/<timestamp>/`

## Problemes coneguts pendents

Cap problema obert de prioritat alta o mitjana.

### Limitacions conegudes (no bugs, sinó restriccions de disseny)

- **Elixir/Phoenix**: problemes de compilació amb dependències antigues (ex: `jose`) en versions modernes d'Elixir. No és un bug de l'agent sinó incompatibilitat upstream.
- **.NET**: detector implementat però no provat E2E (SDK no instal·lat al sistema).
- **Monorepos**: detecció OK, però l'execució completa no s'ha validat amb casos reals.
- **Debugger Anthropic fallback**: requereix API key configurada. Sense ella, només Ollama.
- **`choose_service_verify`**: ajusta la URL de verificació i afegeix `PORT=` a la comanda, però si l'app ignora `PORT=` i usa un port hardcodejat, el smoke test fallarà.
- **is_node_library**: el scoring actual (llindar 2) és conservador. Poden aparèixer falsos positius/negatius.

## Millores futures descobertes

### ✅ [RESOLT 2026-05-04] systemd user service per al bridge
`agent-bridge.service` activat i enabled. El bridge sobreviu als reboots.
Afegits `StandardOutput=journal` i `StandardError=journal` per tenir logs centralitzats.
Script `start-bartolo.sh` creat per arrancar Ollama + bridge + open-webui i executar bartolo-doctor.
Logs: `journalctl --user -u agent-bridge -f`

## Convencions de codi descobertes

### Sistema de scoring per heurístiques ambigues
Per decisions binàries amb senyals sorollosos (library vs app, Emergent vs generic...),
usar puntuació numèrica amb llindar en comptes de regles `if/elif` encadenades.
Avantatge: fàcil d'ajustar pesos sense reescriure la lògica. Vegeu `is_node_library()`.

### Tests unitaris al costat del codi
Fitxers `test_<nom>.py` al root del projecte. Execució: `python3 test_<nom>.py`.
Cap framework extern — `sys.exit(1)` si hi ha fallades. Exemple: `test_node_library_detection.py`.

### Backups `.bak_<motiu>` abans d'editar fitxers grans
Abans d'editar `universal_repo_agent_v5.py` (4060 línies), crear còpia amb
`cp universal_repo_agent_v5.py universal_repo_agent_v5.py.bak_<motiu>`.
Permet revertir manualment si cal sense dependre de git.

## Workflow recomanat per a canvis

```bash
# 1. Branca
git checkout -b fix/<nom-curt>

# 2. Editar
# (Claude Code edita aquí)

# 3. Test ràpid amb bench.sh
./bench.sh quick   # mode ràpid: 6 repos, ~1.5 minuts
./bench.sh         # mode complet: 11 repos, ~5 minuts

# 4. Si tot OK
git add -A && git commit -m "..."
git push origin fix/<nom-curt>
```

## Comandes de control habituals

```bash
# Estat del sistema
systemctl --user status agent-bridge   # bridge
curl http://localhost:9090/health      # bridge HTTP
curl http://localhost:11434/api/tags   # Ollama
docker ps                              # OpenWebUI + BDs

# Reiniciar després d'editar el bridge
systemctl --user restart agent-bridge
# (o si no està com a service)
pkill -f agent_http_bridge.py
python3 ~/universal-agent/agent_http_bridge.py &

# Reiniciar després d'editar la tool
# Cal refer la tool a OpenWebUI manualment via UI (Settings → Tools)
docker restart open-webui

# Logs
tail -f ~/universal-agent-workspace/.agent_logs/*.log
journalctl --user -u agent-bridge -f
docker logs -f open-webui

# Aturar tots els repos arrencats
python3 ~/universal-agent/universal_repo_agent_v5.py --stop all
```

## Què NO fer

- ❌ No reescriure `universal_repo_agent_v5.py` des de zero — el codi és sòlid
- ❌ No tocar el validator (`validate_command`, `SAFE_COMMAND_PREFIXES`, `DANGEROUS_PATTERNS`) sense passar `bench.sh` després
- ❌ No introduir Redis, cues, microserveis — overengineering per al cas d'ús
- ❌ No esborrar `dashboard.py` — és el pla B sense LLM
- ❌ No afegir dependencies a la tool d'OpenWebUI — només `urllib` (biblioteca estàndard)
- ❌ No carregar/imprimir secrets de `~/.universal-agent/secrets.json` als logs

## Què SÍ fer

- ✅ Editar amb canvis quirúrgics (str_replace, no rewrite massiu)
- ✅ Crear backups `.bak_<motiu>` abans d'editar fitxers grans
- ✅ Validar amb `bench.sh quick` després de canvis al validator/planner
- ✅ Mantenir compatibilitat enrere — el bridge i la tool tenen usuaris reals (Bartolo)
- ✅ Documentar bugs trobats a `INFORME_BATERIA.md`
- ✅ Usar el sistema de patches idempotents (`patch_*.py`) si una correcció és complexa

## Persones / mentalitat

L'usuari és l'autor del projecte. Treballa en català per defecte. No vol overengineering. Vol fiabilitat per sobre de funcionalitats noves. Té una bona base d'enginyeria però aprecia opinions honestes sobre què val la pena i què no.
