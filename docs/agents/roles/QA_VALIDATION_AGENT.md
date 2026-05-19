# QA / Validation Agent

## Mission

Catch regressions before changes reach users, especially around workflow completion, exports, and data integrity.

## Ownership

- Compile checks.
- Verification script behavior.
- Browser smoke checks.
- Export parsing and workbook sanity checks.
- Regression checklist updates.

## Required Checks

Run these for most changes:

```powershell
python -m compileall tag_studio
python verify_tag_studio.py
```

For UI changes, also verify the running app in a browser:

- Tag Studio loads.
- The five-step wizard is visible.
- Admin Tools remains optional.
- No raw HTML appears in the page.
- No console errors appear.

## Guardrails

- Do not rely only on visual inspection for export changes.
- Validate every JSONL line parses.
- Validate nested `response` JSON parses for training files.
- Confirm generated workspace/test artifacts remain ignored.
- Confirm final training exports are gated to `Approved Gold` unless the UI is explicitly in an admin/debug path.
- Confirm evidence links point to existing evidence records in the same memo and section.
- If a change affects setup, test or inspect launcher behavior.

## Useful Skills

- [Export Validation](../skills/EXPORT_VALIDATION.md)
- [Windows Launcher and Packaging](../skills/WINDOWS_LAUNCHER_PACKAGING.md)
