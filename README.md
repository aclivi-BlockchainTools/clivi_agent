# Universal Repo Agent v5 — Guia en català

Un agent Python que clona, analitza i arrenca repositoris de GitHub/GitLab/Bitbucket
a la teva màquina Ubuntu, utilitzant **Ollama** + **qwen2.5-coder:14b** per refinar
el pla d'execució i diagnosticar errors.

Inclou:
- 🟢 Detector específic per **repositoris d'Emergent** (FastAPI + React + MongoDB)
- 🐳 Mode **`--dockerize`** — tot el stack aïllat en contenidors
- 🔑 **Caché de secrets** (`EMERGENT_LLM_KEY`, `OPENAI_API_KEY`, `STRIPE_*`…) a `~/.universal-agent/secrets.json`
- 🧪 **Smoke tests automàtics** després d'arrencar (HTTP + pytest)
- 🎨 **Dashboard web** (`dashboard.py`) per veure i controlar repos via navegador
- 🧭 **Router d'intencions** (`bartolo_router.py`) L1 (regex) + L2 (LLM petit) per classificar peticions en llenguatge natural
- 🔧 **Debugger intel·ligent** (`agents/debugger.py`) amb KB persistent de reparacions + fallback a Anthropic

---

## 📦 Contingut

| Fitxer | Descripció |
|---|---|
| `openwebui_tool_repo_agent.py` | Tool per OpenWebUI: activar l'agent via xat |
| `openwebui_tool_web_search.py` | Tool per OpenWebUI: cerca a Internet via DuckDuckGo |
| `OPENWEBUI_SETUP.md` | Guia d'integració amb OpenWebUI (routing automàtic) |
| `setup_ubuntu.sh` | Script d'instal·lació de totes les dependències a Ubuntu |
| `universal_repo_agent_v5.py` | L'agent CLI |
| `agent_http_bridge.py` | Bridge HTTP (API REST al :9090) amb wizard, router dispatch, jobs async |
| `bartolo_router.py` | Classificador d'intencions L1 (regex) + L2 (LLM) — 8 intents, 0ms L1 |
| `agents/debugger.py` | Debugger intel·ligent amb KB de reparacions + Anthropic fallback |
| `dashboard.py` | Dashboard web a `http://localhost:9999` (zero dependències) |
| `bartolo_prompts.md` | Catàleg de prompts naturals que entén Bartolo |
| `bench.sh` | Bateria de proves automatitzada (10 repos) |
| `README.md` | Aquesta guia |

---

## 1) Instal·lació inicial (només una vegada)

```bash
chmod +x setup_ubuntu.sh
./setup_ubuntu.sh          # instal·lació bàsica (recomanat)
# opcions:
# ./setup_ubuntu.sh --full         → afegeix Go, Rust, Ruby, PHP, Java, Maven
# ./setup_ubuntu.sh --no-docker    → salta instal·lació de Docker
# ./setup_ubuntu.sh --no-ollama    → salta instal·lació d'Ollama i model
```

Instal·la:
- Paquets base (`git`, `curl`, `python3`, `python3-venv`, `build-essential`, …)
- **Node.js 20 LTS** + **Yarn** (via corepack)
- **Docker Engine** + Compose (per aixecar BDs i pel mode `--dockerize`)
- **Ollama** + `qwen2.5-coder:14b` (~8–9 GB)
- Python `requests`

Després d'instal·lar Docker, **tanca i torna a obrir sessió** (o `newgrp docker`).

---

## 2) Ús bàsic

### 2.1 Repositori públic
```bash
python3 universal_repo_agent_v5.py \
    --input https://github.com/usuari/repositori.git \
    --execute
```
Sense `--execute` → només mostra el pla (dry-run).
Amb `--approve-all` → no demana confirmació pas a pas.

### 2.2 Repositori privat (GitHub/GitLab/Bitbucket)
```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxx     # o GITLAB_TOKEN / BITBUCKET_TOKEN
python3 universal_repo_agent_v5.py --input https://github.com/user/repo.git --execute
# o passant-lo per CLI: --github-token / --gitlab-token / --bitbucket-token
```

### 2.3 Carpeta local o ZIP
```bash
python3 universal_repo_agent_v5.py --input ./projecte.zip --execute
python3 universal_repo_agent_v5.py --input ./una-carpeta --execute
```

---

## 3) Repositoris d'Emergent (detecció automàtica)

Si el repo té `/backend/server.py` (FastAPI) + `/frontend/package.json` (React),
l'agent activa automàticament:

