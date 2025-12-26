@echo off
REM Strat-O-Matic Card Generator - Windows Launcher
REM This script starts the Flask server and opens the browser

setlocal EnableDelayedExpansion

REM Change to the script's directory (in case launched from elsewhere)
cd /d "%~dp0"

REM Configuration
set PORT=5001
set URL=http://localhost:%PORT%

echo ========================================
echo   Strat-O-Matic Card Generator
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.10 or later from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: During installation, check "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo Python found. Starting server...
echo.
echo The app will open in your browser at: %URL%
echo.
echo ----------------------------------------
echo   Keep this window open while using
echo   the app. Close it to stop the server.
echo ----------------------------------------
echo.

REM Start the browser after a short delay (give server time to start)
REM Using start /b to run in background
start "" cmd /c "timeout /t 2 /nobreak >nul && start %URL%"

REM Start the Flask server (this will block until Ctrl+C or window close)
python app.py

REM If we get here, the server stopped
echo.
echo Server stopped.
pause
