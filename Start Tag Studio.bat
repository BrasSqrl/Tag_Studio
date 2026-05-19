@echo off
setlocal
cd /d "%~dp0"
title Tag Studio

echo.
echo Starting Tag Studio
echo -------------------

where python >nul 2>nul
if errorlevel 1 (
    echo Python is required before Tag Studio can start.
    echo Please install Python 3.11 or newer, then double-click this file again.
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo Tag Studio cannot find its setup file.
    echo Make sure this launcher is in the Tag Studio folder.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo First-time setup. This may take a few minutes.
    python -m venv .venv
    if errorlevel 1 (
        echo Tag Studio could not create its local Python environment.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo Installing Tag Studio components. This may take a few minutes.
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 (
        echo Tag Studio could not update its installer.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Tag Studio could not install its required components.
        pause
        exit /b 1
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try {$c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8501); $c.Close(); exit 0} catch {exit 1}" >nul 2>nul
if not errorlevel 1 (
    echo Tag Studio already appears to be running. Opening it now.
    start "" "http://localhost:8501"
    exit /b 0
)

echo Opening Tag Studio in your browser.
start "" "http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run tag_studio\app.py --server.port 8501
if errorlevel 1 (
    echo.
    echo Tag Studio could not start.
    echo If another app is using port 8501, close it and try again.
    pause
    exit /b 1
)
