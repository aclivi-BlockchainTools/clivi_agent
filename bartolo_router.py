"""
bartolo_router.py — Classificació d'intencions per al router de Bartolo.
Sense dependències del bridge. Importable independentment.
"""
import re
import json
import urllib.request
from typing import Optional, Dict, Any

# ---------------------------------------------------------------------------
# L1 — Regles deterministiques (regex, 0ms, cap LLM)
# ---------------------------------------------------------------------------

_L1_RULES = [
    (re.compile(
        r'\b(quina hora|what time|fecha|hora actual|data actual|quin dia|'
        r'quina data|current time|current date)\b', re.I),
     "temps_data"),

    (re.compile(
        r'\b(docker ps|docker inspect|docker version|docker log|docker stat|'
        r'docker top|docker port|docker network|docker volume|docker image|'
        r'quina versió|quina version|ollama list|systemctl status|'
        r'quins processos|ps aux|espai (lliure|disc|disk)|df -|'
        r'quants containers|quins containers|que corre|que está corriendo|'
        r'ports oberts|ports (en|que) escolt)\b', re.I),
     "info_sistema"),

    (re.compile(
        r'github\.com/|gitlab\.com/|bitbucket\.com/|'
        r'\b(munta|instal[·la]+|clona|desplega|'
        r'munta el repo|deploy|mount repo|clone repo)\b', re.I),
     "munta_repo"),

    (re.compile(
        r'\b(arrenca|arrancar|arrencar|reinicia|reiniciar|torna a engegar|'
        r'engega|posem en marxa)\b', re.I),
     "start_servei"),

    (re.compile(
        r'\b(actualitza open-webui|actualitza el container|'
        r'docker pull|update container|update open-webui|'
        r'upgrade open-webui)\b', re.I),
     "gestio_docker"),

    (re.compile(
        r'\b(cerca (a internet|web|online)|busca (a internet|informació sobre|online)|'
        r'search (online|web|internet)|duckduckgo|google|cerca web|'
        r'busca web|find online)\b', re.I),
     "cerca_web"),
]

# Mapa de patrons → comanda shell per a info_sistema
_INFO_CMD_PATTERNS: list = [
    (re.compile(r'\bdocker ps\b', re.I),
     "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'"),
    (re.compile(r'\bdocker logs?\s+(\S+)', re.I),
     None),   # extret dinàmicament
    (re.compile(r'\b(ollama list|models ollama|llista models)\b', re.I),
     "ollama list"),
    (re.compile(r'\bquina versió\s+(docker)\b', re.I),
     "docker --version"),
    (re.compile(r'\bquina versió\s+(ollama)\b', re.I),
     "ollama --version"),
    (re.compile(r'\bquina versió\s+(python)\b', re.I),
     "python3 --version"),
    (re.compile(r'\bquina versió\s+(node)\b', re.I),
     "node --version"),
    (re.compile(r'\b(espai lliure|espai disc|disk space|df)\b', re.I),
     "df -h /"),
    (re.compile(r'\b(processos|ps aux|que corre)\b', re.I),
     "ps aux | grep -E 'python|node|uvicorn|streamlit' | grep -v grep | head -10"),
    (re.compile(r'\b(ports|listening|escolt)\b', re.I),
     "ss -tlnp | head -20"),
    (re.compile(r'\b(containers|docker)\b', re.I),
     "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'"),
    (re.compile(r'\bsystemctl status\s+(\S+)', re.I),
     None),   # extret dinàmicament
]


def classify_l1(text: str) -> Optional[str]:
    """Retorna l'intent si alguna regla L1 coincideix, sinó None."""
    for pattern, intent in _L1_RULES:
        if pattern.search(text):
            return intent
    return None


def extract_cmd_l1(text: str) -> Optional[str]:
    """Per a intent info_sistema: extreu la comanda shell via patrons L1.
    Retorna None si cap patró específic coincideix."""
    for pattern, cmd in _INFO_CMD_PATTERNS:
        m = pattern.search(text)
        if m:
            if cmd is not None:
                return cmd
            # Casos dinàmics
            if 'logs?' in pattern.pattern:
                return f"docker logs {m.group(1)} --tail 50"
            if 'systemctl' in pattern.pattern:
                return f"systemctl --user status {m.group(1)} --no-pager"
    return None


# ---------------------------------------------------------------------------
# L2 — Classificació per LLM (fallback quan L1 no coincideix)
# ---------------------------------------------------------------------------

