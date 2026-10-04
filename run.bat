@echo off
title M.A.R.C / L.O.K.I AI Assistant Launcher
cd /d "%~dp0"
echo ===================================================
echo   Starting M.A.R.C Local AI Assistant (v1.0)
echo ===================================================

if exist ".venv\Scripts\python.exe" (
    echo [INFO] Activating virtual environment...
    ".venv\Scripts\python.exe" loki_app.py
) else (
    echo [INFO] Running with system Python...
    python loki_app.py
)

pause
