# Bartolo / Universal Repo Agent — Context per a Claude Code

## Què és aquest projecte

Sistema d'arrencada universal de repositoris a Ubuntu. Clona repos de GitHub/GitLab/Bitbucket (o ZIPs locals), detecta el stack, instal·la dependències i arrenca els serveis automàticament. Inclou integració amb OpenWebUI (xat amb LLM Qwen 14B local) per controlar-ho via llenguatge natural.

L'usuari final coneix el sistema com **"Bartolo"** (el nom del model d'OpenWebUI configurat).

## Arquitectura actual (3 capes)

```
[Usuari] → OpenWebUI :3001 → Tools (function calling) → agent_http_bridge.py :9090 → universal_repo_agent_v5.py
                                                       ↓
                                              dashboard.py :9999 (control alternatiu sense LLM)
```

- **OpenWebUI**: xat amb Qwen2.5-coder:14b via Ollama, function calling nadiu
- **Bridge HTTP** (`agent_http_bridge.py`): exposa l'agent com REST API al port 9090
- **Agent CLI** (`universal_repo_agent_v5.py`): el cervell — 3892 línies, validator + planner + executor + preflight + plan B + success KB + 12 detectors
- **Dashboard** (`dashboard.py`): UI web a 9999, sense dependències extra
- **Tool OpenWebUI** (`openwebui_tool_repo_agent.py`): client Python pur (urllib) que el container OpenWebUI carrega

## Fitxers principals

| Fitxer | Què fa | Línies |
|---|---|---|
| `universal_repo_agent_v5.py` | Agent CLI, cor del sistema | 3892 |
| `agent_http_bridge.py` | REST API al port 9090, jobs async, shell exec amb token, upload ZIP, wizard, router dispatch | 1408 |
| `openwebui_tool_repo_agent.py` | Tool per OpenWebUI (v2.3, 10 funcions) | 403 |
| `openwebui_tool_web_search.py` | Tool DuckDuckGo per cerques | 112 |
| `bartolo_router.py` | Classificador d'intencions L1 (regex) + L2 (LLM) — 8 intents | 252 |
| `bartolo_init.py` | CLI interactiva per muntar repos sense flags (reutilitza l'agent) | 168 |
| `agents/success_kb.py` | Registre de plans que han funcionat per stack (KB d'èxits) | 83 |
| `agents/debugger.py` | Debugger intel·ligent amb KB de reparacions + Anthropic fallback | — |
| `dashboard.py` | UI web :9999 | 254 |
| `bench.sh` | Bateria de proves automatitzada (10 repos) | 83 |
| `stress_test.sh` | Bateria d'estrès amb repos complexos (7 repos, detecció) | 85 |
| `setup_ubuntu.sh` | Instal·lador Node/Docker/Ollama/qwen2.5-coder:14b | 190 |
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

## Problemes resolts

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
- `detect_deno_service()`: `deno.json`, `deno.jsonc`, `import_map.json`
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

Implementat a:
- `analyze_repo()`: detecta cloud → afegeix local fallback a `db_hints`, guarda a `cloud_services`
- `build_db_provision_steps()`: resol cloud → local abans de provisionar
- `print_final_summary()`: secció `☁️ Serveis cloud` + etiqueta `supabase (→ postgresql local)`
- Bridge wizard: `_DB_ENV_PATTERNS` inclou supabase, SUMMARY/CONFIRM_PATH mostren fallback

## Problemes coneguts pendents

Cap problema obert de prioritat alta o mitjana.

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
i `analyze_repo()` salta la detecció de serveis. Impacte: turborepo 15→0 serveis, deno 59→0,
phoenix 4→0, lerna 2→0.

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
i afegeix pas `pnpm build`/`yarn build`/`npm run build` entre install i run. Next.js sense
script build → `npx next build`.

**Migrations Node/PHP:** Prisma (`prisma/schema.prisma` → `npx prisma migrate deploy`),
Knex (`knexfile.js` → `npx knex migrate:latest`), Sequelize (`.sequelizerc` →
`npx sequelize-cli db:migrate`), Laravel (`php artisan migrate --force`).
Categoria `"migrate"` ordena 1 (després d'install=0, abans de run=4). `critical=False`.

**DB Health + ordre:** `"db": -1` a `_CATEGORY_ORDER` (contenidors s'arrenquen primer).
`verify_step` activat per `category in ("run", "db")`. Health check `nc -z` inline al
`docker run` (fins a 30 intents de 2s). Rollback atura contenidors en cas d'error.

**pnpm/yarn sense sudo:** `npm install -g pnpm --prefix ~/.local` (no requereix password).

**KB d'èxits:** `_stack_key()` a `agents/success_kb.py` inclou `repo_name` a la clau hash.
Abans dos repos Node amb `package.json` compartien pla. Ara clau tipus `repo::stack`.

### ✅ [RESOLT 2026-05-10] bartolo-doctor.sh: 2 bugs menors
1. **Pas 2 — `/proc/PID/environ` Permission denied:** El codi ja ho gestiona correctament
   (`2>/dev/null` + fallback a token buit + missatge informatiu). No cal canvi.
2. **Pas 7 — `docker port` parsing fràgil amb IPv6:** `head -1 | cut -d: -f2` trencava si
   la línia IPv6 (`[::]:3000`) sortia primer. **Fix:** `grep -oP '0\.0\.0\.0:\K\d+'` per
   extreure només el port de la línia IPv4.

## Millores futures descobertes

### ✅ [RESOLT 2026-05-04] systemd user service per al bridge
`agent-bridge.service` activat i enabled. El bridge sobreviu als reboots.
Afegits `StandardOutput=journal` i `StandardError=journal` per tenir logs centralitzats.
Script `start-bartolo.sh` creat per arrancar Ollama + bridge + open-webui i executar bartolo-doctor.
Logs: `journalctl --user -u agent-bridge -f`

### is_node_library: possibles casos límit
El scoring actual (llindar 2) és conservador. Si apareixen falsos positius (apps
marcades com library) o falsos negatius (libs que passen), ajustar els pesos a
`is_node_library()` i afegir casos a `test_node_library_detection.py`.

## Convencions de codi descobertes

### Sistema de scoring per heurístiques ambigues
Per decisions binàries amb senyals sorollosos (library vs app, Emergent vs generic...),
usar puntuació numèrica amb llindar en comptes de regles `if/elif` encadenades.
Avantatge: fàcil d'ajustar pesos sense reescriure la lògica. Vegeu `is_node_library()`.

### Tests unitaris al costat del codi
Fitxers `test_<nom>.py` al root del projecte. Execució: `python3 test_<nom>.py`.
Cap framework extern — `sys.exit(1)` si hi ha fallades. Exemple: `test_node_library_detection.py`.

### Backups `.bak_<motiu>` abans d'editar fitxers grans
Abans d'editar `universal_repo_agent_v5.py` (3287 línies), crear còpia amb
`cp universal_repo_agent_v5.py universal_repo_agent_v5.py.bak_<motiu>`.
Permet revertir manualment si cal sense dependre de git.

## Workflow recomanat per a canvis

```bash
# 1. Branca
git checkout -b fix/<nom-curt>

# 2. Editar
# (Claude Code edita aquí)

# 3. Test ràpid amb bench.sh
./bench.sh quick   # mode ràpid: 5 repos, ~10 minuts
./bench.sh         # mode complet: 10 repos, ~30 minuts

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
