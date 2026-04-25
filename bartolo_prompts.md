cd ~/universal-agent
nano bartolo_prompts.md
Enganxa això (només el contingut Markdown):

# Catàleg de prompts per Bartolo

Guia completa de tot el que pots demanar a Bartolo (model OpenWebUI amb tool `universal_repo_agent`).

> Bartolo entén llenguatge natural en català/castellà/anglès. Els exemples són literals però pots reformular-los.

## 1. Desplegar repos (asíncron, recomanat)

Executa async aquest repo: https://github.com/streamlit/streamlit-hello

Desplega async https://github.com/Buuntu/fastapi-react

Executa async el ZIP /home/usuari/universal-agent-workspace/_uploads/test.zip

Desplega amb Docker https://github.com/tiangolo/full-stack-fastapi-template


→ Retorna un `job_id`. Consulta'l després.

## 2. Estat de feines

Consulta l'estat del job a3f9b2c1d4e5

Llista totes les feines del bridge

Quins jobs estan corrent?


## 3. Gestió de serveis

Mostra l'estat dels serveis registrats

Quins repos tinc desplegats?

Mostra els logs del repo gptest-main

Reinicia el repo streamlit-hello

Atura el repo gptest-main

Atura tots els serveis


## 4. Shell amb confirmació (2 passos)

### Pas 1: proposar
Proposa una comanda shell: df -h

Proposa: free -h

Proposa: docker ps

Proposa: ls -la ~/universal-agent-workspace

Proposa: du -sh ~/universal-agent-workspace/*

Proposa: ps aux | grep python

Proposa: tail -50 ~/universal-agent-workspace/streamlit-hello/streamlit.log


### Pas 2: confirmar (token caduca als 120s)
Confirma l'execució amb el token a1b2c3d4


## 5. Pujada de ZIPs des del navegador

Dona'm la URL per pujar un ZIP


→ Bartolo retorna `http://<IP_LAN>:9090/upload`. L'obres al navegador, arrossegues el ZIP, copies la ruta i:

Executa async el ZIP /home/usuari/universal-agent-workspace/_uploads/<nom>.zip


## 6. Fluxos combinats reals

### A. Desplegar i veure resultat
Executa async https://github.com/streamlit/streamlit-hello
(espera 30-60s)
Consulta l'estat del job <id>

### B. Quant ocupa el workspace?
Proposa: du -sh ~/universal-agent-workspace
Confirma amb el token <token>

### C. Mira si Docker té contenidors corrent
Proposa: docker ps -a
Confirma amb el token <token>

### D. Treure un repo del disc
Atura el repo <nom>
Proposa: rm -rf ~/universal-agent-workspace/<nom>
Confirma amb el token <token>

### E. Pujar un projecte local i desplegar-lo
Dona'm la URL per pujar un ZIP
(al navegador: arrossegar el zip)
Executa async el ZIP /home/usuari/universal-agent-workspace/_uploads/projecte.zip
Consulta l'estat del job <id>

### F. Un repo s'ha penjat, vull diagnosticar
Mostra els logs del repo <nom>
(si cal més detall) Proposa: tail -100 ~/universal-agent-workspace/<nom>/.agent_logs/01_install.log
Confirma amb el token <token>

## 7. Tools disponibles (resum)

| Tool | Funció |
|---|---|
| `executa_repo_async(input, dockerize)` | Desplega repo en background |
| `consulta_estat_job(job_id)` | Estat i sortida d'una feina |
| `llista_jobs()` | Totes les feines |
| `estat_serveis()` | Repos corrent |
| `consulta_logs(repo)` | Logs d'un repo |
| `refresca_repo(repo)` | Reinicia |
| `atura_repo(repo)` | Para (`"all"` per tots) |
| `proposa_comanda_shell(cmd)` | Pas 1: token |
| `executa_comanda_shell_confirmada(token)` | Pas 2: executa |
| `url_pujada_de_zips()` | URL del formulari d'upload |

## 8. Tips

- **Si Bartolo respon coses estranyes** (paràfrasis o "no tinc accés"): mira sempre el modal de la tool clicant el chip a sota la resposta. Allà està la veritat.
- **Comandes destructives** (`rm -rf /`, `mkfs`, `dd`, ...) es bloquegen automàticament al bridge.
- **Token de shell** caduca als 120s. Si triga, repeteix el pas 1.
- **Paral·lelisme**: pots tenir diversos jobs alhora; cadascun té el seu `job_id`.