_L2_MODEL_PREFERENCES = ["qwen2.5:7b", "qwen2.5:14b"]
_L2_TIMEOUT = 6  # qwen2.5:7b classification takes ~1-3s; 6s gives headroom without blocking
_L2_INTENTS = {"temps_data", "info_sistema", "munta_repo", "gestio_docker",
               "start_servei",
               "cerca_web", "conversa"}

_L2_PROMPT_TMPL = """\
Classifica aquesta petició de l'usuari en una de les categories següents.
Respon ÚNICAMENT amb un JSON en una sola línia. Cap text extra.

Categories:
- temps_data: preguntes sobre hora, data, dia de la setmana
- info_sistema: estat del sistema, docker, processos, ports, versions, logs, espai disc
- munta_repo: muntar, clonar, instal·lar, desplegar un repositori GitHub/GitLab NOU (requereix URL)
- start_servei: arrencar, arrancar, reiniciar, engegar un servei/repo JA EXISTENT pel nom (sense URL)
- gestio_docker: actualitzar o gestionar containers Docker existents
- cerca_web: cerques a internet, informació externa
- conversa: qualsevol altra cosa (conversa general, codi, explicacions)

Per a info_sistema, extreu també la comanda shell adequada.
Per a munta_repo, extreu la URL del repo si n'hi ha.
Per a start_servei, extreu el nom del servei/repo.

Format de resposta:
{"intent": "categoria", "cmd": "comanda o null", "repo_url": "url o null", "repo_name": "nom o null"}

Petició: {text}"""


def _pick_l2_model(ollama_url: str = "http://localhost:11434") -> Optional[str]:
    """Retorna el primer model L2 disponible a Ollama."""
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        available = {m["name"] for m in data.get("models", [])}
        for m in _L2_MODEL_PREFERENCES:
            if m in available:
                return m
        if available:
            return next(iter(available))
    except Exception:
        pass
    return None


def classify_l2(text: str,
                ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Classifica via LLM petit. Retorna dict amb intent + params extrets.
    En cas d'error retorna {"intent": "conversa"}."""
    model = _pick_l2_model(ollama_url)
    if not model:
        return {"intent": "conversa"}

    prompt = _L2_PROMPT_TMPL.replace("{text}", text)
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 80}
    }).encode()

    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=_L2_TIMEOUT) as r:
            resp = json.loads(r.read())
        raw = resp.get("response", "").strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            intent = result.get("intent", "conversa").lower()
            # Validate that intent key exists and is non-empty string
            if not isinstance(intent, str) or not intent or intent not in _L2_INTENTS:
                intent = "conversa"
            return {
                "intent": intent,
                "cmd": result.get("cmd") or None,
                "repo_url": result.get("repo_url") or None,
            }
    except Exception:
        pass
    return {"intent": "conversa"}


# ---------------------------------------------------------------------------
# Punt d'entrada: classifica text amb L1 → L2
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r'https?://\S+|(?:github|gitlab|bitbucket)\.com/\S+', re.I)
_REPO_NAME_RE = re.compile(
    r'\b(?:arrenca|arrancar|arrencar|reinicia|reiniciar|engega|restart|start)\s+'
    r'(?:el\s+|la\s+|els?\s+|un\s+)?([\w][\w-]+)\b', re.I)


def classify(text: str,
             ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Classifica el text amb L1 primer, L2 com a fallback.
    Retorna dict: {"intent": str, "cmd": str|None, "repo_url": str|None,
                   "repo_name": str|None, "source": "l1"|"l2"}
    """
    intent_l1 = classify_l1(text)

    # start_servei amb URL present → és realment munta_repo
    if intent_l1 == "start_servei" and _URL_RE.search(text):
        intent_l1 = "munta_repo"

    if intent_l1:
        cmd = extract_cmd_l1(text) if intent_l1 == "info_sistema" else None
        repo_url = None
        repo_name = None
        if intent_l1 == "munta_repo":
            url_match = _URL_RE.search(text)
            repo_url = url_match.group(0).rstrip(".,);:'\"") if url_match else None
        if intent_l1 == "start_servei":
            m = _REPO_NAME_RE.search(text)
            repo_name = m.group(1) if m else None
        return {"intent": intent_l1, "cmd": cmd, "repo_url": repo_url,
                "repo_name": repo_name, "source": "l1"}

    result = classify_l2(text, ollama_url)
    result["source"] = "l2"
    result.setdefault("repo_name", None)
    return result
