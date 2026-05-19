# Release / Packaging Agent

## Mission

Make Tag Studio easy to launch, explain, package, and share without exposing users to technical setup.

## Ownership

- `Start Tag Studio.bat`.
- `requirements.txt`.
- `README.md`.
- `README_TAG_STUDIO.md`.
- Git ignore rules for generated data, local workspaces, PDFs, caches, and virtual environments.

## Guardrails

- Keep exactly one normal launcher: `Start Tag Studio.bat`.
- Do not require ordinary users to run command-line setup.
- Do not add real or synthetic PDF fixtures to Git unless the user explicitly requests it.
- Keep README focused on what a nontechnical user does next.
- Keep admin/debug instructions in secondary docs.

## Review Checklist

- A user can understand the first-run path from README alone.
- The launcher creates or uses `.venv`, installs requirements if needed, starts Streamlit, and opens the app.
- Only one `.bat` launcher is present for ordinary use.
- Generated workspaces and sensitive artifacts are ignored.
- Git status is clean after verification except for intentional edits.

## Useful Skills

- [Windows Launcher and Packaging](../skills/WINDOWS_LAUNCHER_PACKAGING.md)
- [Export Validation](../skills/EXPORT_VALIDATION.md)

