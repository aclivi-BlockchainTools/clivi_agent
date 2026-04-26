#!/usr/bin/env bash
# =============================================================================
# bartolo-doctor.sh — Health check + auto-fix del sistema Bartolo
#
# Comprova tot el que cal perquè Bartolo funcioni i pot intentar arreglar
# els problemes detectats automàticament.
#
# Ús:
#   ./bartolo-doctor.sh           # només check, no toca res
#   ./bartolo-doctor.sh --fix     # arregla problemes simples (demana confirmació)
#   ./bartolo-doctor.sh --fix -y  # arregla automàticament sense preguntar
#   ./bartolo-doctor.sh --quiet   # només resum final
# =============================================================================

set -uo pipefail

# Colors
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
BLUE="\033[0;34m"
GRAY="\033[0;90m"
CYAN="\033[0;36m"
BOLD="\033[1m"
NC="\033[0m"

# Config (overridable via env vars)
BRIDGE_HOST="${BRIDGE_HOST:-localhost}"
BRIDGE_PORT="${BRIDGE_PORT:-9090}"
OLLAMA_HOST="${OLLAMA_HOST:-localhost}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
OPENWEBUI_CONTAINER="${OPENWEBUI_CONTAINER:-open-webui}"
COMPATIBLE_MODELS=("qwen2.5:14b" "qwen2.5:7b" "llama3.1:8b" "qwen3:8b")
INCOMPATIBLE_MODELS=("qwen2.5-coder:14b" "mistral-nemo:12b")
RECOMMENDED_MODEL="${COMPATIBLE_MODELS[0]}"
# EXPECTED_MODEL env var: override per a models nous que encara no estan a la llista
EXPECTED_TOOL_VERSION="${EXPECTED_TOOL_VERSION:-2.4}"
AGENT_DIR="${AGENT_DIR:-$HOME/universal-agent}"
BRIDGE_SCRIPT="${BRIDGE_SCRIPT:-$AGENT_DIR/agent_http_bridge.py}"

# Flags
FIX_MODE=0
AUTO_YES=0
QUIET_MODE=0
for arg in "$@"; do
    case "$arg" in
        --fix) FIX_MODE=1 ;;
        -y|--yes) AUTO_YES=1 ;;
        --quiet) QUIET_MODE=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
    esac
done

# Counters
CHECKS_PASS=0
CHECKS_WARN=0
CHECKS_FAIL=0
FIXES_APPLIED=0
FIXES_FAILED=0
MANUAL_FIXES=()

# Helpers
log() { [ $QUIET_MODE -eq 0 ] && echo -e "$@"; }
header() { log "\n${BOLD}${BLUE}━━━ $1 ━━━${NC}"; }
sublog() { log "   ${GRAY}$@${NC}"; }
pass() { log "${GREEN}✅${NC} $1"; CHECKS_PASS=$((CHECKS_PASS + 1)); }
warn() { log "${YELLOW}⚠️${NC}  $1"; [ -n "${2:-}" ] && sublog "→ $2"; CHECKS_WARN=$((CHECKS_WARN + 1)); }
fail() { log "${RED}❌${NC} $1"; [ -n "${2:-}" ] && sublog "→ $2"; CHECKS_FAIL=$((CHECKS_FAIL + 1)); }
fix_attempt() { log "${CYAN}🔧${NC} $1"; }
fix_done() { log "${GREEN}   ✓ $1${NC}"; FIXES_APPLIED=$((FIXES_APPLIED + 1)); }
fix_fail() { log "${RED}   ✗ $1${NC}"; FIXES_FAILED=$((FIXES_FAILED + 1)); }

