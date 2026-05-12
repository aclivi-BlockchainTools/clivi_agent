# Bartolo v6 — Refactor Modular + Aprenentatge amb DeepSeek

Data: 2026-05-12
Estat: Aprovat
Objectiu: Portar Bartolo al màxim de fiabilitat, mantenibilitat i intel·ligència adaptativa

## 1. Problemes arrel de v5.3

| Dimensió | Problema | Impacte |
|----------|----------|---------|
| Estructural | Agent monolític de 4067 línies | Modificar qualsevol cosa requereix navegar 4000 línies; risc de regressions |
| Fiabilitat | 50 `except Exception` | Errors silenciats; impossible saber per què falla un pas |
| Fiabilitat | Comandes generades per concatenació de strings | Fàcil introduir bugs de sintaxi; difícil de debugar |
| Fiabilitat | Health checks per temps (sleep 3 + 90×2s) | Lent; no valida que l'app funcioni realment |
| Interacció | Wizard del bridge fràgil | Preguntes buides; repos existents no s'analitzen |
| Interacció | Sense feedback en temps real | L'usuari espera minuts sense saber què passa |
| Aprenentatge | KB d'èxits manual | Bartolo no millora amb l'experiència; errors repetits |
| Testabilitat | 0 tests d'integració E2E | bench.sh només comprova return codes |

## 2. Arquitectura v6

### 2.1 Visió general

```
[Usuari] → OpenWebUI :3001 → Tools → agent_http_bridge.py :9090 → Bartolo v6
                  ↓                      ↓ (SSE streaming)            ↓
              Ollama :11434         Dashboard :9999              DeepSeek API
              (classificació L2)    (WebSocket v6)              (repair + learn)
                                         ↓
                              ┌──────────┴──────────┐
                              │    bartolo/ (v6)     │
                              │  detectors/ planner  │
                              │  executor provisioner│
                              │  smoke preflight     │
                              │  repair/ (deepseek)  │
                              │  kb/ (success+repair)│
                              └─────────────────────┘
```

### 2.2 Canvis per capa

| Capa | v5 | v6 |
|------|-----|-----|
| Agent | 1 fitxer 4067 línies | 20+ fitxers, cap >500 línies |
| Plans | Strings concatenats | Dataclasses estructurades (ja existeixen, refinades) |
| Errors | 50 `except Exception` | Jerarquia `AgentError` → `DetectorError`, `StepError`, `ProvisionerError` |
| Comandes | `f"setsid nohup {rest}"` | Dataclass `ShellCommand` amb build mètode |
| Bridge | Polling `_job_stream` | SSE `text/event-stream` per streaming en temps real |
| Dashboard | Estàtic 254 línies | WebSocket, progrés en temps real |
| Reparació | Ollama → Anthropic | KB → DeepSeek → Anthropic (3 nivells) |
| Aprenentatge | KB d'èxits (manual) | KB de reparacions auto-alimentada |

## 3. Sistema d'aprenentatge amb DeepSeek

### 3.1 El problema

Bartolo v5 no aprèn dels errors. Si un `pip install` falla per un error concret, la pròxima vegada que passi el mateix error, torna a fallar i escala al debugger (lent, consumeix model).

### 3.2 Loop de reparació en 4 nivells

```
Step fails
  ↓
1. Plan B fallbacks (local, gratis)
   - _FALLBACK_MAP: alternatives predefinides per error comú
   - Ex: pnpm install → npm install, pip install → pip install --break-system-packages
  ↓ fail
2. KB de reparacions: cerca signatura (error pattern hash)
   - Signatura: stack + missatge d'error normalitzat → hash
   - Hit → aplica solució guardada → registra hit_count++
   - O(1) lookup
  ↓ miss
3. DeepSeek API: envia context (stack, error, logs, pas intentat)
   - Rep comanda corregida o diagnòstic
   - Aplica → si OK → GUARDA a KB: signatura → solució
   - ~10x més barat que Anthropic
  ↓ fail
4. Anthropic fallback (últim recurs)
   - Mateix context que DeepSeek però amb razonament més potent
   - Si OK → GUARDA a KB
   - Si fail → ErrorReporter (escalat a l'usuari)
```

