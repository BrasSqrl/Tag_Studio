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

".venv\Scripts\python.exe" -c "import importlib.util, sys; required=['streamlit','pandas','openpyxl','pydantic','filelock','fitz','pytesseract','PIL','numpy','cv2','pypdfium2','ocrmypdf','paddleocr']; missing=[name for name in required if importlib.util.find_spec(name) is None]; sys.exit(1 if missing else 0)" >nul 2>nul
if errorlevel 1 (
    echo Installing Tag Studio components. Document reading setup may take several minutes.
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

".venv\Scripts\python.exe" -c "from tag_studio.document_intelligence import dependency_status; import sys; status=dependency_status(); sys.exit(0 if status.get('tesseract') else 2)" >nul 2>nul
if errorlevel 2 (
    echo.
    echo Scanned-PDF setup notice:
    echo Local scanned-PDF reading support was not found on this computer.
    echo Digital PDFs can still be read. Scanned PDFs will need local OCR support installed, or the extracted text must be corrected manually.
    echo Technical note: the current local OCR engine is Tesseract, not AWS Textract.
    echo.
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
