# Router Generalista (Phase 2+3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afegir un router d'intencions a Bartolo que classifica automàticament cada missatge de l'usuari (regles L1 + LLM L2) i el despacha al handler correcte, retornant la resposta directament sense que l'usuari hagui d'escollir la tool.

**Architecture:** `bartolo_router.py` conté la lògica de classificació (L1 regex + L2 Ollama, sense dependències del bridge). `agent_http_bridge.py` rep `POST /router/dispatch`, crida el classificador i executa el handler intern corresponent. La tool d'OpenWebUI afegeix `classifica_i_resol(text)` que crida `/router/dispatch` i retorna el resultat directament.

**Tech Stack:** Python stdlib, re, subprocess, urllib (ja usats al bridge). Ollama local `http://localhost:11434`. Cap dependència nova.

---

## Fitxers afectats

| Fitxer | Acció | Responsabilitat |
|--------|-------|-----------------|
| `bartolo_router.py` | CREATE | Classificació L1+L2. Cap import del bridge. |
| `test_router.py` | CREATE | Tests unitaris L1 + integració L2 |
| `agent_http_bridge.py` | MODIFY | Afegir `_router_dispatch()` + route `POST /router/dispatch` |
| `openwebui_tool_repo_agent.py` | MODIFY | Afegir `classifica_i_resol()` v3.0 |

**Fitxers NO afectats:** `universal_repo_agent_v5.py`, `dashboard.py`.

---

## Task 1: `bartolo_router.py` — Classificació L1 (regles deterministiques)

**Files:**
- Create: `bartolo_router.py`
- Create: `test_router.py`

- [ ] **Step 1: Escriu el test de L1**

