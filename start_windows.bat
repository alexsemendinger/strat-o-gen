@echo off
REM Strat-O-Matic Card Maker - Windows launcher
REM Starts the server; the app opens your browser automatically.

setlocal
cd /d "%~dp0"

echo ========================================
echo   Strat-O-Matic Card Maker
echo ========================================
echo.

REM Find Python (try the py launcher first, then python)
set PY=py -3
%PY% --version >nul 2>&1
if errorlevel 1 (
    set PY=python
    %PY% --version >nul 2>&1
)
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo IMPORTANT: check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Install Flask on first run (the only dependency)
%PY% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo First-time setup: installing Flask...
    %PY% -m pip install --user flask
)

echo Starting... the app will open in your browser shortly.
echo If it doesn't, go to:  http://localhost:5001
echo.
echo ----------------------------------------
echo   Keep this window open while using
echo   the app. Close it to stop.
echo ----------------------------------------
echo.

%PY% app.py

echo.
echo Server stopped.
pause
