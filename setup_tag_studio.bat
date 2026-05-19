@echo off
setlocal
cd /d "%~dp0"

echo.
echo Tag Studio setup
echo ----------------

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    echo Install Python 3.11 or newer, then run this setup again.
    exit /b 1
)

if not exist "requirements.txt" (
    echo ERROR: requirements.txt was not found in this folder.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo Virtual environment already exists.
)

echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    exit /b 1
)

echo Installing requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install requirements.
    exit /b 1
)

echo.
echo Setup complete.
echo Run Tag Studio with:
echo   run_tag_studio.bat
echo.