```python
# test_router.py
import sys
sys.path.insert(0, "/home/usuari/universal-agent")
from bartolo_router import classify_l1

def test_temps_data():
    assert classify_l1("quina hora és?") == "temps_data"
    assert classify_l1("What time is it?") == "temps_data"
    assert classify_l1("quina data tenim avui?") == "temps_data"

def test_info_sistema():
    assert classify_l1("docker ps") == "info_sistema"
    assert classify_l1("quina versió de docker tens?") == "info_sistema"
    assert classify_l1("quins processos corren?") == "info_sistema"
    assert classify_l1("quant d'espai lliure hi ha?") == "info_sistema"
    assert classify_l1("ollama list") == "info_sistema"

def test_munta_repo():
    assert classify_l1("munta https://github.com/tiangolo/fastapi") == "munta_repo"
    assert classify_l1("instal·la el repo github.com/foo/bar") == "munta_repo"
    assert classify_l1("clona https://github.com/x/y i arrenca-ho") == "munta_repo"

def test_gestio_docker():
    assert classify_l1("actualitza open-webui") == "gestio_docker"
    assert classify_l1("docker pull open-webui") == "gestio_docker"
    assert classify_l1("actualitza el container open-webui") == "gestio_docker"

def test_cerca_web():
    assert classify_l1("cerca a internet com funciona fastapi") == "cerca_web"
    assert classify_l1("busca informació sobre langchain") == "cerca_web"

def test_no_match_returns_none():
    assert classify_l1("hola, com estàs?") is None
    assert classify_l1("explica'm python") is None
    assert classify_l1("escriu-me un poema") is None

if __name__ == "__main__":
    tests = [test_temps_data, test_info_sistema, test_munta_repo,
             test_gestio_docker, test_cerca_web, test_no_match_returns_none]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests)-failed}/{len(tests)} tests passats")
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Verifica que falla (fitxer no existeix)**

```bash
cd /home/usuari/universal-agent && python3 /home/usuari/Projects/bartolo/test_router.py
```
Esperat: `ModuleNotFoundError: No module named 'bartolo_router'`

- [ ] **Step 3: Implementa `bartolo_router.py` amb L1**

Crea `/home/usuari/universal-agent/bartolo_router.py`:

```python
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
        r'\b(munta|instal[·l·l]a|clona|desplega|arrenca el repo|'
        r'munta el repo|deploy|mount repo|clone repo)\b', re.I),
     "munta_repo"),

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
    (re.compile(r'\bdocker (logs?)\s+(\S+)', re.I),
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
                return f"docker logs {m.group(2)} --tail 50"
            if 'systemctl' in pattern.pattern:
                return f"systemctl --user status {m.group(1)} --no-pager"
    return None


# ---------------------------------------------------------------------------
# L2 — Classificació per LLM (fallback quan L1 no coincideix)
# ---------------------------------------------------------------------------

_L2_MODEL_PREFERENCES = ["qwen2.5:7b", "qwen2.5:14b"]
_L2_TIMEOUT = 6
_L2_INTENTS = {"TEMPS_DATA", "INFO_SISTEMA", "MUNTA_REPO", "GESTIO_DOCKER",
               "CERCA_WEB", "CONVERSA"}

_L2_PROMPT_TMPL = """\
Classifica aquesta petició de l'usuari en una de les categories següents.
Respon ÚNICAMENT amb un JSON en una sola línia. Cap text extra.

Categories:
- TEMPS_DATA: preguntes sobre hora, data, dia de la setmana
- INFO_SISTEMA: estat del sistema, docker, processos, ports, versions, logs, espai disc
- MUNTA_REPO: muntar, clonar, instal·lar, desplegar un repositori GitHub/GitLab
- GESTIO_DOCKER: actualitzar o gestionar containers Docker existents
- CERCA_WEB: cerques a internet, informació externa
- CONVERSA: qualsevol altra cosa (conversa general, codi, explicacions)

Per a INFO_SISTEMA, extreu també la comanda shell adequada.
Per a MUNTA_REPO, extreu la URL del repo si n'hi ha.

Format de resposta:
{"intent": "CATEGORIA", "cmd": "comanda o null", "repo_url": "url o null"}

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
        # Fallback: primer model disponible
        if available:
            return next(iter(available))
    except Exception:
        pass
    return None


def classify_l2(text: str,
                ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Classifica via LLM petit. Retorna dict amb intent + params extrets.
    En cas d'error retorna {"intent": "CONVERSA"}."""
    model = _pick_l2_model(ollama_url)
    if not model:
        return {"intent": "CONVERSA"}

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
        # Extreu el JSON de la resposta (pot tenir text extra al davant/darrere)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            intent = result.get("intent", "CONVERSA").upper()
            if intent not in _L2_INTENTS:
                intent = "CONVERSA"
            return {
                "intent": intent.lower().replace("_", "_"),
                "cmd": result.get("cmd") or None,
                "repo_url": result.get("repo_url") or None,
            }
    except Exception:
        pass
    return {"intent": "CONVERSA"}


# ---------------------------------------------------------------------------
# Punt d'entrada: classifica text amb L1 → L2
# ---------------------------------------------------------------------------

def classify(text: str,
             ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Classifica el text amb L1 primer, L2 com a fallback.
    Retorna dict: {"intent": str, "cmd": str|None, "repo_url": str|None, "source": "l1"|"l2"}
    """
    intent_l1 = classify_l1(text)
    if intent_l1:
        cmd = extract_cmd_l1(text) if intent_l1 == "info_sistema" else None
        # Extreu repo URL de text si és munta_repo
        repo_url = None
        if intent_l1 == "munta_repo":
            url_match = re.search(
                r'https?://(?:github|gitlab|bitbucket)\.com/\S+', text, re.I)
            repo_url = url_match.group(0).rstrip(".,)") if url_match else None
        return {"intent": intent_l1, "cmd": cmd, "repo_url": repo_url, "source": "l1"}

    result = classify_l2(text, ollama_url)
    result["source"] = "l2"
    # Normalitza intent a minúscules amb underscore
    result["intent"] = result["intent"].lower()
    return result
```

- [ ] **Step 4: Executa els tests i verifica que passen**

```bash
cd /home/usuari/Projects/bartolo && python3 test_router.py
```
Esperat:
```
  ✅ test_temps_data
  ✅ test_info_sistema
  ✅ test_munta_repo
  ✅ test_gestio_docker
  ✅ test_cerca_web
  ✅ test_no_match_returns_none

6/6 tests passats
```

- [ ] **Step 5: Commit**

```bash
cd /home/usuari/Projects/bartolo
git add test_router.py
# El bartolo_router.py viu a universal-agent/ però el test és al repo bartolo
git add -A
git commit -m "feat: bartolo_router L1 + test_router (classificació deterministica)"
```

---

## Task 2: `bartolo_router.py` — Tests d'integració L2

**Files:**
- Modify: `test_router.py` — afegir tests L2

- [ ] **Step 1: Afegeix tests d'integració L2 al final de `test_router.py`**

```python
# Afegeix al final de test_router.py (abans del bloc if __name__ == "__main__":)

def test_classify_dispatch():
    """Test del punt d'entrada unificat classify()."""
    from bartolo_router import classify

    r = classify("quina hora és?")
    assert r["intent"] == "temps_data", f"esperava temps_data, got {r['intent']}"
    assert r["source"] == "l1"

    r = classify("docker ps")
    assert r["intent"] == "info_sistema"
    assert r["source"] == "l1"
    assert r["cmd"] is not None, "hauria d'extreure comanda"

    r = classify("munta https://github.com/tiangolo/fastapi")
    assert r["intent"] == "munta_repo"
    assert r["repo_url"] == "https://github.com/tiangolo/fastapi"

def test_l2_fallback_conversa():
    """L2: frase ambigua sense patró L1 → CONVERSA o INFO_SISTEMA."""
    from bartolo_router import classify
    r = classify("hola, com estàs avui?")
    # L2 pot retornar conversa o qualsevol intent vàlid
    assert r["intent"] in {"conversa", "temps_data", "info_sistema",
                           "munta_repo", "gestio_docker", "cerca_web"}
    assert r["source"] == "l2"

def test_l2_info_with_cmd():
    """L2: pregunta de sistema sense patró L1 exacte → extreu comanda."""
    from bartolo_router import classify
    r = classify("quanta memòria RAM hi ha lliure al sistema?")
    # Pot ser info_sistema o conversa, però si és info_sistema ha de tenir cmd
    if r["intent"] == "info_sistema":
        assert r["cmd"] is not None
```

I actualitza el bloc `if __name__ == "__main__":`:

```python
if __name__ == "__main__":
    tests = [test_temps_data, test_info_sistema, test_munta_repo,
             test_gestio_docker, test_cerca_web, test_no_match_returns_none,
             test_classify_dispatch, test_l2_fallback_conversa, test_l2_info_with_cmd]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ⚠️  {t.__name__} ERROR: {e}")
            failed += 1
    print(f"\n{len(tests)-failed}/{len(tests)} tests passats")
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Executa els tests (requereix Ollama corrent)**

```bash
cd /home/usuari/Projects/bartolo && python3 test_router.py
```
Esperat: 9/9 tests passats. `test_l2_*` poden trigar fins a 6s.

Si `test_l2_info_with_cmd` falla perquè el model retorna CONVERSA en lloc d'INFO_SISTEMA, és acceptable — el L2 no és determinista. Ajusta l'assertion a `assert r["intent"] in {"info_sistema", "conversa"}`.

- [ ] **Step 3: Commit**

```bash
cd /home/usuari/Projects/bartolo
git add test_router.py
git commit -m "test: afegeix tests integració L2 per bartolo_router"
```

---

## Task 3: `agent_http_bridge.py` — Funció `_router_dispatch()`

**Files:**
- Modify: `/home/usuari/universal-agent/agent_http_bridge.py`

La funció `_router_dispatch` conté el L3 (execució per intent). Ha d'estar dins del fitxer del bridge perquè necessita `_info_safe`, `wizard_start`, `_start_job`, etc.

- [ ] **Step 1: Crea un backup del bridge**

```bash
cp /home/usuari/universal-agent/agent_http_bridge.py \
   /home/usuari/universal-agent/agent_http_bridge.py.bak_router
```

- [ ] **Step 2: Afegeix l'import de bartolo_router al principi del bridge**

Localitza el bloc d'imports al principi de `agent_http_bridge.py` (línies ~1-30) i afegeix just abans de la línia `from pathlib import Path`:

```python
# Router d'intencions
try:
    from bartolo_router import classify as _router_classify
    _ROUTER_AVAILABLE = True
except ImportError:
    _ROUTER_AVAILABLE = False
```

- [ ] **Step 3: Afegeix la funció `_router_dispatch()` just ABANS de la classe `Handler`**

Localitza la línia `class Handler(BaseHTTPRequestHandler):` (línia ~330) i insereix just a sobre:

```python
# =============================================================================
# ROUTER — dispatch per intent
# =============================================================================

def _router_dispatch(text: str, ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Classifica el text de l'usuari i executa el handler corresponent.
    Retorna sempre un dict amb almenys {"intent", "result" o "error" o "job_id"}.
    """
    import datetime as _dt

    if not _ROUTER_AVAILABLE:
        return {"intent": "error", "error": "bartolo_router.py no trobat"}

    classified = _router_classify(text, ollama_url)
    intent = classified.get("intent", "conversa")
    source = classified.get("source", "?")

    # --- temps_data ---
    if intent == "temps_data":
        now = _dt.datetime.now()
        dies = ["dilluns","dimarts","dimecres","dijous","divendres","dissabte","diumenge"]
        mesos = ["gener","febrer","març","abril","maig","juny",
                 "juliol","agost","setembre","octubre","novembre","desembre"]
        s = (f"Ara són les {now.strftime('%H:%M')} del "
             f"{dies[now.weekday()]}, {now.day} de {mesos[now.month-1]} de {now.year}.")
        return {"intent": intent, "source": source, "result": s}

    # --- info_sistema ---
    if intent == "info_sistema":
        cmd = classified.get("cmd")
        if not cmd:
            # Extreu via L1 si no ve del L2
            from bartolo_router import extract_cmd_l1
            cmd = extract_cmd_l1(text)
        if not cmd:
            # Últim recurs: posa un fallback genèric
            cmd = "docker ps && df -h / && ollama list"
        if not _info_safe(cmd):
            return {"intent": intent, "source": source,
                    "error": f"Comanda no segura per a mode lectura: {cmd[:80]}"}
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=15)
            out = (r.stdout or r.stderr or "").strip()
            if len(out) > 3000:
                out = out[-3000:]
            return {"intent": intent, "source": source,
                    "cmd": cmd, "result": out or "(sense sortida)"}
        except Exception as e:
            return {"intent": intent, "source": source, "error": str(e)}

    # --- munta_repo ---
    if intent == "munta_repo":
        repo_url = classified.get("repo_url")
        if not repo_url:
            return {"intent": intent, "source": source,
                    "error": "No he pogut extreure la URL del repo. "
                             "Proporciona-la explícitament: 'munta https://github.com/...'"}
        try:
            result = wizard_start(repo_url, rapid=False)
            return {"intent": intent, "source": source, **result}
        except Exception as e:
            return {"intent": intent, "source": source, "error": str(e)}

    # --- gestio_docker ---
    if intent == "gestio_docker":
        # Detecta nom del container del text (default: open-webui)
        container_match = re.search(
            r'\b(open-webui|open-webui-pipelines|ollama|[\w-]+)\b',
            text, re.I)
        container = "open-webui"
        if container_match:
            candidate = container_match.group(1).lower()
            # Evita paraules genèriques
            if candidate not in {"actualitza", "update", "docker", "container", "el", "un"}:
                container = candidate
        try:
            result = _update_container(container)
            return {"intent": intent, "source": source, **result}
        except Exception as e:
            return {"intent": intent, "source": source, "error": str(e)}

    # --- cerca_web ---
    if intent == "cerca_web":
        # El bridge no fa cerca web (és la tool web_search d'OpenWebUI)
        return {"intent": intent, "source": source,
                "redirect": "web_search",
                "message": "Per a cerques web usa la tool `web_search` directament."}

    # --- conversa_general (default) ---
    # Crida Ollama directament per a conversa general
    payload = json.dumps({
        "model": "qwen2.5:14b",
        "messages": [{"role": "user", "content": text}],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 512}
    }).encode()
    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        answer = resp.get("message", {}).get("content", "")
        return {"intent": intent, "source": source, "result": answer}
    except Exception as e:
        return {"intent": intent, "source": source,
                "error": f"Error cridant Ollama: {e}"}
```

**Nota**: `urllib.request` ja s'usa al bridge però potser no està importat com a nom directe. Verifica que la línia `import urllib.request` existeix als imports del bridge. Si no, afegeix-la.

- [ ] **Step 4: Afegeix la route `POST /router/dispatch` al `do_POST`**

Localitza el bloc `else: self._json(404, {"error": "not found"})` al final del `do_POST` (~línia 542) i afegeix just a sobre:

```python
        elif parsed.path == "/router/dispatch":
            text = str(body.get("text", "")).strip()
            if not text:
                self._json(400, {"error": "missing 'text'"}); return
            ollama_url = str(body.get("ollama_url", "http://localhost:11434"))
            self._json(200, _router_dispatch(text, ollama_url=ollama_url))
```

- [ ] **Step 5: Verifica sintaxi del bridge**

```bash
python3 -m py_compile /home/usuari/universal-agent/agent_http_bridge.py && echo "✅ Sintaxi OK"
```
Esperat: `✅ Sintaxi OK`

- [ ] **Step 6: Reinicia el bridge i comprova health**

```bash
systemctl --user restart agent-bridge
sleep 3
curl -s http://localhost:9090/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('Bridge:', d.get('status'))"
```
Esperat: `Bridge: ok`

- [ ] **Step 7: Test manual del endpoint**

```bash
# Test temps_data
curl -s -X POST http://localhost:9090/router/dispatch \
  -H "Content-Type: application/json" \
  -d '{"text": "quina hora és?"}' | python3 -m json.tool

# Test info_sistema
curl -s -X POST http://localhost:9090/router/dispatch \
  -H "Content-Type: application/json" \
  -d '{"text": "docker ps"}' | python3 -m json.tool

# Test conversa
curl -s -X POST http://localhost:9090/router/dispatch \
  -H "Content-Type: application/json" \
  -d '{"text": "explica en una frase que és Docker"}' | python3 -m json.tool
```

Per `temps_data` esperat: `"result": "Ara són les HH:MM del ..."`.
Per `info_sistema` esperat: `"cmd": "docker ps ..."`, `"result": "NAMES STATUS ..."`.
Per `conversa`: `"result": "Docker és..."`.

- [ ] **Step 8: Commit**

```bash
cd /home/usuari/Projects/bartolo
git add -A
git commit -m "feat: /router/dispatch endpoint + _router_dispatch() L3 handlers"
```

---

## Task 4: `openwebui_tool_repo_agent.py` — `classifica_i_resol()` (v3.0)

**Files:**
- Modify: `/home/usuari/Projects/bartolo/openwebui_tool_repo_agent.py`

- [ ] **Step 1: Afegeix la versió al header i la funció `classifica_i_resol`**

Modifica el header de la tool (línia 1-6):

```python
"""
title: Universal Repo Agent
author: usuari
version: 3.0
description: Router + wizard + exec_shell + upload. v3.0: classifica_i_resol router generalista.
"""
```

Afegeix la funció al final de la classe `Tools`, just abans del tancament de classe:

```python
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
        source = r.get("source", "?")

        # Redirect: l'acció requereix una altra tool (cerca_web)
        if r.get("redirect"):
            return r.get("message", f"Redirigit a: {r['redirect']}")

        # Si és munta_repo i ha retornat un wizard o job
        if intent == "munta_repo":
            if r.get("done") and r.get("job_id"):
                return f"🚀 Muntant en mode ràpid...\n\n" + self._wait_for_job(r["job_id"])
            if r.get("wizard_id"):
                return (f"🧙 Wizard iniciat (id: `{r['wizard_id']}`)\n\n"
                        f"{r.get('question', '')}\n\n"
                        f"_Respon amb `respon_wizard('{r['wizard_id']}', 'la teva resposta')`_")
            if r.get("error"):
                return f"❌ {r['error']}"

        result = r.get("result", "")
        if not result and "error" in r:
            return f"❌ {r['error']}"

        # Format per intent
        if intent == "temps_data":
            return result
        if intent == "info_sistema":
            cmd = r.get("cmd", "")
            return f"```\n{result}\n```" if result else "(sense sortida)"
        if intent == "gestio_docker":
            return result or f"Container actualitzat."

        # conversa_general i resta
        return result or "(sense resposta)"
```

- [ ] **Step 2: Verifica sintaxi**

```bash
python3 -m py_compile /home/usuari/Projects/bartolo/openwebui_tool_repo_agent.py && echo "✅ OK"
```

- [ ] **Step 3: Actualitza la tool a OpenWebUI via API**

```bash
NEW_TOKEN=$(curl -s -X POST http://localhost:3000/api/v1/auths/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "aclivi@gmail.com", "password": "99449944Nn"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

CONTENT=$(cat /home/usuari/Projects/bartolo/openwebui_tool_repo_agent.py)

python3 - "$NEW_TOKEN" "$CONTENT" << 'PYEOF'
import sys, json, urllib.request

token = sys.argv[1]
content = sys.argv[2]

# Llegeix meta actual
req = urllib.request.Request("http://localhost:3000/api/v1/tools/universal_repo_agent",
    headers={"Authorization": f"Bearer {token}"})
with urllib.request.urlopen(req, timeout=10) as r:
    existing = json.loads(r.read())

payload = {
    "id": "universal_repo_agent",
    "name": existing["name"],
    "content": content,
    "meta": existing.get("meta", {}),
    "access_grants": existing.get("access_grants", [])
}
data = json.dumps(payload).encode()
req2 = urllib.request.Request(
    "http://localhost:3000/api/v1/tools/id/universal_repo_agent/update",
    data=data, method="POST",
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
)
with urllib.request.urlopen(req2, timeout=10) as r:
    resp = json.loads(r.read())
    specs = resp.get("specs", [])
    names = [s["name"] for s in specs]
    print("✅ Tool actualitzada. Funcions:", names)
PYEOF
```

Esperat: llista de funcions que inclou `classifica_i_resol`.

- [ ] **Step 4: Reinicia open-webui per aplicar la nova tool**

```bash
docker restart open-webui
sleep 10
curl -s http://localhost:3000/api/v1/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('OW:', d)" 2>/dev/null || echo "OW reiniciant..."
```

- [ ] **Step 5: Commit**

```bash
cd /home/usuari/Projects/bartolo
git add openwebui_tool_repo_agent.py
git commit -m "feat: classifica_i_resol v3.0 — tool router generalista per OpenWebUI"
```

---

## Task 5: Actualitza el system prompt de Bartolo

**Files:**
- Modifica Bartolo via API OpenWebUI (no fitxer)

- [ ] **Step 1: Actualitza el system prompt per mencionar classifica_i_resol**

```bash
NEW_TOKEN=$(curl -s -X POST http://localhost:3000/api/v1/auths/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "aclivi@gmail.com", "password": "99449944Nn"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

python3 << PYEOF
import urllib.request, json

token = "$NEW_TOKEN"

SYSTEM = """Ets en Bartolo, un assistent local especialitzat en gestió de repositoris i serveis.

REGLES D'ÚS DE TOOLS:
1. Per a QUALSEVOL pregunta general (hora, data, conversa, explicacions), usa classifica_i_resol(text).
2. Per a consultes del sistema (containers, ports, versions, processos, logs), usa consulta_info(cmd) O classifica_i_resol(text).
3. Per muntar un repo nou, usa inicia_muntatge(repo_url) o classifica_i_resol(text).
4. Per aturar/reiniciar serveis, usa atura_repo o refresca_repo directament.
5. Per executar comandes al host, usa proposa_comanda_shell (requereix confirmació de l'usuari).
6. MAI responguis de memòria a preguntes sobre l'estat del sistema — usa sempre les tools.
7. Respon sempre en català."""

payload = {
    "id": "bartolo",
    "base_model_id": "qwen2.5:14b",
    "name": "Bartolo",
    "meta": {
        "description": None,
        "capabilities": {
            "file_context": True, "vision": True, "file_upload": True,
            "web_search": True, "image_generation": True, "code_interpreter": True,
            "terminal": True, "citations": True, "status_updates": True, "builtin_tools": True
        },
        "suggestion_prompts": None,
        "tags": [],
        "toolIds": ["universal_repo_agent", "web_search"]
    },
    "params": {"system": SYSTEM},
    "access_grants": [],
    "is_active": True
}

data = json.dumps(payload).encode()
req = urllib.request.Request(
    "http://localhost:3000/api/v1/models/model/update?id=bartolo",
    data=data, method="POST",
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
)
with urllib.request.urlopen(req, timeout=10) as r:
    resp = json.loads(r.read())
    sp = resp.get("params", {}).get("system", "")
    print("✅ System prompt actualitzat (" + str(len(sp)) + " chars)")
PYEOF
```

- [ ] **Step 2: Verifica el system prompt persistit**

```bash
NEW_TOKEN=$(curl -s -X POST http://localhost:3000/api/v1/auths/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "aclivi@gmail.com", "password": "99449944Nn"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

curl -s "http://localhost:3000/api/v1/models/model?id=bartolo" \
  -H "Authorization: Bearer $NEW_TOKEN" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); sp=d.get('params',{}).get('system',''); print('✅ OK' if sp else '❌ buit')"
```

---

## Task 6: Test end-to-end via Bartolo

- [ ] **Step 1: Test directe del router per als 5 intents principals**

```bash
for query in \
  "quina hora és?" \
  "docker ps" \
  "quant espai lliure hi ha al disc?" \
  "explica'm en 2 frases que és un microservei" \
  "cerca a internet: que és LangChain?"; do
  echo "=== $query ==="
  curl -s -X POST http://localhost:9090/router/dispatch \
    -H "Content-Type: application/json" \
    -d "{\"text\": \"$query\"}" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'  intent={d.get(\"intent\")} source={d.get(\"source\")}')
r = d.get('result','') or d.get('error','') or d.get('message','')
print(f'  result: {str(r)[:100]}')
"
  echo
done
```

- [ ] **Step 2: Test via Ollama que el model crida classifica_i_resol**

```bash
NEW_TOKEN=$(curl -s -X POST http://localhost:3000/api/v1/auths/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "aclivi@gmail.com", "password": "99449944Nn"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

SPECS=$(curl -s http://localhost:3000/api/v1/tools/ \
  -H "Authorization: Bearer $NEW_TOKEN" | python3 -c "
import sys,json
tools=json.load(sys.stdin)
result=[]
for t in tools:
    if t['id']=='universal_repo_agent':
        for s in t.get('specs',[]):
            result.append({'type':'function','function':{'name':s['name'],'description':s['description'],'parameters':s['parameters']}})
print(json.dumps(result))
")

python3 - "$SPECS" << 'PYEOF'
import sys, json, urllib.request

specs = json.loads(sys.argv[1])
test_msgs = [
    "quina hora és ara?",
    "quins containers Docker estan corrent?",
    "explica'm que és una API REST",
]
for msg in test_msgs:
    payload = {"model": "qwen2.5:14b", "stream": False, "tools": specs,
               "messages": [{"role": "user", "content": msg}]}
    req = urllib.request.Request("http://localhost:11434/api/chat",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    msg_resp = d.get("message", {})
    tc = msg_resp.get("tool_calls")
    if tc:
        fn = tc[0]["function"]["name"]
        args = tc[0]["function"].get("arguments", {})
        print(f"✅ '{msg[:40]}' → {fn}({json.dumps(args)[:60]})")
    else:
        print(f"❌ '{msg[:40]}' → TEXT: {msg_resp.get('content','')[:60]}")
PYEOF
```

Esperat: les 3 preguntes criden `classifica_i_resol` o una tool específica adequada.

- [ ] **Step 3: Commit final**

```bash
cd /home/usuari/Projects/bartolo
git add -A
git commit -m "feat: router generalista complet — L1+L2+L3 + classifica_i_resol v3.0"
git push origin main
```

---

## Checklist de verificació post-implementació

- [ ] `python3 test_router.py` → 9/9 tests passats
- [ ] `curl http://localhost:9090/router/dispatch` retorna resultats per tots els intents
- [ ] `classifica_i_resol` apareix a la llista de funcions de la tool a OpenWebUI
- [ ] Bartolo respon "Ara són les..." quan li preguntes l'hora sense hal·lucinar
- [ ] Bartolo mostra `docker ps` real quan preguntes pels containers
- [ ] El bridge no té errors de sintaxi (`python3 -m py_compile`)

---

## Notes tècniques

**VRAM**: `_router_dispatch` per a `conversa_general` crida `qwen2.5:14b` directament a Ollama (ja carregat). El L2 usa `qwen2.5:7b` si disponible (no carregat simultàniament amb el 14b per defecte). Cap model nou requerit.

**Fallback si Ollama no respon**: `classify_l2` retorna `{"intent": "conversa"}` i `_router_dispatch` per a `conversa_general` captura l'excepció i retorna l'error. El sistema no peta.

**`cerca_web`**: El bridge no fa cerques web (no té accés al DuckDuckGo tool d'OpenWebUI). El `/router/dispatch` retorna un redirect que la tool transforma en un missatge indicant que cal usar `web_search` directament. Correcte per disseny.

**Import condicional**: `_ROUTER_AVAILABLE = False` si `bartolo_router.py` no es troba. L'endpoint `/router/dispatch` retorna error clar en lloc de crash.
