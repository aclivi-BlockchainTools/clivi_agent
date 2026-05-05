# Intelligent Debugger — Design Spec
**Data:** 2026-05-05  
**Estat:** Aprovat, pendent d'implementació  
**Branca origen:** fix/upload-form-js  

---

## Problema

El debugger actual de `universal_repo_agent_v5.py` té tres defectes estructurals:

1. `diagnose_error_with_model` no veu el context del repo (stack, arrel, serveis).
2. `ask_model_for_repair` no sap res dels intents anteriors — cada crida és independent.
3. No hi ha memòria entre sessions: el mateix error es consulta al model cada vegada.

---

## Objectiu

Substituir les dues funcions soltes i el loop de reparació (línies ~2416–2607 de `v5.py`) per un mòdul `agents/debugger.py` que:

- Manté **conversa multi-torn** amb el model durant una sessió de reparació.
- Consulta una **Knowledge Base** (KB) local abans de cridar cap model.
- Usa l'**API d'Anthropic** com a fallback quan Ollama s'esgota.
- **Aprèn** de cada fix exitós per no repetir la mateixa consulta a la API.

---

## Arquitectura

### Components

```
agents/debugger.py
├── RepairKB              — gestió de la memòria persistent
├── Diagnosis             — dataclass resultat de diagnosi
├── RepairResult          — dataclass resultat de reparació
└── IntelligentDebugger   — orquestrador principal
    ├── repair()                  — punt d'entrada públic
    ├── _kb_lookup()              — cerca a la KB abans del model
    ├── _diagnose()               — diagnosi Ollama amb context repo
    ├── _build_system_prompt()    — prompt de sistema amb KB + repo
    ├── _repair_loop_ollama()     — loop multi-torn Ollama
    ├── _repair_with_anthropic()  — fallback API Anthropic
    └── _save_kb()                — guarda fix exitós a la KB
```

### Flux principal de `repair(step, result)`

```
1. KB lookup          → si hi ha fix conegut, prova'l directament
                        si falla, continua al pas 2 (no s'atura)
2. Diagnosi Ollama    → amb context del repo (stack, arrel, serveis)
3. Loop multi-torn    → fins a MAX_REPAIR_ATTEMPTS amb historial acumulat
                        (MAX_REPAIR_ATTEMPTS = constant de v5.py, reutilitzada)
4. Fallback Anthropic → si Ollama s'esgota sense èxit
5. Save KB            → si qualsevol fix funciona (KB/Ollama/Anthropic), guarda'l
6. Return RepairResult
```

---

## Knowledge Base (KB)

### Fingerprinting

Clau única per identificar un error de forma robusta (tolerant a variacions menors del missatge):

```
fingerprint = sha256(stack + "|" + error_type + "|" + top3_keywords)[:12]
```

- **stack**: `python`, `node`, `go`, `docker`, etc. (de `analysis.services`)
- **error_type**: categoria del diagnòstic (`missing_dependency`, `port_conflict`, etc.)
- **top3_keywords**: 3 tokens més significatius del stderr (filtrant stop words i números de línia)

Exemple: `python|missing_dependency|ModuleNotFoundError+requests+pip` → `a3f8c2d91b4e`

### Fitxer JSON (`~/.universal-agent/repair_kb.json`)

Lookup ràpid per fingerprint exacte:

```json
{
  "a3f8c2d91b4e": {
    "stack": "python",
    "error_type": "missing_dependency",
    "keywords": ["ModuleNotFoundError", "requests", "pip"],
    "fix_command": "pip install -r requirements.txt",
    "success_count": 3,
    "last_seen": "2026-05-05T12:00:00",
    "source": "ollama"
  }
}
```

### Fitxers Markdown (`~/.universal-agent/repair_kb_{stack}.md`)

Un fitxer per stack, injectat com a context al model quan no hi ha match exacte:

```markdown
# Python — fixes coneguts

## missing_dependency / ModuleNotFoundError
Fix: `pip install -r requirements.txt`
Vist: 3 vegades · Font: ollama

## port_conflict / Address already in use
Fix: `fuser -k 8000/tcp && uvicorn main:app --port 8000`
Vist: 1 vegada · Font: anthropic
```

