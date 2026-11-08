@echo off
REM Strat-O-Matic Card Maker - Windows launcher.
REM Starts the app; it opens your browser by itself once it is ready.
REM Starting it again while it runs just opens the browser again.

setlocal
cd /d "%~dp0"
title Strat-O-Matic Card Maker

echo ========================================
echo   Strat-O-Matic Card Maker
echo ========================================
echo.

REM Find Python: the py launcher first, then python. One statement per
REM line, so each line sees the PY set by the line before it.
set "PY=py -3"
%PY% --version >nul 2>&1
if errorlevel 1 set "PY=python"
%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

REM Python 3.9 or newer is needed.
%PY% -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if errorlevel 1 goto oldpython

REM Install Flask on first run (the only dependency).
%PY% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo First-time setup: installing Flask...
    %PY% -m pip install --user flask
    echo.
)

echo Starting... your browser opens when the app is ready.
echo.
echo ----------------------------------------
echo   Keep this window open while using
echo   the app. Close it to stop.
echo ----------------------------------------
echo.

%PY% app.py

echo.
echo The card maker has stopped.
pause
exit /b 0

:nopython
echo ERROR: Python was not found.
echo.
echo Install Python 3.9 or newer from https://www.python.org/downloads/
echo (see WINDOWS_SETUP.md), then double-click this file again.
echo.
pause
exit /b 1

:oldpython
echo ERROR: this Python is too old. The card maker needs Python 3.9 or newer.
%PY% --version
echo.
echo Install a current Python from https://www.python.org/downloads/
echo.
pause
exit /b 1
