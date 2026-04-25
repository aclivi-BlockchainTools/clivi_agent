"""
title: Universal Repo Agent (HTTP bridge)
description: Clona, compila i executa repositoris de GitHub/GitLab/Bitbucket o fitxers ZIP locals a la teva màquina Ubuntu. Es comunica amb el bridge HTTP de l'agent que corre al host.
author: tu
version: 2.0.0
license: MIT
requirements: requests
"""

# =============================================================================
# Tool per OpenWebUI — Universal Repo Agent (via HTTP bridge)
# =============================================================================
# Aquest Tool es comunica per HTTP amb `agent_http_bridge.py`, que ha d'estar
# corrent al HOST Ubuntu (fora del container d'OpenWebUI).
#
# Instal·lació (5 passos):
#
#   1. Al HOST Ubuntu, arrenca el bridge:
#        cd ~/universal-agent
#        python3 agent_http_bridge.py --port 9090 &
#
#      (Recomanat: fes-lo persistent amb systemd user — mira els comentaris
#       al final de agent_http_bridge.py)
#
#   2. Comprova que respon:
#        curl http://localhost:9090/health
#      Hauria de retornar {"status": "ok", ...}
#
#   3. Si OpenWebUI corre amb Docker, reinicia el container amb accés al host:
#        docker stop open-webui
#        docker rm open-webui
#        docker run -d -p 3000:8080 \
#            --add-host=host.docker.internal:host-gateway \
#            -v open-webui:/app/backend/data \
#            -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
#            -e BRIDGE_URL=http://host.docker.internal:9090 \
#            --name open-webui --restart always \
#            ghcr.io/open-webui/open-webui:main
#
#      (Si OpenWebUI ja té accés a host.docker.internal, n'hi ha prou amb
#       afegir-hi `-e BRIDGE_URL=http://host.docker.internal:9090`)
#
#   4. A OpenWebUI: Workspace → Tools → "+" → enganxa aquest fitxer.
#
#   5. Activa la Tool al teu xat (o Settings → Interface → Native Function Calling).
# =============================================================================

import os
from typing import Optional
import requests


# BRIDGE_URL: URL on corre agent_http_bridge.py
# - Si OpenWebUI és Docker: "http://host.docker.internal:9090"
# - Si OpenWebUI és natiu al mateix host: "http://localhost:9090"
BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://host.docker.internal:9090")

# Token opcional — ha de coincidir amb el del bridge
BRIDGE_TOKEN = os.environ.get("BRIDGE_AUTH_TOKEN", "")

# Timeout més llarg per l'endpoint /run (un repo pot trigar a arrencar)
LONG_TIMEOUT = 1500
SHORT_TIMEOUT = 60


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if BRIDGE_TOKEN:
        h["X-Auth-Token"] = BRIDGE_TOKEN
    return h


def _post(path: str, body: dict, timeout: int) -> str:
    try:
        r = requests.post(f"{BRIDGE_URL}{path}", json=body, headers=_headers(), timeout=timeout)
        data = r.json()
        return _format_response(data)
    except requests.exceptions.ConnectionError:
        return (f"❌ No s'ha pogut connectar al bridge a {BRIDGE_URL}.\n"
                f"Comprova que agent_http_bridge.py està corrent al host.")
    except requests.exceptions.Timeout:
        return f"⏱️ Timeout després de {timeout}s. Prova `llista_serveis_arrencats()` per veure estat."
    except Exception as e:
        return f"❌ Error: {e}"


def _get(path: str, timeout: int = SHORT_TIMEOUT) -> str:
    try:
        r = requests.get(f"{BRIDGE_URL}{path}", headers=_headers(), timeout=timeout)
        data = r.json()
        return _format_response(data)
    except requests.exceptions.ConnectionError:
        return (f"❌ No s'ha pogut connectar al bridge a {BRIDGE_URL}.\n"
                f"Comprova que agent_http_bridge.py està corrent al host.")
    except Exception as e:
        return f"❌ Error: {e}"


