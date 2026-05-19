@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m streamlit run tag_studio\app.py
) else (
    echo WARNING: .venv was not found. Run setup_tag_studio.bat first for the recommended setup.
    python -m streamlit run tag_studio\app.py
)
