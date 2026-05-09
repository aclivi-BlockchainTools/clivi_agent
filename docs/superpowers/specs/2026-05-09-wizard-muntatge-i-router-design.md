# Disseny: Wizard de Muntatge (A+B) + Router Generalista (D)

**Data**: 2026-05-09  
**Estat**: Pendent d'implementació  
**Scope**: A — Gestió claus API | B — Wizard muntatge pas a pas | D — Router multi-intenció

---

## Part 1 — Wizard de Muntatge (A + B)

### Problema

Bartolo llança el muntatge d'un repo sense preguntar res: path de destí, secrets necessaris, preferència Docker. Si falta una clau d'API (ex. `ANTHROPIC_API_KEY`), falla en silenci o dona un error críptic.

### Solució

**Wizard al bridge** — nou estat de sessió `_WIZARDS` al bridge, paral·lel als `_JOBS` existents. La tool orquestra el diàleg entre l'usuari i el wizard; el bridge manté l'estat entre passos.

---

### Arquitectura

```
[Usuari xat]
     ↕
[OpenWebUI + LLM]  ← tool crida inicia_muntatge / respon_wizard
     ↕
[Bridge :9090]
     ├── POST /wizard/start          → crea wizard, retorna 1a pregunta
     ├── POST /wizard/step           → rep resposta, retorna seg. pregunta o job_id
     └── GET  /wizard/<id>           → estat actual

_WIZARDS: dict[wizard_id → WizardState]   (thread-safe, max 20, igual que _JOBS)
```

---

### Flux de passos (state machine)

```
ANALYZE → CONFIRM_PATH → COLLECT_SECRETS → DOCKER_PREF → SUMMARY → LAUNCHING
    ↓ (si rapid=True o usuari diu "ràpid"/"defaults"/"munta i prou")
LAUNCHING  (salta tots els passos)
```

| Pas | Pregunta | Default si no respon |
|-----|----------|----------------------|
| `ANALYZE` | (intern, no pregunta) | — |
| `CONFIRM_PATH` | "On muntes? [~/universal-agent-workspace/NOM]" | workspace/NOM |
| `COLLECT_SECRETS` | "Falta `VAR_X`. Introdueix el valor (o prem Enter per deixar-la buida):" | buit |
| `DOCKER_PREF` | "Vols usar Docker si és possible? [Sí/No/Auto]" | Auto |
| `SUMMARY` | Resum formatat + "Procedir? [Sí/Cancel·lar]" | Sí |
| `LAUNCHING` | — llança job async, retorna job_id → polling fins a fi | — |

**Detecció de "ràpid"**: si `rapid=True` o la resposta de l'usuari conté `ràpid`, `rapid`, `defaults`, `munta i prou`, `just do it`, el wizard salta directament a `LAUNCHING` amb tots els defaults.

---

### Model de dades del wizard

```python
WizardState = {
    "id": str,                    # 8 chars hex
    "repo_url": str,
    "step": str,                  # nom del pas actual
    "answers": {                  # respostes acumulades
        "mount_path": str,
        "secrets": dict[str, str],
        "docker_pref": str,       # "yes" | "no" | "auto"
    },
    "pending_secrets": list[str], # claus que encara falten
    "analysis_summary": str,      # resum llegible del stack detectat
    "job_id": Optional[str],
    "created_at": float,
    "rapid": bool,
}
```

---

### Pas `ANALYZE` (intern)

El bridge fa una anàlisi lleugera del repo **abans** de fer cap pregunta:
- `git ls-remote <url>` per verificar que existeix i és accessible
- `git clone --depth 1 --no-checkout <url>` + `git ls-tree HEAD` per llegir fitxers de config sense descarregar codi (ràpid, no ocupa espai permanent)
- Detecta stack, ports probables i secrets requerits
- Genera `analysis_summary` llegible: "Stack: Node.js + Vite. Port: 5173. Secrets detectats: ANTHROPIC_API_KEY, OPENAI_API_KEY."

Si el repo és privat o no accessible, el wizard informa i cancel·la.

---

### Gestió de secrets (part A)

