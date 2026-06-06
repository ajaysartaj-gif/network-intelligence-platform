@echo off
title NetBrain AI — Local Startup
chcp 65001 >nul 2>&1

echo.
echo  NetBrain AI — AI-Native Network OS
echo  =====================================
echo.

:: ── Find Python ───────────────────────────────────────────────────────────────
set PYTHON_CMD=
for %%p in (python3 python py) do (
    where %%p >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=%%p
        goto :python_found
    )
)
echo [ERROR] Python not found.
echo Install from: https://python.org/downloads
echo Tick "Add Python to PATH" during install.
pause & exit /b 1
:python_found
for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [OK] %%v

:: ── Find repo folder ──────────────────────────────────────────────────────────
:: Use script's own directory as repo path
set REPO_PATH=%~dp0
if "%REPO_PATH:~-1%"=="\" set REPO_PATH=%REPO_PATH:~0,-1%

if not exist "%REPO_PATH%\app.py" (
    for %%d in (
        "%USERPROFILE%\network-intelligence-platform"
        "%USERPROFILE%\Documents\network-intelligence-platform"
        "%USERPROFILE%\Desktop\network-intelligence-platform"
    ) do (
        if exist "%%~d\app.py" (
            set REPO_PATH=%%~d
            goto :repo_found
        )
    )
    echo [ERROR] Cannot find app.py. Put start_netbrain.bat inside your repo folder.
    pause & exit /b 1
)
:repo_found
cd /d "%REPO_PATH%"
echo [OK] Repo: %REPO_PATH%

:: ── Virtual environment ───────────────────────────────────────────────────────
if not exist ".venv\" (
    echo [INFO] Creating virtual environment...
    %PYTHON_CMD% -m venv .venv
)
call .venv\Scripts\activate.bat
echo [OK] Virtual environment active.

:: ── Install dependencies ──────────────────────────────────────────────────────
echo [INFO] Checking dependencies...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo [OK] Dependencies ready.

:: ── Create .env if missing ────────────────────────────────────────────────────
if not exist ".env" (
    echo [INFO] Creating .env template...
    (
        echo # Get your FREE key from: https://console.groq.com
        echo GROQ_API_KEY=your_groq_api_key_here
        echo.
        echo STREAMLIT_PORT=8501
        echo PINGGY_FALLBACK_URL=
        echo GITHUB_TOKEN=
        echo ROUTER_DEFAULT_USERNAME=admin
        echo ROUTER_DEFAULT_PASSWORD=
    ) > .env
    echo [ACTION NEEDED] Edit .env and add your GROQ_API_KEY
    notepad .env
    pause
)

:: ── Get LAN IP ────────────────────────────────────────────────────────────────
set LAN_IP=unknown
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4 Address"') do (
    set LAN_IP=%%a
    goto :ip_done
)
:ip_done
set LAN_IP=%LAN_IP: =%

:: ── Open browser after delay ──────────────────────────────────────────────────
start "" cmd /c "timeout /t 5 >nul && start http://localhost:8501"

:: ── Launch Streamlit ──────────────────────────────────────────────────────────
echo.
echo ════════════════════════════════════════════════
echo   NetBrain AI is starting!
echo.
echo   Localhost  -^>  http://localhost:8501
echo   LAN URL    -^>  http://%LAN_IP%:8501
echo.
echo   Press Ctrl+C to stop.
echo ════════════════════════════════════════════════
echo.

streamlit run app.py ^
    --server.port 8501 ^
    --server.address 0.0.0.0 ^
    --server.headless true ^
    --server.enableCORS false ^
    --server.enableXsrfProtection false ^
    --browser.gatherUsageStats false

echo.
echo [INFO] NetBrain AI stopped.
pause
