"""
title: Universal Repo Agent
author: usuari
version: 3.1
description: Router + wizard + exec_shell + upload. v3.1: estat_serveis mostra BD (contenidors Docker + URLs).
"""
import json
import os
import time
import urllib.request
import urllib.error
from typing import Optional


class Tools:
    def __init__(self):
        self.bridge_url = "http://host.docker.internal:9090"
        self.timeout = 30
        self._auth_token = os.environ.get("BRIDGE_AUTH_TOKEN", "")

    # ---------- helpers ----------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._auth_token:
            h["X-Auth-Token"] = self._auth_token
        return h

    def _post(self, path: str, payload: dict, timeout: Optional[int] = None) -> dict:
        url = self.bridge_url + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def _get(self, path: str, timeout: Optional[int] = None) -> dict:
        url = self.bridge_url + path
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    # ---------- helpers de polling ----------
    def _format_job_result(self, r: dict) -> str:
        status = r.get("status")
        if status == "failed" and r.get("error_reports"):
            rep = r["error_reports"][0]
            n = len(rep.get("repair_attempts", []))
            step = rep.get("failed_step", {})
            return (
                f"❌ No he pogut arreglar l'error automàticament.\n\n"
                f"**Step fallit**: {step.get('title', '?')} "
                f"(`{step.get('command', '?')}`)\n"
                f"**Error**: {rep.get('error_summary', '')}\n"
                f"**Intentat**: {n} reparació{'ns' if n != 1 else ''}\n"
                f"**Diagnòstic Qwen**: {rep.get('diagnosis', '')}\n\n"
                f"**Per escalar a Claude Code**, copia aquest prompt:\n"
                f"```\n{rep.get('claude_code_prompt', '')}\n```"
            )
        out = r.get("stdout") or r.get("output") or ""
        if len(out) > 4000:
            out = out[-4000:]
        emoji = "✅" if status == "done" else "❌"
        return (f"{emoji} Estat: {status} | rc={r.get('returncode')}\n"
                f"Iniciada: {r.get('started_at')} | Acabada: {r.get('finished_at')}\n"
                f"--- sortida ---\n{out}")

    def _wait_for_job(self, job_id: str, max_wait: int = 600, poll_interval: int = 5) -> str:
        """Espera que un job acabi i retorna el resultat. Si supera max_wait, retorna l'últim estat."""
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            r = self._get(f"/job/{job_id}", timeout=15)
            if "error" in r:
                return f"Error consultant el job: {r['error']}"
            status = r.get("status")
            if status in ("done", "failed"):
                return self._format_job_result(r)
        # Timeout — retorna l'últim estat conegut
        r = self._get(f"/job/{job_id}", timeout=15)
        out = r.get("stdout") or r.get("output") or ""
        if len(out) > 2000:
            out = out[-2000:]
        return (f"⏳ Timeout ({max_wait}s) — el job {job_id} encara s'executa.\n"
                f"Estat: {r.get('status')}\n"
                f"--- sortida fins ara ---\n{out}\n\n"
                f"Consulta el resultat final amb: consulta_estat_job('{job_id}')")

    # ---------- v2.9: wizard de muntatge pas a pas ----------
    def inicia_muntatge(self, repo_url: str, rapid: bool = False) -> str:
        """
        Inicia el muntatge guiat d'un repo amb wizard interactiu.
        Analitza el repo, pregunta on muntar-lo, recull les claus API que falten
        i confirma la configuració ABANS d'executar res.
        Si rapid=True (o l'usuari diu 'ràpid'/'defaults'), salta el wizard i munta amb defaults.
        Usa SEMPRE aquesta funció en lloc de executa_repo_async per a repos nous.
        :param repo_url: URL del repo (GitHub, GitLab, Bitbucket) o ruta local a ZIP.
        :param rapid: Si True, salta el wizard i usa tots els valors per defecte.
        """
        r = self._post("/wizard/start", {"repo_url": repo_url, "rapid": rapid}, timeout=60)
        if "error" in r:
            return f"❌ Error: {r['error']}"
        if r.get("done"):
            # Mode ràpid: job ja llançat, espera resultat
            return f"🚀 Mode ràpid activat.\n\n" + self._wait_for_job(r["job_id"])
        return (f"🧙 Wizard iniciat (id: `{r['wizard_id']}`)\n\n"
                f"{r.get('question', '')}\n\n"
                f"_Respon amb `respon_wizard('{r['wizard_id']}', 'la teva resposta')`_\n"
                f"_(O di 'ràpid' per saltar el wizard i usar valors per defecte)_")

    def respon_wizard(self, wizard_id: str, resposta: str) -> str:
        """
        Envia la resposta de l'usuari al pas actual del wizard de muntatge.
        Retorna la pregunta següent, o el resultat final quan el wizard acaba.
        Si dius 'ràpid' o 'defaults' en qualsevol pas, salta la resta i munta immediatament.
        :param wizard_id: codi de 8 caràcters retornat per inicia_muntatge (ex: 'a1b2c3d4').
            MAI posis aquí la resposta de l'usuari (clau API, path, etc.) — això va a 'resposta'.
        :param resposta: resposta al pas actual (path, clau API, sí/no, etc.).
        """
        r = self._post("/wizard/step", {"wizard_id": wizard_id, "answer": resposta}, timeout=60)
        if "error" in r:
            return f"❌ Error: {r['error']}"
        if r.get("step") == "CANCELLED":
            return "❌ Muntatge cancel·lat."
        if r.get("done"):
            job_id = r.get("job_id")
            if not job_id:
                return "✅ Wizard completat."
            return f"🚀 Llançant el muntatge...\n\n" + self._wait_for_job(job_id)
        return (f"{r.get('question', '')}\n\n"
                f"_Respon amb `respon_wizard('{wizard_id}', 'la teva resposta')`_")

    # ---------- agent: execució de repos ----------
    def executa_repo_async(self, input: str, dockerize: bool = False) -> str:
        """
        Desplega un repo (URL GitHub o ruta local a un .zip/carpeta). Espera automàticament
        fins que acabi i retorna el resultat final (fins a 10 minuts).
        :param input: URL del repo de GitHub o ruta local al host (ex: /home/usuari/...).
        :param dockerize: Si True, intenta dockeritzar l'aplicació.
        """
        r = self._post("/run/async", {"input": input, "dockerize": dockerize}, timeout=20)
        if "error" in r:
            return f"Error: {r['error']}"
        job_id = r.get("job_id")
        return self._wait_for_job(job_id, max_wait=600, poll_interval=5)

    def consulta_estat_job(self, job_id: str) -> str:
        """
        Consulta l'estat d'un job. Si encara s'executa, espera fins que acabi (màx 10 min).
        :param job_id: identificador retornat per executa_repo_async.
        """
        r = self._get(f"/job/{job_id}", timeout=15)
        if "error" in r:
            return f"Error: {r['error']}"
        status = r.get("status")
        if status in ("done", "failed"):
            return self._format_job_result(r)
        # Encara en curs — espera fins que acabi
        return self._wait_for_job(job_id, max_wait=600, poll_interval=5)

    def segueix_progres_job(self, job_id: str) -> str:
        """
        Mostra les últimes línies de progrés d'un job en execució.
        Crida-la repetidament per veure com avança l'agent pas a pas.
        :param job_id: identificador retornat per executa_repo_async.
        """
        r = self._get(f"/job/{job_id}/stream", timeout=10)
        if "error" in r:
            return f"Error: {r['error']}"
        status = r.get("status", "?")
        lines = r.get("lines", "").strip()
        emoji = {"running": "⏳", "done": "✅", "failed": "❌", "queued": "🕐"}.get(status, "❓")
        return f"{emoji} [{status}]\n{lines}" if lines else f"{emoji} [{status}] (sense sortida encara)"

    def llista_jobs(self) -> str:
        """Llista totes les feines (en execució i acabades) registrades al bridge."""
        r = self._get("/jobs", timeout=10)
        if "error" in r:
            return f"Error: {r['error']}"
        jobs = r.get("jobs", [])
        if not jobs:
            return "No hi ha cap feina registrada."
        lines = [f"Total: {r.get('count')}"]
        for j in jobs:
            lines.append(f"  • {j['id']} | {j['status']} | rc={j.get('returncode')} | {j['started_at']}")
        return "\n".join(lines)

    # ---------- agent: gestió de serveis ----------
    def estat_serveis(self) -> str:
        """
        Mostra tots els serveis i repos en execució al sistema.
        Inclou serveis arrencats via start.sh (wavebox-mail, etc.) i via l'agent.
        """
        ws = self._get("/workspace/services", timeout=15)
        ag = self._get("/status", timeout=15)

        lines = []
        # Serveis workspace (start.sh)
        if ws and not ws.get("error") and not ws.get("_error"):
            for repo, svcs in ws.items():
                running = [s for s, info in svcs.items() if info.get("running")]
                stopped = [s for s, info in svcs.items() if not info.get("running")]
                status = "✅" if running else "❌"
                pids = ", ".join(f"{s}(PID {svcs[s]['pid']})" for s in running)
                lines.append(f"{status} {repo}: {pids or 'aturat'}")
        # Serveis agent (legacy)
        if isinstance(ag, dict) and ag.get("services"):
            for repo, info in ag["services"].items():
                if repo not in ws:
                    st = info.get("status", "?")
                    lines.append(f"{'✅' if st == 'RUNNING' else '❌'} {repo} (agent): {st}")

        if not lines:
            return "Cap servei actiu al workspace."
        # Afegeix info de BD si n'hi ha
        if isinstance(ws, dict) and ws.get("_databases"):
            lines.append("")
            lines.append("🗄️ Bases de dades:")
            for db in ws["_databases"]:
                lines.append(f"   {db['type']} — {db['connection_url']}")
                lines.append(f"   docker exec -it {db['container']} sh")
        return "\n".join(lines)

    def atura_repo(self, repo: str = "all") -> str:
        """
        Atura un servei específic o tots ('all').
        Funciona tant per serveis de l'agent com per serveis arrencats amb start.sh.
        :param repo: nom del repo o 'all'.
        """
        # Atura serveis workspace (start.sh)
        r_ws = self._post("/workspace/stop", {"repo": repo}, timeout=30)
        # Atura serveis agent (legacy)
        r_ag = self._post("/stop", {"repo": repo}, timeout=20)

        stopped = r_ws.get("stopped", []) + (r_ag.get("stopped", []) if isinstance(r_ag, dict) else [])
        errors = r_ws.get("errors", [])
        if not stopped and not errors:
            return f"Cap servei '{repo}' actiu per aturar."
        msg = ""
        if stopped:
            msg += "✅ Aturat:\n" + "\n".join(f"  - {s}" for s in stopped)
        if errors:
            msg += "\n❌ Errors:\n" + "\n".join(f"  - {e}" for e in errors)
        return msg.strip()

    def refresca_repo(self, repo: str) -> str:
        """
        Reinicia un repo ja desplegat (atura i torna a arrencar).
        :param repo: nom del repo.
        """
        r = self._post("/refresh", {"repo": repo}, timeout=60)
        return json.dumps(r, indent=2, ensure_ascii=False)

    def consulta_logs(self, repo: str) -> str:
        """
        Mostra els últims logs d'un repo.
        :param repo: nom del repo.
        """
        r = self._get(f"/logs?repo={repo}", timeout=15)
        if "error" in r:
            return f"Error: {r['error']}"
        out = r.get("output") or json.dumps(r, ensure_ascii=False)
        if len(out) > 4000:
            out = out[-4000:]
        return out

    # ---------- v2.8: consultes de lectura directes (sense confirmació) ----------
    def consulta_info(self, cmd: str) -> str:
        """
        Executa una comanda de lectura al host i retorna la sortida directament, sense necessitat
        de confirmació. Només per a comandes segures de lectura: docker inspect/ps/logs/version,
        curl localhost, systemctl status, ps, df, ollama list, etc.
        Usa-la per respondre preguntes sobre l'estat del sistema (versions, processos, ports, logs...).
        :param cmd: comanda de lectura a executar (ex: 'docker inspect open-webui', 'ollama list').
        """
        r = self._post("/exec_info", {"cmd": cmd}, timeout=20)
        if "error" in r:
            return f"❌ {r['error']}"
        out = r.get("output", "").strip()
        rc = r.get("returncode", 0)
        if not out:
            return f"(sense sortida, rc={rc})"
        return out

    # ---------- v2.7: actualització de containers Docker ----------
    def actualitza_container(self, container: str = "open-webui") -> str:
        """
        Actualitza un container Docker existent: baixa la nova imatge, atura el container,
        l'elimina i el torna a crear amb els mateixos paràmetres (ports, volums, variables d'entorn).
        Usa-la quan l'usuari vulgui actualitzar OpenWebUI o un altre container gestionat.
        :param container: nom del container Docker a actualitzar (per defecte 'open-webui').
        """
        r = self._post(f"/update_container/{container}", {}, timeout=360)
        if "error" in r:
            return f"❌ Error actualitzant '{container}': {r['error']}\n{r.get('log', '')}"
        return (f"✅ Container '{container}' actualitzat correctament.\n"
                f"Imatge: {r.get('image')}\n\n"
                f"--- log ---\n{r.get('log', '')}")

    # ---------- v2.3: shell amb confirmació ----------
    def proposa_comanda_shell(self, cmd: str) -> str:
        """
        PRIMER PAS d'execució de shell: proposa una comanda i obté un token.
        L'usuari ha de revisar la comanda i confirmar-la cridant executa_comanda_shell_confirmada.
        :param cmd: comanda bash a executar al host.
        """
        r = self._post("/exec_shell", {"cmd": cmd}, timeout=10)
        if "error" in r:
            return f"Error: {r['error']}"
        return (f"COMANDA PROPOSADA (cal confirmacio):\n"
                f"  {r.get('cmd')}\n\n"
                f"Token: {r.get('token')}\n"
                f"Caduca en: {r.get('expires_in')}s\n\n"
                f"Per executar-la, crida:\n"
                f"  executa_comanda_shell_confirmada('{r.get('token')}')")

    def executa_comanda_shell_confirmada(self, token: str, timeout: int = 60) -> str:
        """
        SEGON PAS: executa la comanda associada a un token retornat per proposa_comanda_shell.
        :param token: token rebut de proposa_comanda_shell.
        :param timeout: timeout en segons (per defecte 60).
        """
        r = self._post("/exec_shell/confirm", {"token": token, "timeout": timeout},
                       timeout=timeout + 10)
        if "error" in r:
            return f"Error: {r['error']}"
        out = r.get("output", "")
        if len(out) > 4000:
            out = out[-4000:]
        return (f"Returncode: {r.get('returncode')} | OK: {r.get('ok')}\n"
                f"--- sortida ---\n{out}")

    # ---------- v2.3: upload UI ----------
    def url_pujada_de_zips(self) -> str:
        """
        Retorna la URL del formulari web per pujar un ZIP al host.
        L'usuari obre la URL al navegador, arrossega un .zip i obte la ruta al host.
        Despres pot cridar executa_repo_async amb aquesta ruta.
        """
        health = self._get("/health", timeout=10)
        public_url = health.get("public_url", "")
        if public_url:
            upload_url = public_url.rstrip("/") + "/upload"
        else:
            upload_url = "(no s'ha pogut determinar la IP del host — comprova que el bridge corre i és accessible)"
        return (f"Obre aquesta URL al navegador per pujar un ZIP:\n"
                f"  {upload_url}\n\n"
                f"Un cop pujat, copia la ruta retornada i crida:\n"
                f"  executa_repo_async('/ruta/al/zip/que/has/pujat.zip')")

    # ---------- v3.0: router generalista ----------
    def classifica_i_resol(self, text: str) -> str:
        """
        Router generalista: classifica automàticament la intenció de l'usuari i executa
        l'acció correcta sense necessitat de seleccionar una tool específica.
        Usa-la per a preguntes generals, consultes del sistema, hora/data, conversa, i
        com a primera opció quan no saps quina altra tool usar.
        Intents suportats: temps_data, info_sistema, munta_repo, gestio_docker, cerca_web, conversa.
        :param text: text complet del missatge de l'usuari.
        """
        r = self._post("/router/dispatch", {"text": text}, timeout=35)
        if "error" in r:
            return f"❌ Router error: {r['error']}"

        intent = r.get("intent", "?")

        if r.get("redirect"):
            return r.get("message", f"Redirigit a: {r['redirect']}")

        if intent == "munta_repo":
            if r.get("done") and r.get("job_id"):
                return "🚀 Muntant en mode ràpid...\n\n" + self._wait_for_job(r["job_id"])
            if r.get("wizard_id"):
                return (f"🧙 Wizard iniciat (id: `{r['wizard_id']}`)\n\n"
                        f"{r.get('question', '')}\n\n"
                        f"_Respon amb `respon_wizard('{r['wizard_id']}', 'la teva resposta')`_")
            if r.get("error"):
                return f"❌ {r['error']}"

        result = r.get("result", "")
        if not result and "error" in r:
            return f"❌ {r['error']}"

        if intent == "info_sistema":
            return f"```\n{result}\n```" if result else "(sense sortida)"

        return result or "(sense resposta)"