### 3.3 Estructura de la KB de reparacions

Fitxer: `~/.universal-agent/repair_kb.json`

```json
{
  "node+npm::pnpm_command_not_found": {
    "pattern": "pnpm: command not found",
    "solution": "corepack enable && corepack prepare pnpm@latest --activate",
    "stack": "node+npm",
    "error_type": "ENOENT",
    "hits": 3,
    "source": "deepseek",
    "created": "2026-05-15T10:30:00Z",
    "last_used": "2026-05-20T14:22:00Z"
  },
  "python+fastapi::keyerror_mongodb_url": {
    "pattern": "KeyError.*MONGODB_URL",
    "solution": "test -f .env && export $(grep -v '^#' .env | grep -v '^$' | xargs)",
    "stack": "python+fastapi+pip",
    "error_type": "KeyError",
    "hits": 5,
    "source": "deepseek",
    "created": "2026-05-16T08:00:00Z",
    "last_used": "2026-05-20T09:00:00Z"
  }
}
```

**Generació de signatures:**
```python
def repair_signature(stack: str, error_message: str) -> str:
    normalized = re.sub(r'\d+', 'N', error_message.lower().strip())
    normalized = re.sub(r'0x[0-9a-f]+', 'HEX', normalized)
    normalized = re.sub(r'/[^\s]+', 'PATH', normalized)
    return f"{stack}::{hashlib.md5(normalized.encode()).hexdigest()[:16]}"
```

Això normalitza missatges d'error perquè siguin reutilitzables (números concrets, paths, etc. s'abstreuen) però manté la signatura única per patró.

### 3.4 DeepSeek API client

```python
# bartolo/repair/deepseek.py

DEEPSEEK_MODEL = "deepseek-chat"  # o deepseek-reasoner per casos difícils

def repair_with_deepseek(
    stack: str,
    error: str,
    step_command: str,
    repo_context: dict,
    api_key: str
) -> Optional[str]:
    """
    Envia l'error a DeepSeek i retorna la comanda corregida,
    o None si DeepSeek no pot resoldre-ho.
    
    El prompt inclou:
    - Stack + manifests detectats
    - Comanda que ha fallat
    - Sortida completa de l'error (stdout + stderr)
    - Context del repo (llista de fitxers, estructura)
    - Instrucció: retorna NOMÉS la comanda Bash corregida, res més
    """
```

La resposta de DeepSeek es valida amb `validate_command()` abans d'executar-la. Si no passa la validació, s'escala a Anthropic.

### 3.5 Integració amb IntelligentDebugger

L'`IntelligentDebugger` actual (`agents/debugger.py`, 670 línies) es migra a `bartolo/repair/debugger.py` i s'amplia:

```python
class IntelligentDebugger:
    def debug(self, step_error: StepError, analysis: RepoAnalysis) -> RepairResult:
        # 1. Plan B fallbacks (local)
        fallback = self._try_fallbacks(step_error)
        if fallback.success:
            return fallback
        
        # 2. KB lookup (local, gratis)
        kb_hit = self.repair_kb.lookup(analysis.stack_key, step_error.message)
        if kb_hit:
            return self._apply_kb_solution(kb_hit, step_error)
        
        # 3. DeepSeek (API, barat)
        deepseek = self._repair_with_deepseek(step_error, analysis)
        if deepseek.success:
            self.repair_kb.record(analysis.stack_key, step_error.message,
                                  deepseek.solution, source="deepseek")
            return deepseek
        
        # 4. Anthropic (API, car)
        anthropic = self._repair_with_anthropic(step_error, analysis)
        if anthropic.success:
            self.repair_kb.record(analysis.stack_key, step_error.message,
                                  anthropic.solution, source="anthropic")
            return anthropic
        
        # 5. Escalate
        return self._escalate(step_error)
```

## 4. Estructura de mòduls

