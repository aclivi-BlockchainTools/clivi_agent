# Dashboard v2.1 — Xat amb històrics + millores UI

**Data:** 2026-05-12
**Estat:** Aprovat

## Visió general

Millora principal del dashboard: xat amb múltiples fils de conversa persistents (com ChatGPT), navegació d'historial d'inputs amb fletxa amunt (com terminal), i 7 millores addicionals a la resta de pestanyes.

## Fase 1: Xat amb històrics

### Backend: chat_routes.py (nou fitxer)

Emmagatzematge a `~/.bartolo/chats/`:
- `threads.json` — índex de fils `[{id, title, created_at, updated_at, msg_count}]`
- `t-{id}.json` — missatges d'un fil `[{role, content, timestamp}]`
- `input_history.json` — últims 100 inputs enviats (global, per fletxa ↑)

Endpoints:
- `GET /api/chat/threads` — llista tots els fils
- `POST /api/chat/threads` — crea fil nou `{title?}`, retorna thread_id
- `DELETE /api/chat/threads/{id}` — elimina fil + fitxer JSON
- `PUT /api/chat/threads/{id}` — reanomena fil `{title}`
- `GET /api/chat/threads/{id}` — retorna missatges del fil
- `GET /api/chat/history` — retorna historial d'inputs

### WebSocket: chat.py (modificat)

- Client envia `{type:"chat", thread_id, message}`
- Servidor guarda cada missatge user/assistant al fitxer del fil
- En connectar, envia historial previ: `{type:"history", messages:[...]}`
- Si el fil no existeix, es crea automàticament (títol = primer missatge)

### Frontend: templates.py (modificat)

Components nous:
1. **ThreadSidebar**: llista de fils, fil actiu ressaltat, botó +, reanomenar/eliminar
2. **ChatMessages**: carrega historial, scroll automàtic, bombolles user/assistant
3. **ChatInput millorat**: ↑/↓ historial d'inputs (local), Enter envia, Shift+Enter salt línia
4. **ThreadHeader**: títol editable amb doble click, auto-títol del primer missatge

Keyboard shortcuts:
- `↑` — input anterior (historial)
- `↓` — input següent / buit original
- `Enter` — enviar
- `Shift+Enter` — salt de línia
- `Ctrl+N` — xat nou
- `Ctrl+W` — eliminar fil actual (amb confirmació)
- `Ctrl+←/→` — navegar entre fils

## Fase 2: Millores dashboard

### 1. Repos: logs en temps real + controls
- Panell de logs desplegable inline amb scroll automàtic (substitueix popup)
- Botons Start/Stop/Restart per servei individual
- Indicador de salut (verd/groc/vermell segons HTTP check)

### 2. Notificacions toast globals
- Toasts flotants (cantonada dreta inferior)
- Eventos: repo arrencat, error, container aturat, model descarregat
- Auto-desapareixen en 5s
- Cua de fins a 3 toasts simultanis

### 3. Shell: output en temps real via WebSocket
- WebSocket `/ws/shell` amb output línia per línia
- Substitueix el flux token+confirmació
- Suport per Ctrl+C (SIGINT)
- Historial de comandes executades

### 4. Models: barra de progrés en descàrrega
- Ollama pull mostra % + velocitat en temps real
- Cancel·lable
- Info VRAM estimada abans de descarregar

### 5. Repos: timeline d'events
- Timeline visual per repo: "arrencat 12:03", "error build 12:04", "reparat 12:06"
- Extret dels logs de l'agent

### 6. Eines: syntax highlight a l'editor
- Modal d'edició amb números de línia
- Highlighting bàsic Python (paraules clau, strings, comentaris)
- Confirmació abans de desar

### 7. Auto-refresh intel·ligent
- Polling adaptatiu: 2s amb canvis recents, 15s estable
- Pestanyes en background no fan polling

## Fitxers afectats

| Fitxer | Acció |
|--------|-------|
| `bartolo/dashboard/chat_routes.py` | NOU — endpoints REST threads + history |
| `bartolo/dashboard/chat.py` | MOD — WS amb thread_id + persistència |
| `bartolo/dashboard/templates.py` | MOD — sidebar fils, input ↑↓, toasts, totes millores |
| `bartolo/dashboard/__init__.py` | MOD — registrar chat_routes, lifespan crea ~/.bartolo/chats/ |
| `bartolo/dashboard/repos_routes.py` | MOD — start/stop/restart + timeline |
| `bartolo/dashboard/shell_routes.py` | MOD — WS /ws/shell |

## Ordre d'implementació

1. `chat_routes.py` — backend threads/history
2. `chat.py` — WS ampliat amb thread_id
3. `templates.py` — sidebar fils + input ↑↓ (nucli xat)
4. `templates.py` — toasts + auto-refresh (millores globals)
5. `repos_routes.py` + `templates.py` — logs inline + controls + timeline
6. `shell_routes.py` + `templates.py` — WS shell real-time
7. Models/tools — progrés + syntax highlight

## Verificació

```bash
# 1. bench.sh quick 6/6
# 2. Endpoints nous:
curl http://localhost:9999/api/chat/threads
curl -X POST http://localhost:9999/api/chat/threads -H 'Content-Type: application/json' -d '{}'
curl http://localhost:9999/api/chat/history
# 3. bartolo-doctor.sh dashboard OK
```
