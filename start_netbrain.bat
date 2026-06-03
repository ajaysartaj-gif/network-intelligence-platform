@echo off
title NetBrain AI — Local Startup
color 0A
chcp 65001 >nul 2>&1

echo.
echo  NetBrain AI — AI-Native Network OS
echo  =====================================
echo.
echo  Starting local server...
echo.

:: ── Step 1: Find Python ───────────────────────────────────────────────────────
set PYTHON_CMD=
for %%p in (python python3 py) do (
    %%p --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=%%p
        goto :python_found
    )
)
echo [ERROR] Python not found.
echo.
echo Install Python 3.10+ from: https://python.org/downloads
echo Make sure to tick "Add Python to PATH" during install.
echo.
pause
exit /b 1
:python_found
for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [OK] %%v

:: ── Step 2: Find the repo folder ─────────────────────────────────────────────
:: Script placed inside the repo folder — use that as repo path
set REPO_PATH=%~dp0
:: Remove trailing backslash
if "%REPO_PATH:~-1%"=="\" set REPO_PATH=%REPO_PATH:~0,-1%

:: Verify app.py exists here
if not exist "%REPO_PATH%\app.py" (
    :: Try common locations
    if exist "%USERPROFILE%\network-intelligence-platform\app.py" (
        set REPO_PATH=%USERPROFILE%\network-intelligence-platform
    ) else if exist "%USERPROFILE%\Documents\network-intelligence-platform\app.py" (
        set REPO_PATH=%USERPROFILE%\Documents\network-intelligence-platform
    ) else if exist "%USERPROFILE%\Desktop\network-intelligence-platform\app.py" (
        set REPO_PATH=%USERPROFILE%\Desktop\network-intelligence-platform
    ) else (
        echo.
        echo [ERROR] Could not find app.py.
        echo.
        echo Please move start_netbrain.bat into your cloned repo folder.
        echo Expected: %USERPROFILE%\network-intelligence-platform
        echo.
        pause
        exit /b 1
    )
)
cd /d "%REPO_PATH%"
echo [OK] Repo: %REPO_PATH%

:: ── Step 3: Create virtual environment ───────────────────────────────────────
if not exist ".venv\" (
    echo.
    echo [INFO] Creating virtual environment (.venv)...
    %PYTHON_CMD% -m venv .venv
    echo [OK] Virtual environment created.
)
call .venv\Scripts\activate.bat
echo [OK] Virtual environment active.

:: ── Step 4: Install dependencies ──────────────────────────────────────────────
echo.
echo [INFO] Checking dependencies...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [WARN] Some packages may have failed. Trying with --user...
    pip install -r requirements.txt --user --quiet
)
echo [OK] Dependencies ready.

:: ── Step 5: Create .env if missing ────────────────────────────────────────────
if not exist ".env" (
    echo.
    echo [INFO] Creating .env template...
    (
        echo # NetBrain AI - Local Environment
        echo # Get your key from: https://openrouter.ai/keys
        echo OPENROUTER_API_KEY=your_openrouter_key_here
        echo.
        echo STREAMLIT_PORT=8501
        echo PINGGY_FALLBACK_URL=
        echo.
        echo GITHUB_TOKEN=
        echo GITHUB_LOG_REPO=your-username/gns3-router-logs
        echo.
        echo ROUTER_DEFAULT_USERNAME=admin
        echo ROUTER_DEFAULT_PASSWORD=
        echo ROUTER_ENABLE_SECRET=
    ) > .env
    echo [ACTION NEEDED] Edit .env and add your OPENROUTER_API_KEY
    echo Opening .env in Notepad...
    notepad .env
    echo.
    echo Press Enter after you have saved your API key.
    pause
)

:: ── Step 6: Get LAN IP ────────────────────────────────────────────────────────
set LAN_IP=unknown
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4 Address"') do (
    set LAN_IP=%%a
    goto :ip_done
)
:ip_done
set LAN_IP=%LAN_IP: =%

:: ── Step 7: Open browser after delay ─────────────────────────────────────────
start "" cmd /c "timeout /t 4 >nul && start http://localhost:8501"

:: ── Step 8: Launch Streamlit ──────────────────────────────────────────────────
echo.
echo ════════════════════════════════════════════════════════════
echo   NetBrain AI is starting!
echo.
echo   Localhost  -^>  http://localhost:8501
echo   LAN URL    -^>  http://%LAN_IP%:8501
echo   (LAN URL works from any device on your Wi-Fi)
echo.
echo   Press Ctrl+C to stop.
echo ════════════════════════════════════════════════════════════
echo.

streamlit run app.py ^
    --server.address 0.0.0.0 ^
    --server.port 8501 ^
    --server.headless false ^
    --browser.gatherUsageStats false

echo.
echo [INFO] NetBrain AI stopped.
pause
