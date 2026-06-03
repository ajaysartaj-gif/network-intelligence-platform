#!/bin/bash
# ════════════════════════════════════════════════════════════
# NetBrain AI — macOS / Linux Startup Script
# ════════════════════════════════════════════════════════════

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}${BOLD}"
echo "  ███╗   ██╗███████╗████████╗██████╗ ██████╗  █████╗ ██╗███╗   ██╗"
echo "  ████╗  ██║██╔════╝╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║"
echo "  ██╔██╗ ██║█████╗     ██║   ██████╔╝██████╔╝███████║██║██╔██╗ ██║"
echo "  ██║╚██╗██║██╔══╝     ██║   ██╔══██╗██╔══██╗██╔══██║██║██║╚██╗██║"
echo "  ██║ ╚████║███████╗   ██║   ██████╔╝██║  ██║██║  ██║██║██║ ╚████║"
echo "  ╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝"
echo -e "${NC}"
echo -e "${BOLD}                    AI-Native Network OS${NC}"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Starting NetBrain AI locally..."
echo "════════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Find the repo folder ─────────────────────────────────────────────
# Script's own directory is assumed to be the repo root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_PATH="$SCRIPT_DIR"

# Fallback: check common clone locations
if [ ! -f "$REPO_PATH/app.py" ]; then
    CANDIDATES=(
        "$HOME/network-intelligence-platform"
        "$HOME/Documents/network-intelligence-platform"
        "$HOME/Desktop/network-intelligence-platform"
    )
    for dir in "${CANDIDATES[@]}"; do
        if [ -f "$dir/app.py" ]; then
            REPO_PATH="$dir"
            break
        fi
    done
fi

if [ ! -f "$REPO_PATH/app.py" ]; then
    echo -e "${RED}[ERROR] Could not find app.py in:${NC}"
    echo "  $REPO_PATH"
    echo ""
    echo "Please move this script into your cloned repo folder and try again."
    echo "Expected folder: ~/network-intelligence-platform"
    exit 1
fi

cd "$REPO_PATH"
echo -e "${GREEN}[OK]${NC} Repo folder: $REPO_PATH"

# ── Step 2: Check Python ──────────────────────────────────────────────────────
PYTHON_CMD=""
for cmd in python3 python python3.12 python3.11 python3.10; do
    if command -v "$cmd" &>/dev/null; then
        VERSION=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}[ERROR] Python 3.10+ not found.${NC}"
    echo ""
    echo "Install it:"
    echo "  macOS  → brew install python  (or https://python.org/downloads)"
    echo "  Linux  → sudo apt install python3.11"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} Python: $($PYTHON_CMD --version)"

# ── Step 3: Virtual environment ───────────────────────────────────────────────
VENV_DIR="$REPO_PATH/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "[INFO] Creating virtual environment (.venv)..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    echo -e "${GREEN}[OK]${NC} Virtual environment created."
fi

# Activate venv
source "$VENV_DIR/bin/activate"
echo -e "${GREEN}[OK]${NC} Virtual environment active."

# ── Step 4: Install/upgrade dependencies ─────────────────────────────────────
echo ""
echo "[INFO] Checking dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo -e "${GREEN}[OK]${NC} All dependencies ready."

# ── Step 5: Create .env if missing ───────────────────────────────────────────
if [ ! -f "$REPO_PATH/.env" ]; then
    echo ""
    echo -e "${YELLOW}[INFO] No .env file found. Creating template...${NC}"
    cat > "$REPO_PATH/.env" << 'ENV'
# NetBrain AI — Local Environment
# Get your key from: https://openrouter.ai/keys
OPENROUTER_API_KEY=your_openrouter_key_here

STREAMLIT_PORT=8501
PINGGY_FALLBACK_URL=

GITHUB_TOKEN=
GITHUB_LOG_REPO=your-username/gns3-router-logs

ROUTER_DEFAULT_USERNAME=admin
ROUTER_DEFAULT_PASSWORD=
ROUTER_ENABLE_SECRET=
ENV

    echo -e "${YELLOW}[ACTION NEEDED]${NC} .env file created at: $REPO_PATH/.env"
    echo ""
    echo "  Open it and add your OPENROUTER_API_KEY, then re-run this script."
    echo "  Opening in your default editor..."
    echo ""

    # Try to open in a text editor
    if command -v open &>/dev/null; then
        open -t "$REPO_PATH/.env"   # macOS
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$REPO_PATH/.env"  # Linux
    else
        echo "  → Edit manually: $REPO_PATH/.env"
    fi

    read -p "Press Enter after you have saved your API key..."
fi

# ── Step 6: Get LAN IP ────────────────────────────────────────────────────────
PORT=8501
if command -v ipconfig &>/dev/null; then
    # macOS (ipconfig getifaddr)
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
fi
if [ -z "$LAN_IP" ]; then
    # Linux / fallback
    LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
if [ -z "$LAN_IP" ]; then
    LAN_IP="<your-local-ip>"
fi

# ── Step 7: Open browser after a short delay ─────────────────────────────────
(sleep 3 && open "http://localhost:$PORT" 2>/dev/null || \
           xdg-open "http://localhost:$PORT" 2>/dev/null) &

# ── Step 8: Launch Streamlit ─────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "  ${BOLD}NetBrain AI is starting!${NC}"
echo ""
echo -e "  ${CYAN}Localhost  →  http://localhost:$PORT${NC}"
echo -e "  ${CYAN}LAN URL    →  http://$LAN_IP:$PORT${NC}"
echo "  (LAN URL works from any device on your Wi-Fi)"
echo ""
echo "  Press Ctrl+C to stop."
echo "════════════════════════════════════════════════════════════"
echo ""

streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$PORT" \
    --server.headless false \
    --browser.gatherUsageStats false

echo ""
echo "[INFO] NetBrain AI stopped."
