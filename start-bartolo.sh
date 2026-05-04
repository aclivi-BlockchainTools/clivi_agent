#!/usr/bin/env bash
# start-bartolo.sh — Arrenca tot el sistema Bartolo
#
# Ordre: Ollama → bridge (systemd) → open-webui → bartolo-doctor
#
# Ús:
#   ./start-bartolo.sh          # arrenca tot i comprova
#   ./start-bartolo.sh --check  # només comprova (no arrenca res)

set -uo pipefail

# ── Config (overridable via env) ──────────────────────────────────────────────
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
BRIDGE_PORT="${BRIDGE_PORT:-9090}"
OPENWEBUI_CONTAINER="${OPENWEBUI_CONTAINER:-open-webui}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
BOLD="\033[1m"
NC="\033[0m"

ok()   { echo -e "  ${GREEN}✔${NC}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "  ${RED}✘${NC}  $*"; }
info() { echo -e "  ${CYAN}→${NC}  $*"; }
header() { echo -e "\n${BOLD}$*${NC}"; }

ERRORS=0

# ── 1. Ollama ─────────────────────────────────────────────────────────────────
header "1. Ollama"
if curl -s --max-time 3 "http://localhost:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; then
    ok "Ollama ja corre al port ${OLLAMA_PORT}"
else
    if [[ $CHECK_ONLY -eq 1 ]]; then
        fail "Ollama NO respon al port ${OLLAMA_PORT}"
        ERRORS=$((ERRORS + 1))
    else
        info "Ollama no respon — intentant arrancar..."
        if sudo systemctl start ollama 2>/dev/null; then
            # Espera fins a 15 s
            for i in $(seq 1 15); do
                sleep 1
                if curl -s --max-time 2 "http://localhost:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; then
                    ok "Ollama operatiu (${i}s)"
                    break
                fi
                [[ $i -eq 15 ]] && { fail "Ollama no ha respost en 15s"; ERRORS=$((ERRORS + 1)); }
            done
        else
            fail "sudo systemctl start ollama ha fallat — arrenca-ho manualment"
            ERRORS=$((ERRORS + 1))
        fi
    fi
fi

# ── 2. Bridge HTTP (systemd user service) ─────────────────────────────────────
header "2. Bridge HTTP (agent-bridge)"
BRIDGE_ACTIVE=$(systemctl --user is-active agent-bridge 2>/dev/null || echo "unknown")
if [[ "$BRIDGE_ACTIVE" == "active" ]]; then
    ok "agent-bridge.service ja corre"
else
    if [[ $CHECK_ONLY -eq 1 ]]; then
        fail "agent-bridge.service no està actiu (estat: ${BRIDGE_ACTIVE})"
        ERRORS=$((ERRORS + 1))
    else
        info "Arrancat agent-bridge.service..."
        if systemctl --user start agent-bridge 2>/dev/null; then
            sleep 2
            if curl -s --max-time 3 "http://localhost:${BRIDGE_PORT}/health" >/dev/null 2>&1; then
                ok "Bridge operatiu al port ${BRIDGE_PORT}"
            else
                warn "Servei iniciat però /health no respon encara (pot tardar uns segons)"
            fi
        else
            fail "systemctl --user start agent-bridge ha fallat"
            info "Comprova: journalctl --user -u agent-bridge -n 20"
            ERRORS=$((ERRORS + 1))
        fi
    fi
fi

# ── 3. OpenWebUI Docker container ─────────────────────────────────────────────
header "3. OpenWebUI (Docker)"
if ! command -v docker >/dev/null 2>&1; then
    warn "Docker no trobat — salta comprovació OpenWebUI"
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${OPENWEBUI_CONTAINER}$"; then
    ok "Container '${OPENWEBUI_CONTAINER}' ja corre"
elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${OPENWEBUI_CONTAINER}$"; then
    if [[ $CHECK_ONLY -eq 1 ]]; then
        fail "Container '${OPENWEBUI_CONTAINER}' existeix però està aturat"
        ERRORS=$((ERRORS + 1))
    else
        info "Arrancat container '${OPENWEBUI_CONTAINER}'..."
        if docker start "${OPENWEBUI_CONTAINER}" >/dev/null 2>&1; then
            ok "Container '${OPENWEBUI_CONTAINER}' arrencat"
        else
            fail "docker start ${OPENWEBUI_CONTAINER} ha fallat"
            ERRORS=$((ERRORS + 1))
        fi
    fi
else
    warn "Container '${OPENWEBUI_CONTAINER}' no trobat — potser cal crear-lo"
    info "Consulta OPENWEBUI_SETUP.md per als passos de creació"
fi

# ── 4. bartolo-doctor ─────────────────────────────────────────────────────────
header "4. Comprovació final (bartolo-doctor)"
DOCTOR="${SCRIPT_DIR}/bartolo-doctor.sh"
if [[ -x "$DOCTOR" ]]; then
    echo ""
    "$DOCTOR"
else
    warn "bartolo-doctor.sh no trobat o no executable a ${SCRIPT_DIR}"
fi

# ── Resum ─────────────────────────────────────────────────────────────────────
echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo -e "${BOLD}${GREEN}Bartolo operatiu.${NC}"
else
    echo -e "${BOLD}${RED}${ERRORS} problema(es) detectat(s) — revisa els missatges anteriors.${NC}"
    exit 1
fi
