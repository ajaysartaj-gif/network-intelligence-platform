@echo off
REM ═══════════════════════════════════════════════════════════════
REM NetBrain AI — Startup Script (Windows)
REM ═══════════════════════════════════════════════════════════════

echo ╔══════════════════════════════════════╗
echo ║       NetBrain AI — Starting         ║
echo ╚══════════════════════════════════════╝

REM Check .env exists
if not exist ".env" (
    echo [SETUP] Creating .env from template...
    (
        echo # Get your FREE Groq key from: https://console.groq.com
        echo GROQ_API_KEY=your_groq_api_key_here
        echo GNS3_SSH_USER=admin
        echo GNS3_SSH_PASS=admin
        echo GNS3_SSH_SECRET=admin
        echo GNS3_DEVICE_TYPE=cisco_ios
        echo GNS3_TUNNEL_URL=
        echo PINGGY_FALLBACK_URL=
        echo STREAMLIT_PORT=8501
    ) > .env
    echo [ACTION NEEDED] Edit .env and add your GROQ_API_KEY
    echo Get your FREE key from: https://console.groq.com
)

REM Install dependencies
echo [INFO] Installing dependencies...
pip install -r requirements.txt -q

REM Start Streamlit
echo [INFO] Starting NetBrain AI...
python -m streamlit run app.py --server.port 8501