def _format_response(data: dict) -> str:
    if "error" in data:
        return f"❌ {data['error']}"
    output = data.get("output", "")
    rc = data.get("returncode", "?")
    ok = data.get("ok", False)
    icon = "✅" if ok else "⚠️"
    return f"{icon} Return code: {rc}\n\n{output}"


class Tools:
    def __init__(self):
        self.citation = True

    def compila_i_executa_repositori(
        self,
        input_url_o_path: str,
        dockerize: bool = False,
        usa_llm_primari: bool = False,
    ) -> str:
        """
        Clona, analitza, instal·la i arrenca un repositori de codi al host Ubuntu. Funciona amb URLs de GitHub/GitLab/Bitbucket (públiques o privades si tens el token configurat al host), carpetes locals al host o fitxers ZIP.

        Detecta automàticament el stack (Python, Node, FastAPI+React+Mongo, Docker, Go, Rust, Ruby, PHP, Java...) i aixeca els serveis necessaris en background. També provisiona bases de dades (MongoDB, PostgreSQL, MySQL, Redis) via Docker si cal.

        :param input_url_o_path: URL de git (ex: https://github.com/user/repo.git), carpeta local al host o fitxer ZIP al host
        :param dockerize: Si True, aïlla tot el stack en contenidors Docker (requereix Docker al host). Útil per evitar instal·lar res al host.
        :param usa_llm_primari: Si True, l'LLM llegeix el repo sencer i proposa el pla des de zero (millor per repos desordenats, requereix Ollama amb qwen2.5-coder:14b al host). Si falla, usa el pla determinista com a fallback.
        :return: Sortida combinada de l'agent amb l'estat final de l'arrencada
        """
        return _post("/run", {
            "input": input_url_o_path,
            "dockerize": dockerize,
            "llm_primary": usa_llm_primari,
        }, timeout=LONG_TIMEOUT)

    def analitza_repositori_sense_executar(self, input_url_o_path: str) -> str:
        """
        Només analitza un repositori (sense executar-lo): detecta stack, dependències, bases de dades necessàries i serveis 3a part (Supabase/Stripe/OpenAI/...). Útil per revisar què faria abans de confirmar.

        :param input_url_o_path: URL de git, carpeta local o fitxer ZIP (tots al host)
        :return: Anàlisi i pla d'execució, sense executar-lo
        """
        return _post("/analyze", {"input": input_url_o_path}, timeout=300)

    def llista_serveis_arrencats(self) -> str:
        """
        Mostra tots els repositoris i serveis actualment en marxa al host, amb el seu PID i estat (RUNNING/STOPPED).

        :return: Llistat formatat dels serveis registrats
        """
        return _get("/status")

    def atura_repositori(self, nom_repo: str = "all") -> str:
        """
        Atura tots els serveis d'un repositori concret, o tots els repositoris si es passa 'all'.

        :param nom_repo: Nom del repo (slug, ex: 'gptest') o 'all' per aturar-ho tot
        :return: Resultat de l'aturada amb el nombre de processos acabats
        """
        nom = (nom_repo or "all").strip() or "all"
        return _post("/stop", {"repo": nom}, timeout=SHORT_TIMEOUT)

    def mostra_logs_repositori(self, nom_repo: str) -> str:
        """
        Mostra els últims logs d'un repositori arrencat (tant logs de l'agent com stdout/stderr dels serveis en execució).

        :param nom_repo: Nom del repo (slug, ex: 'gptest')
        :return: Contingut dels últims logs
        """
        nom = (nom_repo or "").strip()
        if not nom:
            return "❌ Cal indicar un nom de repo."
        return _get(f"/logs?repo={nom}")

    def estat_del_bridge(self) -> str:
        """
        Comprova que el bridge HTTP al host respon correctament. Usa aquesta funció si altres operacions fallen per entendre si el problema és de connectivitat.

        :return: Estat del bridge (health check)
        """
        return _get("/health")
