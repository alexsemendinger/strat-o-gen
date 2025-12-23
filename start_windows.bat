@echo off
echo Strat-O-Matic Card Maker
echo ========================
cd /d "%~dp0"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed.
    echo Please install Python 3.10 or later from https://www.python.org/
    pause
    exit /b 1
)

REM Check if dependencies are installed
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
)

REM Start the server
echo Starting Strat-O-Matic Card Maker...
start /b python app.py

REM Wait for server to start
timeout /t 3 /nobreak >nul

REM Open browser
start http://localhost:5000

echo.
echo Strat-O-Matic Card Maker is running!
echo The application should open in your default browser.
echo.
echo To stop the server, close this window.
echo.
pause
