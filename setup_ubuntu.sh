#!/usr/bin/env bash
# =============================================================================
# setup_ubuntu.sh
# Prepara una màquina Ubuntu (20.04 / 22.04 / 24.04) per executar
# universal_repo_agent_v5.py amb Ollama + qwen2.5-coder:14b.
#
# Instal·la:
#   - Paquets de sistema (git, build-essential, curl, unzip, ...)
#   - Python 3 + venv + pip + dependències Python (requests)
#   - Node.js 20 LTS + Yarn (via corepack)
#   - Docker Engine + Docker Compose plugin (per BDs automàtiques)
#   - Ollama + model qwen2.5-coder:14b
#   - Altres llenguatges opcionals (Go, Rust, Ruby, PHP, Java) si s'activa
#
# Ús:
#   chmod +x setup_ubuntu.sh
#   ./setup_ubuntu.sh                 # mínim (Python, Node, Docker, Ollama)
#   ./setup_ubuntu.sh --full          # + Go, Rust, Ruby, PHP, Java
#   ./setup_ubuntu.sh --no-ollama     # salta instal·lació d'Ollama
#   ./setup_ubuntu.sh --no-docker     # salta Docker
# =============================================================================

set -euo pipefail

FULL=0
SKIP_OLLAMA=0
SKIP_DOCKER=0
MODEL="qwen2.5-coder:14b"

for arg in "$@"; do
    case "$arg" in
        --full)        FULL=1 ;;
        --no-ollama)   SKIP_OLLAMA=1 ;;
        --no-docker)   SKIP_DOCKER=1 ;;
        --model=*)     MODEL="${arg#*=}" ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Argument desconegut: $arg"; exit 1 ;;
    esac
done

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; BLUE="\033[0;34m"; NC="\033[0m"
log()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*" >&2; }

if [[ $EUID -eq 0 ]]; then
    err "No executis aquest script com a root directament. Fes-ho com el teu usuari; usarà sudo on calgui."
    exit 1
fi

if ! command -v sudo >/dev/null; then
    err "Cal 'sudo' instal·lat."
    exit 1
fi

log "Actualitzant índex d'apt..."
sudo apt-get update -y

log "Instal·lant paquets base..."
sudo apt-get install -y \
    git curl wget unzip zip tar ca-certificates gnupg lsb-release \
    build-essential pkg-config \
    python3 python3-venv python3-pip python3-dev \
    jq net-tools procps lsof

ok "Paquets base instal·lats."

# -----------------------------------------------------------------------------
# Dependències Python de l'agent
# -----------------------------------------------------------------------------
log "Instal·lant dependències Python de l'agent (requests)..."
# Ubuntu 24+ aplica PEP 668 i bloqueja pip global. Provem per ordre:
#   1. apt (via paquet de distribució)    → ideal en Ubuntu 24
#   2. pip --user --break-system-packages → fallback
#   3. pip --user                         → Ubuntu 22 i anteriors
if ! python3 -c "import requests" >/dev/null 2>&1; then
    if sudo apt-get install -y python3-requests 2>/dev/null; then
        ok "python3-requests instal·lat via apt."
    elif python3 -m pip install --user --break-system-packages requests >/dev/null 2>&1; then
        ok "requests instal·lat via pip (--break-system-packages)."
    elif python3 -m pip install --user requests >/dev/null 2>&1; then
        ok "requests instal·lat via pip --user."
    else
        warn "No s'ha pogut instal·lar 'requests'. Instal·la'l manualment:"
        warn "  sudo apt install python3-requests"
    fi
else
    ok "'requests' ja disponible."
fi
ok "Dependències Python OK."

# -----------------------------------------------------------------------------
# Node.js 20 LTS + Yarn (via corepack)
# -----------------------------------------------------------------------------
if ! command -v node >/dev/null || [[ "$(node -v 2>/dev/null | sed 's/v//; s/\..*//')" -lt 18 ]]; then
    log "Instal·lant Node.js 20 LTS via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
else
    ok "Node.js $(node -v) ja instal·lat."
fi

log "Activant corepack + Yarn..."
sudo corepack enable || true
sudo corepack prepare yarn@stable --activate || true
ok "Node: $(node -v) · npm: $(npm -v) · yarn: $(yarn -v 2>/dev/null || echo 'no')"

# -----------------------------------------------------------------------------
# Docker
# -----------------------------------------------------------------------------
if [[ $SKIP_DOCKER -eq 0 ]]; then
    if ! command -v docker >/dev/null; then
        log "Instal·lant Docker Engine..."
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update -y
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        sudo groupadd -f docker
        sudo usermod -aG docker "$USER"
        warn "S'ha afegit $USER al grup 'docker'. Tanca i reobre sessió (o 'newgrp docker') perquè funcioni sense sudo."
    else
        ok "Docker ja instal·lat ($(docker --version))."
    fi
else
    warn "Docker omès (--no-docker)."
fi

# -----------------------------------------------------------------------------
# Ollama + model
# -----------------------------------------------------------------------------
if [[ $SKIP_OLLAMA -eq 0 ]]; then
    if ! command -v ollama >/dev/null; then
        log "Instal·lant Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
    else
        ok "Ollama ja instal·lat ($(ollama --version | head -n1))."
    fi

    log "Comprovant que el servei Ollama està en marxa..."
    if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        if systemctl list-unit-files | grep -q '^ollama.service'; then
            sudo systemctl enable --now ollama || true
            sleep 2
        else
            warn "No s'ha pogut detectar el servei systemd d'Ollama. Engega'l manualment amb: 'ollama serve &'"
        fi
    fi

    log "Baixant model $MODEL (pot trigar uns minuts, ~8-9 GB)..."
    ollama pull "$MODEL"
    ok "Model $MODEL disponible."
else
    warn "Ollama omès (--no-ollama)."
fi

# -----------------------------------------------------------------------------
# Extras opcionals (--full)
# -----------------------------------------------------------------------------
if [[ $FULL -eq 1 ]]; then
    log "Instal·lant extres (Go, Ruby, PHP, Java, Maven)..."
    sudo apt-get install -y golang-go ruby ruby-dev php php-cli composer default-jdk maven
    if ! command -v cargo >/dev/null; then
        log "Instal·lant Rust (via rustup)..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
        # shellcheck disable=SC1090
        source "$HOME/.cargo/env" || true
    fi
    ok "Extres instal·lats."
fi

echo
ok "============================================================"
ok "  Setup completat."
ok "============================================================"
echo
echo "  Següents passos:"
echo "    1) (Si has instal·lat Docker) tanca sessió i torna-la a obrir, o executa: newgrp docker"
echo "    2) Comprova Ollama:        curl http://localhost:11434/api/tags"
echo "    3) Comprova model:         ollama list | grep qwen2.5-coder"
echo "    4) Executa l'agent:"
echo "       python3 universal_repo_agent_v5.py --input https://github.com/USER/REPO.git --execute"
echo
