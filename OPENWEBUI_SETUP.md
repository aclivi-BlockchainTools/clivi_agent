# Integració amb OpenWebUI — Guia pas a pas

Aquesta guia t'ensenya a tenir una **interfície web unificada** (OpenWebUI) que:
- Parla amb els teus models d'Ollama (qwen2.5-coder:14b, altres)
- Decideix **automàticament** quan activar quin "agent":
  - 📦 Si demanes "compila aquest repo..." → invoca **Universal Repo Agent v5**
  - 🔍 Si preguntes "què va passar avui..." → invoca **Web Search**
  - 💬 Si preguntes qualsevol altra cosa → respon directament amb el model

---

## 1) Instal·la OpenWebUI

```bash
# Opció A: Docker (recomanat)
docker run -d \
    -p 3001:8080 \
    --add-host=host.docker.internal:host-gateway \
    -v open-webui:/app/backend/data \
    -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    --name open-webui \
    --restart always \
    ghcr.io/open-webui/open-webui:main

# Opció B: pip (sense Docker)
pip install open-webui
open-webui serve --port 3001
```

Obre **http://localhost:3001** al navegador. Registra't com a primer usuari (serà admin).

---

## 2) Comprova que Ollama està connectat

A OpenWebUI: **Settings → Admin Settings → Models**
Hauria d'aparèixer `qwen2.5-coder:14b` i altres models que tinguis a Ollama.

Si no apareixen:
- Comprova que Ollama corre: `curl http://localhost:11434/api/tags`
- Si Ollama corre al host i OpenWebUI al Docker, la URL ha de ser `http://host.docker.internal:11434`
- Reinicia OpenWebUI: `docker restart open-webui`

---

## 3) Instal·la els Tools

### Tool 1 — Universal Repo Agent

1. A OpenWebUI, ves a **Workspace → Tools → "+"**
2. Enganxa el contingut del fitxer **`openwebui_tool_repo_agent.py`**
3. Guarda amb nom "**Universal Repo Agent**"
4. Abans de guardar, **edita** la constant `AGENT_PATH` a la part de dalt del codi perquè apunti al fitxer `universal_repo_agent_v5.py` a la teva màquina:

```python
AGENT_PATH = "/home/usuari/universal-agent/universal_repo_agent_v5.py"
```

O configura-ho via variable d'entorn abans d'iniciar OpenWebUI:
```bash
export UNIVERSAL_AGENT_PATH=/home/usuari/universal-agent/universal_repo_agent_v5.py
```

### Tool 2 — Web Search

1. **Workspace → Tools → "+"**
2. Enganxa el contingut d'**`openwebui_tool_web_search.py`**
3. Guarda amb nom "**Web Search**"
4. Instal·la dependències al host (o dins del container OpenWebUI):

```bash
pip install requests beautifulsoup4
# Si OpenWebUI corre a Docker:
docker exec -it open-webui pip install beautifulsoup4
```

---

## 4) Activa el Function Calling nadiu

Perquè l'LLM decideixi **automàticament** quina Tool invocar:

1. **Settings → Admin Settings → Interface**
2. Busca "**Function Calling**" o "**Native function calling**"
3. Activa'l (o al model individual, si el model ho suporta)

Amb qwen2.5-coder:14b, el function calling nadiu **funciona bé**.

---

## 5) Exemples d'ús al xat

### Compilar i executar un repo
> **Tu**: Compila i executa aquest repositori: https://github.com/aclivi-BlockchainTools/GPTest.git

> **LLM**: [Invoca automàticament `compila_i_executa_repositori(input_url_o_path="https://github.com/aclivi-BlockchainTools/GPTest.git")`]
>
> He clonat el repositori GPTest, instal·lat les dependències i arrencat els serveis. Backend a http://localhost:8001 i frontend a http://localhost:3000. Smoke tests 6/6 ✅.

### Usar l'LLM primari (v6)
> **Tu**: Analitza aquest repo desordenat i prova d'arrencar-lo: https://github.com/algun/repo-complex

> **LLM**: [Invoca `compila_i_executa_repositori(input_url_o_path=..., usa_llm_primari=True)`]

### Veure què tens arrencat
> **Tu**: Què tinc en marxa ara mateix?

> **LLM**: [Invoca `llista_serveis_arrencats()`]
>
> Tens aquests serveis arrencats:
> - **gptest** (backend PID 1234, frontend PID 5678, tots dos RUNNING)

### Aturar un repo
> **Tu**: Atura el repo gptest

> **LLM**: [Invoca `atura_repositori(nom_repo="gptest")`]

### Cerca a Internet
> **Tu**: Quan va sortir Python 3.13?

> **LLM**: [Invoca `cerca_web(consulta="Python 3.13 release date")`]

### Barreja
> **Tu**: Busca'm a la web la documentació de FastAPI i després clona'm i executa'm un repo que la usi

> **LLM**: [Invoca `cerca_web(...)` i després `compila_i_executa_repositori(...)`]

---

## 6) Arquitectura complet del sistema