---

## Conversa multi-torn amb Ollama

L'historial s'acumula durant la sessió de reparació d'un error concret. Estructura:

```
[system]  Context repo + KB rellevant (injectat una sola vegada)
[user]    "Ha fallat: {command}. Stderr: {stderr}"
[assist]  {"command": "pip install -r requirements.txt", "reason": "..."}
[user]    "He executat la comanda. Ha fallat amb codi 1. Stderr: {nou_stderr}"
[assist]  {"command": "pip install requests flask", "reason": "..."}
... fins a MAX_REPAIR_ATTEMPTS
```

### Missatge de sistema

```
Ets un expert en desplegar repositoris a Linux.
Stack detectat: python / fastapi
Arrel del repo: /home/usuari/universal-agent-workspace/my-repo
Fitxers rellevants: requirements.txt, .env.example
KB de fixes coneguts:
  [missing_dependency] pip install -r requirements.txt (vist 3 vegades)
Regles: sense sudo, sense comandes destructives, cwd fix.
```

---

## Fallback a l'API d'Anthropic

### Activació

Només si tots els intents d'Ollama han fallat.

### Payload

El debugger passa **tot l'historial acumulat** (intents fallits d'Ollama) a Claude:

```python
messages = [
    *conversation_history,
    {
        "role": "user",
        "content": f"Ollama ha esgotat {MAX_REPAIR_ATTEMPTS} intents sense èxit. "
                   f"Necessito una solució definitiva."
    }
]
```

### Model i configuració

- Model: `claude-sonnet-4-6`
- El missatge de sistema (context repo + KB) s'envia amb `cache_control: ephemeral` (prompt caching)
- API key: `ANTHROPIC_API_KEY` (env var) o `anthropic_api_key` a `~/.universal-agent/secrets.json`
- Si no hi ha clau o `anthropic` no està instal·lat → degradació graceful, es registra al `ErrorReporter`

### Configuració de la clau

```bash
# Una sola vegada:
python3 -c "
import json, os
path = os.path.expanduser('~/.universal-agent/secrets.json')
d = json.load(open(path)) if os.path.exists(path) else {}
d['anthropic_api_key'] = 'sk-ant-...'
json.dump(d, open(path, 'w'), indent=2)
os.chmod(path, 0o600)
print('Clau guardada.')
"
```

---

## Integració a `v5.py`

### Codi que desapareix

- Línies ~2416–2434: `diagnose_error_with_model` i `ask_model_for_repair`
- Línies ~2549–2607: loop de diagnosi + reparació + crida a `ErrorReporter`

### Codi nou

```python
from agents.debugger import IntelligentDebugger

debugger = IntelligentDebugger(model=model, analysis=analysis, workspace=workspace)
repair_result = debugger.repair(step, current_result, approve_all=approve_all)
results.extend(repair_result.execution_results)
errors.append(repair_result.to_step_error())
if not repair_result.repaired and step.critical:
    raise AgentError(f"Critical step failed: {step.title}")
```

`IntelligentDebugger` absorbeix internament: execució de comandes, logs per intent, `register_service`, `verify_step` i `ErrorReporter`.

---

## Dependències

| Dependència | Ús | Obligatòria |
|---|---|---|
| `anthropic` (PyPI) | Fallback API | No — degradació graceful si absent |
| `hashlib`, `json`, `os`, `pathlib` | KB + secrets | Sí (stdlib) |

Instal·lació opcional: `pip install anthropic`

---

## Fitxers afectats

| Fitxer | Canvi |
|---|---|
| `agents/debugger.py` | **NOU** |
| `universal_repo_agent_v5.py` | Eliminació ~2416–2434 + ~2549–2607, nova crida |
| `~/.universal-agent/repair_kb.json` | Creat en runtime |
| `~/.universal-agent/repair_kb_{stack}.md` | Creat en runtime |

---

## Fora d'abast (per ara)

- Exposició via bridge HTTP (enfocament 3 descartat)
- UI al dashboard per visualitzar la KB
- Comprovació de la clau Anthropic a `bartolo-doctor.sh`
