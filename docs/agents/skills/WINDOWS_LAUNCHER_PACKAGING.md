# Skill Brief: Windows Launcher and Packaging

Use this skill when changing launcher files, setup instructions, requirements, README, or GitHub packaging.

## Launcher Rules

- Keep one normal user launcher: `Start Tag Studio.bat`.
- The launcher should:
  - find Python,
  - create `.venv` if missing,
  - install requirements if Streamlit is unavailable,
  - open `http://localhost:8501`,
  - start Streamlit on port `8501`,
  - show friendly errors.

## Documentation Rules

- README should tell a nontechnical user to double-click the launcher and follow the five app steps.
- Keep command-line alternatives in secondary/admin docs only when useful.
- Do not reference deleted launchers.

## Git Hygiene

- Ignore `.venv/`, caches, local workspaces, source PDFs, and generated exports.
- Do not commit synthetic PDFs unless the user explicitly requests it.
- Verify only one `.bat` file exists unless the user asks for admin-specific scripts.

## Validation

```powershell
Get-ChildItem -File *.bat
rg "run_tag_studio|setup_tag_studio" -n .
python -m compileall tag_studio
```