1. Bridge carrega `~/.universal-agent/secrets.json` (via `load_secrets_cache()` ja existent a l'agent)
2. Secrets que ja hi són → saltar-los al wizard
3. Secrets que falten → demanar-los un per un al pas `COLLECT_SECRETS`
4. El bridge desa al `secrets.json` amb `chmod 600` (via `save_secrets_cache()` ja existent)
5. Injectar al `.env` del repo via `inject_secrets_into_env()` ja existent

**Nota de seguretat**: els valors de les claus passen pel xat (OpenWebUI → tool → bridge). El sistema és local, però l'usuari n'és conscient. Els logs del bridge no registren els valors de les claus.

---

### Endpoint `POST /wizard/start`

**Request:**
```json
{ "repo_url": "https://github.com/...", "rapid": false }
```

**Response (primer pas):**
```json
{
  "wizard_id": "a1b2c3d4",
  "step": "CONFIRM_PATH",
  "question": "He detectat: Stack Node.js + Vite. Port: 5173.\n\nOn vols muntar el repo?\n[Enter per defecte: ~/universal-agent-workspace/wavebox-mail]",
  "analysis_summary": "Stack: Node.js + Vite. Port 5173. Secrets: cap.",
  "can_skip": true
}
```

---

### Endpoint `POST /wizard/step`

**Request:**
```json
{ "wizard_id": "a1b2c3d4", "answer": "ràpid" }
```

**Response (pregunta següent):**
```json
{
  "wizard_id": "a1b2c3d4",
  "step": "COLLECT_SECRETS",
  "question": "Falta ANTHROPIC_API_KEY. Introdueix el valor (o Enter per deixar-la buida):",
  "done": false
}
```

**Response (wizard completat → llança job):**
```json
{
  "wizard_id": "a1b2c3d4",
  "step": "LAUNCHING",
  "done": true,
  "job_id": "85a5138d"
}
```
Quan `done: true`, la tool entra en mode polling (igual que `_wait_for_job` existent) i retorna el resultat final.

---

### Funcions noves a la tool (v2.9)

```python
def inicia_muntatge(self, repo_url: str, rapid: bool = False) -> str:
    """
    Inicia el muntatge guiat d'un repo amb wizard interactiu pas a pas.
    Si rapid=True (o l'usuari diu 'ràpid'/'defaults'), salta el wizard i usa defaults.
    Substitueix executa_repo_async per a repos nous.
    :param repo_url: URL del repo (GitHub, GitLab, Bitbucket) o ruta local a ZIP.
    :param rapid: Si True, salta el wizard i usa tots els valors per defecte.
    """

def respon_wizard(self, wizard_id: str, resposta: str) -> str:
    """
    Envia la resposta de l'usuari al pas actual del wizard i retorna la pregunta
    següent. Quan el wizard acaba, llança el job i espera el resultat final.
    :param wizard_id: identificador retornat per inicia_muntatge.
    :param resposta: resposta de l'usuari al pas actual.
    """
```

`executa_repo_async` es manté per compatibilitat però el seu docstring indicarà que el nou flux recomanat és `inicia_muntatge`.

---

### Diagrama de seqüència

```
Usuari          LLM (Bartolo)         Tool              Bridge
  |                   |                 |                  |
  | "munta X"         |                 |                  |
  |──────────────────>|                 |                  |
  |                   | inicia_muntatge |                  |
  |                   |────────────────>| POST /wizard/start
  |                   |                 |─────────────────>|
  |                   |                 |   {wizard_id, q1}|
  |                   |  "Stack: Node.. |<─────────────────|
  |                   |  On muntes?"    |                  |
  |<──────────────────|                 |                  |
  | "/home/usuari/dev"|                 |                  |
  |──────────────────>|                 |                  |
  |                   | respon_wizard   |                  |
  |                   |────────────────>| POST /wizard/step
  |                   |                 |─────────────────>|
  |                   |                 |   {q2: secrets}  |
  |                   |  "Falta ANTHRO" |<─────────────────|
  |<──────────────────|                 |                  |
  | "sk-ant-xxx"      |                 |                  |
  |──────────────────>|                 |                  |
  |                   | respon_wizard   |                  |
  |                   |────────────────>| POST /wizard/step
  |                   |                 |─────────────────>|
  |                   |                 | {done, job_id}   |
  |                   |                 | [polling...]     |
  |                   |                 |<─────────────────|
  |   "✅ Muntat!"    |                 |                  |
  |<──────────────────|                 |                  |
```

---

---

## Part 2 — Router Generalista (D) — Proposta i Esquema

> Aquesta part és una proposta de disseny per a implementació futura. No forma part del pla immediat.

### Problema

Bartolo rep qualsevol tipus de pregunta però només sap "muntar repos". "Quina hora és?", "cerca X a internet", "quina versió té el sistema?" → respostes lentes, poc precises o innecessàriament complexes.

### Arquitectura proposada (3 capes)

```
[Usuari]
    ↓
[OpenWebUI + Model base (qwen2.5:14b)]
    ↓ system prompt: "Ets un router. Classifica i usa la tool correcta."
    ↓
[Tool: classifica_i_resol(text, context)]
    ↓
[Bridge Router — /router/dispatch]
    ├── INTENT: temps/data         → resposta directa (no LLM, Python datetime)
    ├── INTENT: cerca_web          → DuckDuckGo (tool existent)
    ├── INTENT: info_sistema       → /exec_info (endpoint existent)
    ├── INTENT: munta_repo         → /wizard/start (nou)
    ├── INTENT: gestio_docker      → /update_container o /exec_info
    ├── INTENT: debug_error        → agent_debug (futur)
    └── INTENT: conversa_general   → Ollama directe (qwen2.5:14b o 7b)
```

### Classificació d'intencions

**Nivell 1 — Regles deterministiques** (ràpid, sense LLM):
| Patró | Intent |
|-------|--------|
| `quina hora`, `what time`, `fecha` | `temps_data` |
| `docker ps`, `docker inspect`, `quina versió` | `info_sistema` |
| `munta`, `instal·la`, `clona`, `github.com/` | `munta_repo` |
| `actualitza open-webui`, `docker pull` | `gestio_docker` |

**Nivell 2 — Classificació lleugera per LLM** (si les regles no encaixen):
- Model: `qwen2.5:7b` si disponible a Ollama, sinó el model actiu actual. Crida directa a `http://localhost:11434/api/generate` (no via OpenWebUI).  
- Prompt: "Classifica en: INFO_SISTEMA / MUNTA_REPO / CERCA_WEB / CONVERSA. Respon amb una sola paraula."
- Timeout: 3s. Si falla → `CONVERSA` per defecte

**Nivell 3 — Execució per intent:**
- `INFO_SISTEMA` → `/exec_info` (síncron, < 2s)
- `MUNTA_REPO` → `/wizard/start` (async + polling)
- `CERCA_WEB` → DuckDuckGo tool existent
- `CONVERSA` → Ollama API directe (streaming si possible)
- `TEMPS_DATA` → resposta Python sense LLM

### Model per intenció

| Intent | Model recomanat | Raó |
|--------|----------------|-----|
| `temps_data` | cap (Python) | Trivial, 0ms |
| `info_sistema` | cap (shell) | Determinista |
| `munta_repo` | qwen2.5:14b | Necessita raonament per wizard |
| `cerca_web` | qwen2.5:7b | Sintetitza resultats |
| `conversa_general` | qwen2.5:14b | Qualitat màxima |
| `debug_error` | qwen2.5:14b o Claude Sonnet | Raonament complex |

### Execució paral·lela (futur)

Per queries que toquen múltiples intents ("cerca documentació de fastapi i munta el repo oficial"):
- Bridge llança els dos agents en paral·lel (threads/asyncio)
- Recull les respostes i les fusiona
- Timeout global: 30s

### Nous components

1. **`bartolo_router.py`** — lògica de classificació (regles + LLM petit)
2. **`/router/dispatch` endpoint** al bridge — rep text + context, retorna resposta o job_id
3. **`classifica_i_resol(text)` a la tool** — funció única d'entrada per a Bartolo "generalista"
4. **System prompt actualitzat** a OpenWebUI — "Usa sempre `classifica_i_resol` per qualsevol petició"

### Fases d'implementació suggerides

- **Fase 1** (immediata): wizard A+B (aquesta spec)
- **Fase 2**: regles deterministiques + `/router/dispatch` bàsic
- **Fase 3**: classificació per LLM petit + `classifica_i_resol` a la tool
- **Fase 4**: execució paral·lela multi-agent

---

## Fitxers afectats (A+B)

| Fitxer | Canvis |
|--------|--------|
| `agent_http_bridge.py` | `_WIZARDS` dict, `/wizard/start`, `/wizard/step`, `/wizard/<id>` |
| `openwebui_tool_repo_agent.py` | `inicia_muntatge()`, `respon_wizard()`, v2.9 |
| `universal_repo_agent_v5.py` | Cap canvi — reutilitza `load_secrets_cache`, `save_secrets_cache`, `inject_secrets_into_env` |

## Fitxers NO afectats

- `dashboard.py` — no canvia
- `universal_repo_agent_v5.py` — l'agent s'executa igual, el wizard només configura els paràmetres que li passa el bridge

## Tests

- `test_wizard_flow.py` — simula els 5 passos amb respostes mock
- `test_wizard_rapid.py` — verifica que `rapid=True` salta directament a LAUNCHING
- `test_secrets_skip.py` — verifica que secrets ja presents al cache es salten