```
┌──────────────────────────────────────────────────────┐
│  Navegador: http://localhost:3001                    │
│  OpenWebUI (UI + xat + historial)                    │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  Function Calling Router (integrat a OpenWebUI)      │
│  L'LLM llegeix la teva pregunta + les descripcions   │
│  de les Tools i decideix quina invocar.              │
└────┬────────────────┬────────────────┬──────────────┘
     │                │                │
     ▼                ▼                ▼
┌─────────┐    ┌──────────┐   ┌──────────────┐
│ Ollama  │    │ Tool 1:  │   │ Tool 2:      │
│ qwen2.5 │    │ Repo     │   │ Web Search   │
│ -coder  │    │ Agent    │   │ (DuckDuckGo) │
│ :14b    │    │ (v5/v6)  │   │              │
└─────────┘    └────┬─────┘   └──────┬───────┘
                    │                │
                    ▼                ▼
         ┌─────────────────┐   ┌─────────────┐
         │ subprocess      │   │ requests +  │
         │ universal_repo_ │   │ BeautifulSoup│
         │ agent_v5.py     │   │              │
         └─────────────────┘   └─────────────┘
                    │
                    ▼
         ┌──────────────────────────┐
         │ Serveis arrencats:       │
         │ - backend :8001          │
         │ - frontend :3000         │
         │ - mongo :27017           │
         └──────────────────────────┘
```

---

## 7) Novetats v6 (LLM com a planner primari)

El flag `--llm-primary` (i el paràmetre `usa_llm_primari` del Tool) fa que:

1. L'agent recull tot el context del repo: README, manifests (package.json, requirements.txt, Dockerfile, go.mod…), primers fitxers de codi (server.py, main.go, index.ts…), i l'arbre de fitxers.
2. Envia tot això a qwen2.5-coder:14b amb un prompt detallat.
3. El model retorna un JSON amb el pla d'execució (passos a executar).
4. **El validador de seguretat valida cada pas** (mateixos controls que el pla determinista).
5. Si qualsevol pas no és segur, es descarta.
6. Si hi ha <1 pas vàlid, **fallback automàtic al pla determinista**.

### Quan usar `--llm-primary`?
- ✅ Repos amb README detallat però estructura poc comuna
- ✅ Repos en llenguatges menys estàndard (Rust, Elixir, Crystal, Nim...)
- ✅ Projectes amb build systems custom (Just, Earthly, Bazel)
- ✅ Quan el pla determinista genera massa passos o no els correctes

### Quan NO usar-lo?
- ❌ Repos Emergent estàndard (el detector dedicat funciona millor)
- ❌ Projectes Docker Compose simples (un pas i ja està)
- ❌ Quan no tens Ollama o el model no cabe a la RAM

---

## 8) Troubleshooting

### La Tool "Universal Repo Agent" no apareix al xat
- Comprova que està **Enabled** a Workspace → Tools
- Al xat, clica el botó "+" al costat del caixa d'entrada i activa-la manualment
- O bé activa "Native function calling" al model perquè l'LLM la vegi sempre

### "❌ No s'ha trobat l'agent"
- Ajusta `AGENT_PATH` al fitxer del Tool
- Si OpenWebUI corre a Docker, el path ha de ser **dins del container**. Munta un volum:
  ```bash
  docker run ... -v /home/usuari/universal-agent:/agent ...
  ```
  i configura `AGENT_PATH=/agent/universal_repo_agent_v5.py`

### La Tool executa però no veig res al xat
- OpenWebUI retalla sortides llargues. Mira els logs del container: `docker logs open-webui`
- Els serveis arrencats amb `nohup` continuen corrent. Comprova amb `llista_serveis_arrencats`.

### L'LLM no invoca la Tool automàticament
- Sigues **explícit**: "Usa la tool `compila_i_executa_repositori` per..."
- Comprova que el model suporta function calling. **qwen2.5-coder:14b sí**, però alguns altres no.
- Alguns models necessiten "prompt tuning" — mira a Admin Settings si hi ha opcions de format JSON.

---

## 9) Extensions possibles

A partir d'aquí pots afegir més Tools personalitzats:
- 🐙 **Git operations** — clonar, commit, push, PR
- 🐳 **Docker control** — `docker ps`, logs, stop
- 📊 **System info** — CPU, RAM, disk (útil per decidir si un repo cabrà)
- 🔐 **Secrets manager** — llegir/escriure secrets cachejats
- 💻 **Terminal** — executar comandes arbitràries amb confirmació (ALT risc, només per admins)

Cada Tool és un fitxer Python amb el format d'aquests exemples. L'LLM llegeix les docstrings per saber **quan** i **com** usar-los.

---

## 10) Comandes ràpides de referència

```bash
# Engegar Ollama + el teu model
ollama serve &                    # o via systemctl
ollama pull qwen2.5-coder:14b

# Engegar OpenWebUI
docker start open-webui           # si ja l'has creat
# o primera vegada:
docker run -d -p 3001:8080 -v open-webui:/app/backend/data \
    --add-host=host.docker.internal:host-gateway \
    -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    --name open-webui --restart always \
    ghcr.io/open-webui/open-webui:main

# Comprovar que tot està bé
curl http://localhost:11434/api/tags        # Ollama OK
curl -I http://localhost:3001/              # OpenWebUI OK (HTTP 200)

# Obrir navegador
xdg-open http://localhost:3001
```

Bona sort! 🚀