1. Mongo local (via Docker si està disponible, o apunta al mongo del host)
2. Crea `backend/.env` amb `MONGO_URL`, `DB_NAME`, `CORS_ORIGINS`, `JWT_SECRET`, `JWT_ALGORITHM`
3. Crea `frontend/.env` amb `REACT_APP_BACKEND_URL=http://localhost:8001`
4. `python3 -m venv .venv` + `pip install -r requirements.txt`
5. `yarn install` (o `npm install --legacy-peer-deps` si no hi ha yarn)
6. Arrenca `uvicorn server:app --port 8001` en background
7. Arrenca `yarn start` (port 3000) en background
8. Executa **smoke tests**: `curl /api/`, `/api/health`, `/`, + `pytest --co` si n'hi ha

```bash
python3 universal_repo_agent_v5.py \
    --input https://github.com/user/emergent-demo.git \
    --execute --approve-all
```

### Secrets: `EMERGENT_LLM_KEY` i altres
Si el repo necessita `EMERGENT_LLM_KEY`, `OPENAI_API_KEY`, `STRIPE_SECRET_KEY`, etc.,
l'agent t'ho preguntarà el primer cop i ho **desarà encriptat a `~/.universal-agent/secrets.json` (chmod 600)**.
La pròxima vegada que un repo necessiti la mateixa variable, l'agent la reutilitzarà
automàticament.

```bash
# Primer cop
python3 universal_repo_agent_v5.py --input https://github.com/user/llm-repo.git --execute
# "Detectats 1 secrets requerits: EMERGENT_LLM_KEY"
# "  EMERGENT_LLM_KEY = sk-xxxxx..."

# Segon cop amb un altre repo que també la necessiti
python3 universal_repo_agent_v5.py --input https://github.com/user/altre-repo.git --execute
# "EMERGENT_LLM_KEY reutilitzat de la caché"
```

On obtenir `EMERGENT_LLM_KEY`: al teu perfil a **emergent.sh → Profile → Universal Key**.

---

## 4) Mode `--dockerize` (recomanat si vols zero instal·lació al host)

Amb `--dockerize`, l'agent no crea venv ni fa `yarn install` al host. En canvi
**genera automàticament** un `docker-compose.agent.yml` i `Dockerfile.agent` per
backend i frontend, i aixeca tot dins de contenidors (inclòs MongoDB).

```bash
python3 universal_repo_agent_v5.py \
    --input https://github.com/user/repo.git \
    --dockerize --execute --approve-all
```