```
~/Projects/bartolo/
├── bartolo/                    # Nou paquet Python
│   ├── __init__.py
│   ├── types.py                # Dataclasses: ServiceInfo, RepoAnalysis, CommandStep...
│   ├── exceptions.py           # Jerarquia: AgentError, DetectorError, StepError...
│   ├── validator.py            # validate_command + ShellCommand builder
│   ├── shell.py                # run_shell + maybe_background_command
│   ├── detectors/              # 12 detectors, 1 per fitxer
│   │   ├── __init__.py         # ALL_DETECTORS registry + discover_candidate_dirs
│   │   ├── base.py             # Detector protocol (run(root) -> Optional[ServiceInfo])
│   │   ├── node.py             # Node.js (npm, yarn, pnpm)
│   │   ├── python.py           # Python (pip, poetry, uv)
│   │   ├── go.py
│   │   ├── rust.py
│   │   ├── ruby.py
│   │   ├── php.py
│   │   ├── java.py
│   │   ├── deno.py
│   │   ├── elixir.py
│   │   ├── dotnet.py
│   │   ├── docker.py
│   │   └── emergent.py
│   ├── planner.py              # build_deterministic_plan + choose_* helpers
│   ├── executor.py             # execute_plan + verify_step + rollback
│   ├── provisioner.py          # DB provisioning + env vars + cloud→local
│   ├── preflight.py            # preflight_check + system deps installation
│   ├── smoke.py                # run_smoke_tests + _framework_endpoints
│   ├── runtime.py              # read_runtime_versions + check_runtime_versions
│   ├── llm.py                  # ollama_chat_json + model helpers
│   ├── repair/                 # Sistema de reparació + aprenentatge
│   │   ├── __init__.py
│   │   ├── kb.py               # RepairKB: signatura, cerca, guardar
│   │   ├── fallback.py         # Plan B fallbacks (_FALLBACK_MAP ampliat)
│   │   ├── deepseek.py         # DeepSeek API client
│   │   ├── anthropic.py        # Anthropic API fallback
│   │   └── debugger.py         # IntelligentDebugger (migrat des de agents/)
│   ├── kb/                     # Knowledge bases
│   │   ├── __init__.py
│   │   └── success.py          # Success KB (migrat des de agents/)
│   ├── cli.py                  # parse_args + main (wrapper prim)
│   └── reporter.py             # print_analysis + print_plan + print_final_summary
├── agent_http_bridge.py        # Refactoritzat: SSE streaming, wizard arreglat
├── dashboard.py                # Refet: WebSocket, progress bars, logs en temps real
├── openwebui_tool_repo_agent.py # Compatible, sense canvis
├── bartolo_router.py           # Sense canvis (ja és modular, 253 línies)
├── bartolo_init.py             # Adaptat al nou paquet
├── universal_repo_agent_v5.py  # Mantingut com a entry point (wrapper a bartolo.cli)
├── bench.sh                    # Ampliat amb tests d'integració
├── stress_test.sh              # Sense canvis
├── tests/                      # Tests d'integració nous
│   ├── test_detectors.py       # Cada detector validat amb fixtures reals
│   ├── test_planner.py         # Plans generats correctament per stack
│   ├── test_executor.py        # Execució de passos amb mock de shell
│   ├── test_repair_kb.py       # Signatures, lookup, record
│   ├── test_deepseek.py        # Client DeepSeek amb mock
│   └── test_e2e.py             # Tests end-to-end amb repos reals petits
└── legacy/                     # Fitxers antics (v4, patches aplicats)
```

### 4.1 Interfície de detector

```python
# bartolo/detectors/base.py

class DetectorProtocol(Protocol):
    """Cada detector implementa aquesta interfície."""
    def detect(self, path: Path) -> Optional[ServiceInfo]:
        """
        Analitza un directori i retorna ServiceInfo si detecta
        un servei del seu stack, o None si no.
        """
        ...

# Registre automàtic a bartolo/detectors/__init__.py
ALL_DETECTORS: List[DetectorProtocol] = [
    NodeDetector(),
    PythonDetector(),
    GoDetector(),
    RustDetector(),
    RubyDetector(),
    PhpDetector(),
    JavaDetector(),
    DenoDetector(),
    ElixirDetector(),
    DotnetDetector(),
    DockerDetector(),
    EmergentDetector(),
]
```

