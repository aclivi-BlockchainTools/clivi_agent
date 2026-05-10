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
- **Agent CLI** (`universal_repo_agent_v5.py`): el cervell — 2786 línies, validator + planner + executor
- **Dashboard** (`dashboard.py`): UI web a 9999, sense dependències extra
- **Tool OpenWebUI** (`openwebui_tool_repo_agent.py`): client Python pur (urllib) que el container OpenWebUI carrega

## Fitxers principals

| Fitxer | Què fa | Línies |
|---|---|---|
| `universal_repo_agent_v5.py` | Agent CLI, cor del sistema | 2960 |
| `agent_http_bridge.py` | REST API al port 9090, jobs async, shell exec amb token, upload ZIP, wizard, router dispatch | 1330 |
| `openwebui_tool_repo_agent.py` | Tool per OpenWebUI (v2.3, 10 funcions) | 396 |
| `openwebui_tool_web_search.py` | Tool DuckDuckGo per cerques | 112 |
| `dashboard.py` | UI web :9999 | 254 |
| `bench.sh` | Bateria de proves automatitzada (10 repos) | 83 |
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

## Problemes coneguts pendents (PRIORITAT ALTA → BAIXA)

### 1. [MITJA] Repos-col·lecció generen 60+ passos
Vegeu casos #07, #09, #10 a INFORME_BATERIA. Necessari un pre-classifier que detecti "és un index, no una app" i demani tria.

### 2. [MITJA] Workspace duplicat: `universal-agent-workspace` vs `Projects/agent-workspace`
Descobert 2026-05-10 durant test E2E. Hi ha 2 workspaces al sistema i els repos es dispersen
entre tots dos. Cal triar-ne un d'oficial i migrar l'altre, o fer que el bridge i l'agent
usin el mateix consistentment.

### 3. [BAIXA] `diagnose_error_with_model` + `ask_model_for_repair` són dues crides desconnectades
El "debugger" actual no té memòria entre intents ni context del repo. Vegeu el patch `debugger_patch.py` que ja vam dissenyar (cal aplicar).

### 4. [BAIXA] Smoke tests només per stack Emergent
`run_smoke_tests()` fa servir paths hardcoded `/api/`, `/api/health`. Cal generalitzar per stack detectat.

### bartolo-doctor.sh: 2 bugs menors (Bloc D, sessió futura)
- Pas 2: `/proc/PID/environ` Permission denied si bridge no és fill del shell
  (warning confús, ja funciona silenciosament — fix: millorar el missatge)
- Pas 7: mostra `localhost:3001` però OpenWebUI escolta al `:3000`

## Millores futures descobertes

### ✅ [RESOLT 2026-05-04] systemd user service per al bridge
`agent-bridge.service` activat i enabled. El bridge sobreviu als reboots.
Afegits `StandardOutput=journal` i `StandardError=journal` per tenir logs centralitzats.
Script `start-bartolo.sh` creat per arrancar Ollama + bridge + open-webui i executar bartolo-doctor.
Logs: `journalctl --user -u agent-bridge -f`

### bench.sh no passa --non-interactive
El mode `analyze` del bench falla repos que demanen secrets o deps del sistema
(vite, nextjs, gradio, go-example, fastapi-mongo) per EOF en lectura interactiva.
Resultat: 5/10 falsos negatius al bench complet. Fix: afegir `--non-interactive`
a la crida `analyze` de bench.sh (branca `chore/bench-non-interactive`).

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
Abans d'editar `universal_repo_agent_v5.py` (2786 línies), crear còpia amb
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