Avantatges:
- ✅ Zero "a mi em funciona" (l'entorn és idèntic per a tothom)
- ✅ Neteja amb `docker compose down -v`
- ✅ Funciona fins i tot si no tens Python o Node al host
- ✅ Aïllament total de versions

Desavantatges:
- ⚠️ La primera build és lenta (~3-5 min)
- ⚠️ Cal tenir Docker

---

## 5) Dashboard web

```bash
python3 dashboard.py                 # arrenca a http://localhost:9999
python3 dashboard.py --port 9000     # port custom
```

Al dashboard pots:
- Veure tots els repos arrencats + PIDs + estat RUNNING/STOPPED
- Clicar **📜 Logs** per veure els logs en temps real (auto-refresh 3s)
- Clicar **⏹ Stop** per aturar un repo sencer
- Llançar nous repos via formulari (amb checkboxes per `--dockerize`, `--approve-all`, etc.)

Sense dependències extres — només Python estàndard. Serveix HTML + CSS dark mode.

---

## 6) Gestió dels serveis arrencats

```bash
python3 universal_repo_agent_v5.py --status          # llista serveis + PIDs
python3 universal_repo_agent_v5.py --stop gptest     # atura un repo
python3 universal_repo_agent_v5.py --stop all        # atura tot
python3 universal_repo_agent_v5.py --logs gptest     # últims logs
```

L'agent fa servir `setsid` + `killpg` per assegurar que matar un servei també
mata tots els seus subprocessos (ex. webpack-dev-server sota `yarn start`).

---

## 7) Opcions completes

| Flag | Descripció |
|---|---|
| `--input <URL\|carpeta\|zip>` | Font del repositori |
| `--workspace <path>` | Per defecte `~/universal-agent-workspace` |
| `--model <nom>` | Model Ollama. Per defecte `qwen2.5-coder:14b` |
| `--execute` | Executa el pla |
| `--approve-all` | No demana confirmació pas a pas |
| `--dry-run` | Mostra el pla, no executa |
| `--dockerize` | **NOU** — Mode Docker Compose (tot en contenidors) |
| `--no-smoke` | **NOU** — Salta els smoke tests |
| `--non-interactive` | **NOU** — No demana inputs (secrets no trobats → buits) |
| `--no-model-refine` | No refinis el pla amb LLM |
| `--no-readme` | No llegeixis el README |
| `--no-db-provision` | No aixequis BDs amb Docker |
| `--no-emergent-detect` | Desactiva detector Emergent |
| `--llm-primary` | **v6 NOU** — L'LLM llegeix el repo i proposa el pla des de zero (fallback determinista si falla). Millor per repos desordenats. |
| `--skip-env` | No facis configuració interactiva de .env |
| `--github-token <t>` | Token GitHub (també env `GITHUB_TOKEN`) |
| `--gitlab-token <t>` | Token GitLab (també env `GITLAB_TOKEN`) |
| `--bitbucket-token <t>` | Token Bitbucket (també env `BITBUCKET_TOKEN`) |
| `--status` | Llista serveis registrats |
| `--stop <repo\|all>` | Atura serveis |
| `--logs <repo>` | Mostra últims logs d'un repo |

---

## 8) Seguretat

- Whitelist de prefixos permesos (`pip`, `npm`, `uvicorn`…) + suport camins com `.venv/bin/pip`
- Whitelist de wrappers (`nohup`, `setsid`) amb validació del binari real
- Blacklist de patrons perillosos (`sudo`, `rm -rf /`, `curl | bash`, `shutdown`, `mkfs`…)
- Scripts del repo només executables si estan **dins** del repo
- Secrets guardats amb `chmod 600`
- Les suggerències de reparació del LLM també passen pel validador

---

## 9) Stacks suportats

### Detecció automàtica completa
- **Emergent** (FastAPI+React+Mongo) — pla específic optimitzat
- Node.js (Next, Vite, React, Express) amb npm/yarn/pnpm
- Python (FastAPI, Flask, Django, Streamlit)
- Docker/Docker Compose
- Go, Rust, Ruby (Rails/Sinatra), PHP (Laravel/Symfony), Java (Maven/Gradle)
- Makefile

### BDs auto-provisionades via Docker
- PostgreSQL 16 · MySQL 8 · **MongoDB 7** · Redis 7

---

## 10) Problemes freqüents

### Ollama no responent
```bash
sudo systemctl restart ollama
curl http://localhost:11434/api/tags
```

### Docker sense permisos
`newgrp docker` o tanca sessió i torna a obrir.

### Ports ocupats
L'agent intenta port lliure automàticament. Si vols forçar:
```bash
lsof -i :3000; kill <PID>
```

### Model lent (poca RAM)
```bash
ollama pull qwen2.5-coder:7b
python3 universal_repo_agent_v5.py --input ... --model qwen2.5-coder:7b --execute
```
O desactiva'l: `--no-model-refine`.

### npm install falla per peer deps
Als stacks Emergent, l'agent ja fa servir `yarn` per defecte (millor amb peer deps).
Si només tens `npm`, usa `npm install --legacy-peer-deps` manualment.

---

## 11) Novetats v5 respecte v4

- Detector Emergent stack (FastAPI+React+Mongo) amb `.env` auto
- Suport **GitLab** i **Bitbucket** tokens a més de GitHub
- Registry de PIDs + subcomandes `--status`/`--stop`/`--logs`
- **Mode `--dockerize`** — genera compose.yml automàtic
- **Caché de secrets** (`~/.universal-agent/secrets.json`)
- **Smoke tests automàtics** post-arrencada (HTTP + pytest)
- **Dashboard web** (`dashboard.py`)
- `setsid` + `killpg` per matar subprocessos fills
- Validador accepta `.venv/bin/pip`, `PORT=3000 yarn start`, `nohup`, `setsid`
- Preferència `yarn` sobre `npm` als stacks Emergent

---

## 12) Exemple complet end-to-end

```bash
# Un cop: instal·la tot
./setup_ubuntu.sh
newgrp docker

# Dashboard en una terminal
python3 dashboard.py &

# Obrir http://localhost:9999 al navegador,
# llançar repos via UI o via CLI:
python3 universal_repo_agent_v5.py \
    --input https://github.com/user/emergent-repo.git \
    --execute --approve-all

# Comprovar
curl http://localhost:8001/api/
xdg-open http://localhost:3000

# Neteja
python3 universal_repo_agent_v5.py --stop all
```

Bona sort! 🚀