### 4.2 ShellCommand estructurat

```python
# bartolo/validator.py (ampliat)

@dataclass
class ShellCommand:
    """Comanda shell construïda de forma estructurada, no per strings."""
    executable: str          # p.e. "uvicorn"
    args: List[str]          # p.e. ["app:app", "--host", "0.0.0.0"]
    env: Dict[str, str]      # Variables d'entorn
    cwd: Optional[Path]      # Directori de treball
    background: bool = False # Si s'executa en background
    log_file: Optional[str] = None
    
    def build(self) -> str:
        """Genera la comanda shell completa."""
        parts = []
        if self.env:
            parts.extend(f"{k}={shlex.quote(v)}" for k, v in self.env.items())
        
        # Auto-load .env si existeix
        parts.append("test -f .env && export $(grep -v '^#' .env | grep -v '^$' | xargs);")
        
        cmd = f"{' '.join(parts)} {self.executable} {' '.join(self.args)}"
        
        if self.background:
            cmd = f"setsid nohup {cmd} > {self.log_file} 2>&1 < /dev/null & echo __AGENT_PID__=$!"
        
        return cmd
```

## 5. Bridge + Dashboard: streaming en temps real

### 5.1 Bridge SSE endpoint

Nou endpoint al bridge:

```
GET /job/{id}/stream
Content-Type: text/event-stream

data: {"event": "step_start", "step": 1, "total": 5, "label": "Instal·lant dependències"}
data: {"event": "log", "step": 1, "line": "Collecting fastapi..."}
data: {"event": "step_done", "step": 1, "status": "ok", "duration_ms": 3400}
data: {"event": "step_start", "step": 2, "total": 5, "label": "Arrencant MongoDB"}
data: {"event": "log", "step": 2, "line": "Container agent-mongo started"}
data: {"event": "step_done", "step": 2, "status": "ok", "duration_ms": 2100}
...
data: {"event": "done", "status": "success", "summary": "5/5 passos completats"}
```

Implementació: handler `do_GET` mira `path.startswith("/job/") and path.endswith("/stream")`, configura `response.headers["Content-Type"] = "text/event-stream"`, i escriu events a mesura que el job avança.

### 5.2 Dashboard v2

