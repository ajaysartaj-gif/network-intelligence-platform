#!/bin/bash
# ════════════════════════════════════════════════════════════
# NetBrain AI — Universal Startup Script
# Works on: macOS · Linux · GitHub Codespaces · Cursor
# ════════════════════════════════════════════════════════════

CYAN='\033[0;36m'; GREEN='\033[0;32m'
YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'

PORT=8501

echo ""
echo -e "${CYAN}${BOLD}  NetBrain AI — AI-Native Network OS${NC}"
echo "  ════════════════════════════════════"
echo ""

# ── Detect environment ────────────────────────────────────────────────────────
IN_CODESPACE=false
IN_CURSOR=false
[ -n "$CODESPACE_NAME" ] && IN_CODESPACE=true
[ -n "$CURSOR_TRACE_ID" ] || [ -n "$VSCODE_GIT_IPC_HANDLE" ] && IN_CURSOR=true

if $IN_CODESPACE; then
    echo -e "${CYAN}[ENV]${NC} GitHub Codespaces detected"
elif $IN_CURSOR; then
    echo -e "${CYAN}[ENV]${NC} Cursor / VS Code terminal detected"
else
    echo -e "${CYAN}[ENV]${NC} Local machine"
fi

# ── Find repo root ────────────────────────────────────────────────────────────
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_PATH="$SCRIPT_DIR"

if [ ! -f "$REPO_PATH/app.py" ]; then
    for dir in \
        "$HOME/network-intelligence-platform" \
        "$HOME/Documents/network-intelligence-platform" \
        "$HOME/Desktop/network-intelligence-platform" \
        "/workspaces/network-intelligence-platform"; do
        if [ -f "$dir/app.py" ]; then
            REPO_PATH="$dir"; break
        fi
    done
fi

if [ ! -f "$REPO_PATH/app.py" ]; then
    echo -e "${RED}[ERROR]${NC} Cannot find app.py. Put this script inside your repo folder."
    exit 1
fi

cd "$REPO_PATH"
echo -e "${GREEN}[OK]${NC} Repo: $REPO_PATH"

# ── Find Python ───────────────────────────────────────────────────────────────
PYTHON_CMD=""
for cmd in python3 python python3.12 python3.11 python3.10; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null)
        if [ "$VER" = "True" ]; then
            PYTHON_CMD="$cmd"; break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}[ERROR]${NC} Python 3.10+ not found."
    echo "  macOS  → brew install python  OR  https://python.org/downloads"
    echo "  Linux  → sudo apt install python3.11"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} $($PYTHON_CMD --version)"

# ── Virtual environment (skip in Codespaces — already has global pip) ─────────
if ! $IN_CODESPACE; then
    VENV_DIR="$REPO_PATH/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[INFO] Creating virtual environment..."
        $PYTHON_CMD -m venv "$VENV_DIR"
    fi
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}[OK]${NC} Virtual environment active."
fi

# ── Install dependencies ──────────────────────────────────────────────────────
echo "[INFO] Checking dependencies..."
pip install --upgrade pip --quiet 2>/dev/null
pip install -r requirements.txt --quiet
echo -e "${GREEN}[OK]${NC} Dependencies ready."

# ── Create .env if missing ────────────────────────────────────────────────────
if [ ! -f "$REPO_PATH/.env" ]; then
    echo -e "${YELLOW}[INFO]${NC} Creating .env template..."
    cat > "$REPO_PATH/.env" << 'ENV'
# Get your FREE key from: https://console.groq.com
GROQ_API_KEY=your_groq_api_key_here

STREAMLIT_PORT=8501
PINGGY_FALLBACK_URL=

GITHUB_TOKEN=
GITHUB_LOG_REPO=your-username/gns3-router-logs

ROUTER_DEFAULT_USERNAME=admin
ROUTER_DEFAULT_PASSWORD=
ROUTER_ENABLE_SECRET=
ENV
    echo -e "${YELLOW}[ACTION NEEDED]${NC} Edit .env and add your GROQ_API_KEY"
    # Open in editor
    command -v open &>/dev/null && open -t "$REPO_PATH/.env"   # macOS
    command -v nano &>/dev/null && echo "  Run: nano $REPO_PATH/.env"
    read -p "  Press Enter after saving your API key..."
fi

# ── Get LAN IP ────────────────────────────────────────────────────────────────
LAN_IP=""
if command -v ipconfig &>/dev/null; then
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
fi
if [ -z "$LAN_IP" ]; then
    LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
[ -z "$LAN_IP" ] && LAN_IP="<your-local-ip>"

# ── Build access URLs ─────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "  ${BOLD}NetBrain AI is starting!${NC}"
echo ""

if $IN_CODESPACE; then
    CODESPACE_URL="https://${CODESPACE_NAME}-${PORT}.app.github.dev"
    echo -e "  ${CYAN}Codespaces URL → ${CODESPACE_URL}${NC}"
    echo "  (Also check the PORTS tab in VS Code / Codespaces)"
else
    echo -e "  ${CYAN}Localhost  →  http://localhost:${PORT}${NC}"
    echo -e "  ${CYAN}LAN URL    →  http://${LAN_IP}:${PORT}${NC}"
    echo "  (LAN URL works from any device on your Wi-Fi)"
    # Auto-open browser
    (sleep 4 && {
        command -v open &>/dev/null && open "http://localhost:$PORT"
        command -v xdg-open &>/dev/null && xdg-open "http://localhost:$PORT"
    }) &
fi

echo ""
echo "  Press Ctrl+C to stop."
echo "════════════════════════════════════════════════════════════"
echo ""

# ── Launch Streamlit ──────────────────────────────────────────────────────────
streamlit run app.py \
    --server.port "$PORT" \
    --server.address "0.0.0.0" \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --browser.gatherUsageStats false

echo ""
echo "[INFO] NetBrain AI stopped."