ask_confirm() {
    local prompt="$1"
    if [ $AUTO_YES -eq 1 ]; then
        log "${CYAN}   $prompt → AUTO-YES${NC}"
        return 0
    fi
    echo -en "${CYAN}   $prompt? [s/N]:${NC} "
    read -r answer
    case "$answer" in
        s|S|y|Y|si|Si|SI|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

detect_bridge_token() {
    local pid
    pid=$(pgrep -f "agent_http_bridge.py" 2>/dev/null | head -1)
    [ -z "$pid" ] && { echo ""; return; }
    if [ -e "/proc/$pid/environ" ] && [ ! -r "/proc/$pid/environ" ]; then
        echo "__PERM_DENIED__"
        return
    fi
    [ -r "/proc/$pid/environ" ] || { echo ""; return; }
    tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | \
        grep "^BRIDGE_AUTH_TOKEN=" | cut -d= -f2-
}

test_bridge_health() {
    local url="$1"
    local token="$2"
    if [ -n "$token" ]; then
        curl -s --max-time 3 -H "X-Auth-Token: $token" "$url" 2>/dev/null
    else
        curl -s --max-time 3 "$url" 2>/dev/null
    fi
}

# =============================================================================
# AUTO-FIX FUNCTIONS
# =============================================================================

fix_arrenca_bridge() {
    fix_attempt "Bridge no corre"
    if [ ! -f "$BRIDGE_SCRIPT" ]; then
        fix_fail "No s'ha trobat: $BRIDGE_SCRIPT"
        return 1
    fi
    if ! ask_confirm "Arrencar bridge a port $BRIDGE_PORT (sense token)"; then
        return 1
    fi
    cd "$AGENT_DIR" || return 1
    nohup python3 "$BRIDGE_SCRIPT" --port "$BRIDGE_PORT" \
        > /tmp/bridge_doctor.log 2>&1 &
    disown
    sleep 2
    if pgrep -f "agent_http_bridge.py" >/dev/null; then
        fix_done "Bridge arrencat (PID $(pgrep -f agent_http_bridge.py | head -1))"
        return 0
    else
        fix_fail "No ha arrencat — mira /tmp/bridge_doctor.log"
        return 1
    fi
}

fix_reinicia_bridge() {
    fix_attempt "Reiniciant bridge sense token"
    if ! ask_confirm "Aturar i rearrencar el bridge sense token"; then
        return 1
    fi
    pkill -f "agent_http_bridge.py" 2>/dev/null || true
    sleep 1
    if [ ! -f "$BRIDGE_SCRIPT" ]; then
        fix_fail "$BRIDGE_SCRIPT no existeix"
        return 1
    fi
    cd "$AGENT_DIR" || return 1
    nohup python3 "$BRIDGE_SCRIPT" --port "$BRIDGE_PORT" \
        > /tmp/bridge_doctor.log 2>&1 &
    disown
    sleep 2
    if pgrep -f "agent_http_bridge.py" >/dev/null; then
        fix_done "Bridge reiniciat sense token"
        return 0
    else
        fix_fail "No ha reiniciat — mira /tmp/bridge_doctor.log"
        return 1
    fi
}

fix_arrenca_ollama() {
    fix_attempt "Iniciar servei Ollama"
    if ! ask_confirm "Cal sudo per a 'systemctl restart ollama'"; then
        return 1
    fi
    if sudo systemctl restart ollama 2>/dev/null; then
        sleep 3
        if curl -s --max-time 3 "http://${OLLAMA_HOST}:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; then
            fix_done "Ollama operatiu"
            return 0
        fi
        fix_fail "Reiniciat però no respon"
        return 1
    else
        fix_fail "systemctl restart ha fallat"
        return 1
    fi
}

fix_pull_model() {
    local target="${EXPECTED_MODEL:-$RECOMMENDED_MODEL}"
    fix_attempt "Descarregar $target"
    if ! ask_confirm "Descarregar ~8 GB"; then
        return 1
    fi
    if ollama pull "$target"; then
        fix_done "Model descarregat"
        return 0
    fi
    fix_fail "ollama pull ha fallat"
    return 1
}

fix_arrenca_openwebui() {
    fix_attempt "Iniciar container $OPENWEBUI_CONTAINER"
    if ! ask_confirm "docker start $OPENWEBUI_CONTAINER"; then
        return 1
    fi
    if docker start "$OPENWEBUI_CONTAINER" >/dev/null 2>&1; then
        sleep 3
        fix_done "Container iniciat"
        return 0
    fi
    fix_fail "docker start ha fallat"
    return 1
}

# =============================================================================
# Inici
# =============================================================================
log "${BOLD}🩺 Bartolo Doctor${NC}"
log "${GRAY}$(date '+%Y-%m-%d %H:%M:%S')   Mode: $([ $FIX_MODE -eq 1 ] && echo 'FIX' || echo 'CHECK')${NC}"

# 1. Bridge corrent?
header "1. Bridge HTTP"
BRIDGE_PID=$(pgrep -f "agent_http_bridge.py" | head -1)
if [ -n "$BRIDGE_PID" ]; then
    BRIDGE_CMD=$(ps -p "$BRIDGE_PID" -o cmd= 2>/dev/null | head -c 80)
    pass "Bridge corrent (PID $BRIDGE_PID)"
    sublog "cmd: $BRIDGE_CMD"
else
    fail "Bridge NO corre"
    if [ $FIX_MODE -eq 1 ]; then
        if fix_arrenca_bridge; then
            BRIDGE_PID=$(pgrep -f "agent_http_bridge.py" | head -1)
        fi
    else
        MANUAL_FIXES+=("Arrencar bridge: cd $AGENT_DIR && python3 agent_http_bridge.py &")
    fi
fi

# 2. Bridge respon?
header "2. /health del bridge"
BRIDGE_URL="http://${BRIDGE_HOST}:${BRIDGE_PORT}"
DETECTED_TOKEN=$(detect_bridge_token)
TOKEN_PERM_DENIED=0
if [ "$DETECTED_TOKEN" = "__PERM_DENIED__" ]; then
    TOKEN_PERM_DENIED=1
    DETECTED_TOKEN=""
fi
BRIDGE_TOKEN=""

RESP=$(test_bridge_health "$BRIDGE_URL/health" "")

if echo "$RESP" | grep -q '"status": "ok"'; then
    pass "Bridge respon /health (sense token)"
elif echo "$RESP" | grep -qi "unauthorized\|401\|auth"; then
    warn "Bridge requereix token"
    if [ -n "$DETECTED_TOKEN" ]; then
        RESP2=$(test_bridge_health "$BRIDGE_URL/health" "$DETECTED_TOKEN")
        if echo "$RESP2" | grep -q '"status": "ok"'; then
            pass "Bridge respon amb token detectat"
            BRIDGE_TOKEN="$DETECTED_TOKEN"
            RESP="$RESP2"
        else
            fail "Token detectat no funciona"
        fi
    else
        if [ $TOKEN_PERM_DENIED -eq 1 ]; then
            sublog "ℹ️  Token no llegible des d'aquest shell (normal). Pas 5 validarà la connectivitat real."
        else
            warn "No es pot detectar el token"
        fi
    fi
elif [ -z "$RESP" ] && [ -n "$BRIDGE_PID" ]; then
    fail "Bridge corre però no respon"
    if [ $FIX_MODE -eq 1 ]; then fix_reinicia_bridge; fi
elif [ -z "$BRIDGE_PID" ]; then
    sublog "(salta — bridge no corre)"
fi

# public_url indicator
if [ -n "$RESP" ] && echo "$RESP" | grep -q '"status": "ok"'; then
    PUBLIC_URL=$(echo "$RESP" | grep -o '"public_url"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/')
    if [ -n "$PUBLIC_URL" ]; then
        pass "public_url: $PUBLIC_URL"
    else
        warn "public_url absent (bridge antic, pre-Fix #2)"
    fi
fi

# 3. Ollama
header "3. Ollama"
OLLAMA_RESP=$(curl -s --max-time 3 "http://${OLLAMA_HOST}:${OLLAMA_PORT}/api/tags" 2>/dev/null)
if [ -z "$OLLAMA_RESP" ]; then
    fail "Ollama NO respon"
    if [ $FIX_MODE -eq 1 ]; then
        fix_arrenca_ollama
        OLLAMA_RESP=$(curl -s --max-time 3 "http://${OLLAMA_HOST}:${OLLAMA_PORT}/api/tags" 2>/dev/null)
    else
        MANUAL_FIXES+=("sudo systemctl restart ollama")
    fi
fi

if [ -n "$OLLAMA_RESP" ]; then
    pass "Ollama respon"
    if [ -n "${EXPECTED_MODEL:-}" ]; then
        # Override explícit via env var (per a models nous no a la llista)
        if echo "$OLLAMA_RESP" | grep -q "$EXPECTED_MODEL"; then
            pass "Model $EXPECTED_MODEL carregat (override)"
        else
            warn "Model $EXPECTED_MODEL NO present"
            if [ $FIX_MODE -eq 1 ] && command -v ollama >/dev/null; then fix_pull_model; fi
            MANUAL_FIXES+=("ollama pull $EXPECTED_MODEL")
        fi
    else
        FOUND_COMPATIBLE=""
        for _m in "${COMPATIBLE_MODELS[@]}"; do
            if echo "$OLLAMA_RESP" | grep -q "$_m"; then
                FOUND_COMPATIBLE="$_m"
                break
            fi
        done
        if [ -n "$FOUND_COMPATIBLE" ]; then
            pass "Model compatible present: $FOUND_COMPATIBLE"
        else
            FOUND_INCOMPAT=""
            for _m in "${INCOMPATIBLE_MODELS[@]}"; do
                if echo "$OLLAMA_RESP" | grep -q "$_m"; then
                    FOUND_INCOMPAT="$_m"
                    break
                fi
            done
            if [ -n "$FOUND_INCOMPAT" ]; then
                warn "Model $_m present però NO compatible amb tool calling" \
                    "Substitueix per: ollama pull $RECOMMENDED_MODEL"
            else
                warn "Cap model compatible per a Bartolo" \
                    "Recomanació: ollama pull $RECOMMENDED_MODEL"
            fi
            if [ $FIX_MODE -eq 1 ] && command -v ollama >/dev/null; then
                fix_pull_model
            else
                MANUAL_FIXES+=("ollama pull $RECOMMENDED_MODEL")
            fi
        fi
    fi
fi

# 4. OpenWebUI
header "4. OpenWebUI"
OPENWEBUI_OK=0
if ! command -v docker >/dev/null 2>&1; then
    warn "Docker no instal·lat"
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${OPENWEBUI_CONTAINER}$"; then
    pass "Container $OPENWEBUI_CONTAINER corrent"
    OPENWEBUI_OK=1
elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${OPENWEBUI_CONTAINER}$"; then
    fail "Container existeix però aturat"
    if [ $FIX_MODE -eq 1 ]; then
        if fix_arrenca_openwebui; then OPENWEBUI_OK=1; fi
    else
        MANUAL_FIXES+=("docker start $OPENWEBUI_CONTAINER")
    fi
else
    warn "Container $OPENWEBUI_CONTAINER no trobat"
fi

# 5. OpenWebUI veu el bridge?
header "5. Connectivitat OpenWebUI → Bridge"
if [ "$OPENWEBUI_OK" -eq 1 ]; then
    INTERNAL=$(docker exec "$OPENWEBUI_CONTAINER" \
        curl -s --max-time 3 "http://host.docker.internal:${BRIDGE_PORT}/health" 2>/dev/null || echo "")

    if echo "$INTERNAL" | grep -q '"status": "ok"'; then
        pass "OpenWebUI veu el bridge sense token"
    elif echo "$INTERNAL" | grep -qi "unauthorized\|401\|auth"; then
        CONTAINER_TOKEN=$(docker exec "$OPENWEBUI_CONTAINER" env 2>/dev/null | \
            grep "^BRIDGE_AUTH_TOKEN=" | cut -d= -f2- || echo "")

        if [ -n "$CONTAINER_TOKEN" ]; then
            INTERNAL2=$(docker exec "$OPENWEBUI_CONTAINER" \
                curl -s --max-time 3 -H "X-Auth-Token: $CONTAINER_TOKEN" \
                "http://host.docker.internal:${BRIDGE_PORT}/health" 2>/dev/null || echo "")
            if echo "$INTERNAL2" | grep -q '"status": "ok"'; then
                pass "OpenWebUI veu el bridge amb token"
            else
                fail "Token al container NO coincideix amb el del bridge"
                if [ $FIX_MODE -eq 1 ]; then
                    log "${YELLOW}   Solució més fàcil: rearrencar bridge sense token${NC}"
                    fix_reinicia_bridge
                fi
            fi
        else
            fail "Bridge requereix token, container NO en té"
            sublog "Tool fallarà sempre amb 401"
            if [ $FIX_MODE -eq 1 ]; then
                log "${YELLOW}   Opcions:${NC}"
                log "${YELLOW}   A) Rearrencar bridge sense token (ràpid, dev-friendly)${NC}"
                log "${YELLOW}   B) Recrear container OpenWebUI (manual, més segur)${NC}"
                if ask_confirm "Apliquem A: bridge sense token"; then
                    fix_reinicia_bridge
                else
                    MANUAL_FIXES+=("Recrear container amb -e BRIDGE_AUTH_TOKEN=<token-bridge>")
                fi
            else
                MANUAL_FIXES+=("Reinicia bridge sense token, O recrea container amb -e BRIDGE_AUTH_TOKEN")
            fi
        fi
    else
        fail "OpenWebUI no pot connectar al bridge"
        sublog "host.docker.internal:${BRIDGE_PORT} inaccessible"
        MANUAL_FIXES+=("Recrea container amb --add-host=host.docker.internal:host-gateway")
    fi
else
    sublog "(salta — OpenWebUI no operatiu)"
fi

# 6. OpenWebUI veu Ollama?
header "6. Connectivitat OpenWebUI → Ollama"
if [ "$OPENWEBUI_OK" -eq 1 ]; then
    OLLAMA_INT=$(docker exec "$OPENWEBUI_CONTAINER" \
        curl -s --max-time 3 "http://host.docker.internal:${OLLAMA_PORT}/api/tags" 2>/dev/null || echo "")
    if echo "$OLLAMA_INT" | grep -q "models"; then
        pass "OpenWebUI veu Ollama"
    else
        fail "OpenWebUI no pot connectar a Ollama"
        MANUAL_FIXES+=("Comprova OLLAMA_BASE_URL al container")
    fi
else
    sublog "(salta — OpenWebUI no operatiu)"
fi

# 7. Tool (manual)
header "7. Tool d'OpenWebUI (verificació manual)"
OWU_PORT=$(docker port "$OPENWEBUI_CONTAINER" 8080 2>/dev/null | head -1 | cut -d: -f2)
OWU_PORT="${OWU_PORT:-3000}"
log "  ${GRAY}A http://localhost:${OWU_PORT}:${NC}"
log "  ${GRAY}1. Settings → Workspace → Tools → Universal Repo Agent${NC}"
log "  ${GRAY}   Versió esperada: ${BOLD}$EXPECTED_TOOL_VERSION${NC}"
log "  ${GRAY}2. Settings → Admin → Models → Qwen → Function Calling: ON${NC}"
log "  ${GRAY}3. Al xat: tool 'Universal Repo Agent' activada (botó +)${NC}"

# Veredicte
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
TOTAL=$((CHECKS_PASS + CHECKS_WARN + CHECKS_FAIL))
echo -e "${BOLD}Resum:${NC} ${GREEN}$CHECKS_PASS ✅${NC}  ${YELLOW}$CHECKS_WARN ⚠️${NC}  ${RED}$CHECKS_FAIL ❌${NC}  (de $TOTAL)"

if [ $FIX_MODE -eq 1 ]; then
    echo -e "${CYAN}Fixes:${NC}  ${GREEN}$FIXES_APPLIED aplicats${NC}  ${RED}$FIXES_FAILED fallits${NC}"
fi
echo ""

if [ $CHECKS_FAIL -eq 0 ] && [ $CHECKS_WARN -eq 0 ]; then
    echo -e "${GREEN}${BOLD}🎉 Tot perfecte. Bartolo hauria de funcionar.${NC}"
    EXIT_CODE=0
elif [ $CHECKS_FAIL -eq 0 ]; then
    echo -e "${YELLOW}${BOLD}✓ Bartolo funcionarà amb avisos menors.${NC}"
    EXIT_CODE=0
else
    echo -e "${RED}${BOLD}✗ Bartolo NO funcionarà fins arreglar els problemes.${NC}"
    EXIT_CODE=1
fi

if [ ${#MANUAL_FIXES[@]} -gt 0 ]; then
    echo ""
    echo -e "${BOLD}🔧 Solucions manuals pendents:${NC}"
    for fix in "${MANUAL_FIXES[@]}"; do
        echo -e "   ${GRAY}\$${NC} $fix"
    done
fi

if [ $FIX_MODE -eq 0 ] && [ $CHECKS_FAIL -gt 0 ]; then
    echo ""
    echo -e "${CYAN}💡 Prova: ${BOLD}./bartolo-doctor.sh --fix${NC}${CYAN} per intentar arreglar automàticament${NC}"
fi

echo ""
exit $EXIT_CODE