- HTML+JS vanilla, sense frameworks (mateixa filosofia que l'actual)
- `EventSource("/job/{id}/stream")` per rebre events
- Progress bar per pas, logs en scroll, estatus de BD
- Colors: verd (ok), groc (running), vermell (error), gris (pending)

## 6. Pla de migració en 4 fases

Cada fase acaba amb `bench.sh` verd abans de continuar.

### Fase 1: Fundació (1 setmana)

**Objectiu:** Crear el paquet `bartolo/` amb tipus, excepcions i validador. v5.py importa d'ell.

Fitxers nous:
- `bartolo/__init__.py`
- `bartolo/types.py` — migrar dataclasses existents
- `bartolo/exceptions.py` — jerarquia nova
- `bartolo/validator.py` — `validate_command` + `ShellCommand`
- `bartolo/shell.py` — `run_shell` + `maybe_background_command`

**Validació:** `bench.sh quick` verd + `universal_repo_agent_v5.py` funciona igual (importa tipus des de `bartolo.types`)

### Fase 2: Detectors + Executor (2 setmanes)

**Objectiu:** Migrar detectors a fitxers individuals + planner + executor + provisioner.

Fitxers nous/modificats:
- `bartolo/detectors/` (13 fitxers)
- `bartolo/planner.py`
- `bartolo/executor.py`
- `bartolo/provisioner.py`
- `bartolo/preflight.py`
- `bartolo/smoke.py`
- `bartolo/runtime.py`

**Validació:** `bench.sh` complet verd (11/11) + `stress_test.sh` verd

### Fase 3: Repair + DeepSeek (1 setmana)

**Objectiu:** Sistema d'aprenentatge complet.

Fitxers nous/modificats:
- `bartolo/repair/` (6 fitxers)
- `bartolo/kb/` (2 fitxers)
- `bartolo/llm.py`
- `bartolo/reporter.py`
- `bartolo/cli.py`

**Validació:** `bench.sh` complet verd + test manual amb un repo que falla → DeepSeek repara → KB guarda → segon intent repara des de KB

### Fase 4: Bridge SSE + Dashboard v2 (1 setmana)

**Objectiu:** Streaming en temps real + dashboard interactiu.

Fitxers nous/modificats:
- `agent_http_bridge.py` — SSE endpoint
- `dashboard.py` — WebSocket + EventSource

**Validació:** Desplegament E2E via OpenWebUI → el dashboard mostra progrés en temps real

## 7. Ampliacions de cobertura funcional

### 7.1 Detectors nous

| Detector | Senyal | Prioritat |
|----------|--------|-----------|
| Bun | `bun.lock`, `Bun.lockb` | Mitjana |
| SvelteKit | `svelte.config.js` + `vite.config.ts` | Baixa |
| Nuxt | `nuxt.config.ts` | Baixa |
| Astro | `astro.config.mjs` | Baixa |
| Hugo | `config.toml` amb `baseURL` | Baixa |
| WebSocket apps | `socket.io`, `ws` a package.json, `fastapi.WebSocket` | Mitjana |
| Workers (Celery) | `celery` a requirements.txt / pyproject.toml | Mitjana |
| Workers (BullMQ) | `bullmq` a package.json | Mitjana |

### 7.2 Millores al provisioner

- `.env` amb secrets xifrats via `age` (`age -d secrets.env.age`)
- Suport per a `DATABASE_URL` format RFC 3986 (postgresql://user:pass@host/db)
- Templates de `.env` per a cada stack (valors per defecte intel·ligents)

## 8. Test harness

### 8.1 Tests d'integració per detectors

Cada detector té fixtures reals (repos petits al workspace) i es valida que:
- Detecta correctament el stack
- Extreu les dependències correctes
- No dona falsos positius en repos d'altres stacks

### 8.2 Tests E2E

Nous tests a `tests/test_e2e.py`:
- Clonar repo petit → detectar → generar pla → executar → verificar smoke test
- 5 repos representatius (node, python/flask, python/fastapi+mongo, go, deno)

### 8.3 bench.sh ampliat

- Mode `integration` que executa els tests Python
- Mode `e2e` que executa tests E2E amb repos reals

## 9. Secrets i configuració

### 9.1 DeepSeek API key

Emmagatzemada a `~/.universal-agent/secrets.json`:
```json
{
    "deepseek_api_key": "sk-...",
    "anthropic_api_key": "sk-ant-..."
}
```

### 9.2 Configuració via variables d'entorn

- `DEEPSEEK_API_KEY`: prioritat sobre secrets.json
- `DEEPSEEK_MODEL`: default `deepseek-chat`, opcional `deepseek-reasoner`
- `BARTOLO_REPAIR_MODE`: `kb_only` | `kb+deepseek` (default) | `kb+deepseek+anthropic`

## 10. Mètriques d'èxit

| Mètrica | v5.3 actual | v6 objectiu |
|---------|-------------|-------------|
| Bench pass rate | 100% (11/11) | 100% (11/11 + 5 E2E) |
| Except Exception | 50 | 0 |
| Fitxer més gran | 4067 línies | <500 línies |
| Cobertura tests | ~10% (unittest aïllats) | >70% (unit + integració + E2E) |
| Temps mig health check | 180s (sleep-based) | 30s (HTTP-based) |
| Reparació autònoma | 60% (Ollama + Anthropic) | >85% (KB + DeepSeek + Anthropic) |
| Feedback usuari | Només al final | En temps real (SSE) |
| Taxa aprenentatge | 0 (KB manual) | Creix amb cada error (KB auto) |
