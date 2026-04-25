"""
title: Universal Repo Agent
author: usuari
version: 2.3
description: Pont a l'agent universal local. Suporta async, exec_shell amb confirmació i upload de ZIPs.
"""
import json
import urllib.request
import urllib.error
from typing import Optional


class Tools:
    def __init__(self):
        self.bridge_url = "http://host.docker.internal:9090"
        self.timeout = 30

    # ---------- helpers ----------
    def _post(self, path: str, payload: dict, timeout: Optional[int] = None) -> dict:
        url = self.bridge_url + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
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
        try:
            with urllib.request.urlopen(url, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    # ---------- agent: execució de repos ----------
    def executa_repo_async(self, input: str, dockerize: bool = False) -> str:
        """
        Inicia el desplegament d'un repo (URL GitHub o ruta local a un .zip/carpeta) en segon pla.
        Retorna immediatament un job_id. Fes servir consulta_estat_job per veure el progrés.
        :param input: URL del repo de GitHub o ruta local al host (ex: /home/usuari/...).
        :param dockerize: Si True, intenta dockeritzar l'aplicació.
        """
        r = self._post("/run/async", {"input": input, "dockerize": dockerize}, timeout=20)
        if "error" in r:
            return f"Error: {r['error']}"
        return (f"Feina iniciada amb job_id: {r.get('job_id')}\n"
                f"Estat inicial: {r.get('status')}\n"
                f"Consulta el progrés amb: consulta_estat_job('{r.get('job_id')}')")

    def consulta_estat_job(self, job_id: str) -> str:
        """
        Consulta l'estat i la sortida acumulada d'una feina iniciada amb executa_repo_async.
        :param job_id: identificador retornat per executa_repo_async.
        """
        r = self._get(f"/job/{job_id}", timeout=15)
        if "error" in r:
            return f"Error: {r['error']}"
        out = r.get("stdout") or r.get("output") or ""
        if len(out) > 4000:
            out = out[-4000:]
        return (f"Estat: {r.get('status')}\n"
                f"Returncode: {r.get('returncode')}\n"
                f"Iniciada: {r.get('started_at')}\n"
                f"Acabada: {r.get('finished_at')}\n"
                f"--- sortida (final) ---\n{out}")

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
        """Mostra l'estat dels serveis registrats actualment."""
        r = self._get("/status", timeout=15)
        if "error" in r:
            return f"Error: {r['error']}"
        return json.dumps(r, indent=2, ensure_ascii=False)

    def atura_repo(self, repo: str = "all") -> str:
        """
        Atura un servei específic o tots ('all').
        :param repo: nom del repo o 'all'.
        """
        r = self._post("/stop", {"repo": repo}, timeout=20)
        return json.dumps(r, indent=2, ensure_ascii=False)

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
        return ("Obre aquesta URL al navegador per pujar un ZIP:\n"
                "  http://192.168.0.164:9090/upload\n"
                "  (o http://localhost:9090/upload si ets al mateix host)\n\n"
                "Un cop pujat, copia la ruta retornada i crida:\n"
                "  executa_repo_async('/ruta/al/zip/que/has/pujat.zip')")
