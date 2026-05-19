# Tag Studio Agent Framework

This repo is organized for coordinated AI-agent work on Tag Studio, a local-first credit memo tagging app for nontechnical credit professionals.

## Operating Principles

- Keep the normal user workflow simple: no command line, no raw JSON, no model jargon, no file-path decisions.
- Preserve credit-review intent: the app creates reviewed tagging data; it does not make binding credit decisions.
- Keep real bank/customer data out of Git. Use synthetic fixtures only.
- Keep technical controls under Admin Tools unless the user explicitly asks otherwise.
- Protect export compatibility: Review Workbook and Training File outputs must remain valid after changes.

## Primary Agent Breakout

- **UI/UX Agent**: Owns the Streamlit user journey, labels, layout, wizard behavior, accessibility, and nontechnical wording.
- **Backend Agent**: Owns PDF extraction, local workspace storage, sectioning, schemas, export generation, and data integrity.

## Additional Recommended Agents

- **Credit Domain Agent**: Owns credit memo taxonomy, section/tag meaning, underwriting language, and RCO-assistive boundaries.
- **QA / Validation Agent**: Owns test scenarios, export checks, browser smoke tests, and regression risk.
- **Release / Packaging Agent**: Owns Windows launchers, README clarity, dependency setup, and GitHub-ready packaging.

Use these additional agents when a change materially touches their ownership area. For narrow changes, one primary agent can own implementation while another performs review.

## When To Spawn Subagents

Spawn subagents when work can proceed in parallel or needs independent review:

- UI change plus backend/export impact: spawn UI/UX and Backend agents.
- Tag taxonomy or credit-language change: spawn Credit Domain agent.
- Any export, schema, extraction, or validation change: spawn QA / Validation agent for a read-only review.
- Launcher/setup/readme/deployment change: spawn Release / Packaging agent.

Do not spawn subagents for trivial copy edits or single-line fixes. Keep each subagent prompt bounded and assign clear file ownership for worker agents.

## Coordination Workflow

1. Read the relevant role doc under `docs/agents/roles/`.
2. If the task touches reusable practice, read the relevant skill brief under `docs/agents/skills/`.
3. Split work by ownership:
   - UI files: primarily `tag_studio/app.py`, README user-facing instructions.
   - Backend files: `tag_studio/extraction.py`, `storage.py`, `sectioning.py`, `models.py`, `exporters.py`, `defaults.py`.
   - Verification: `verify_tag_studio.py`, browser smoke tests, compile checks.
   - Packaging: `Start Tag Studio.bat`, `requirements.txt`, README files.
4. Validate before finalizing:
   - `python -m compileall tag_studio`
   - `python verify_tag_studio.py`
   - Browser smoke check for visible UI changes.
5. Summarize what changed, what was tested, and any remaining risk.

## Required Guardrails

- Do not commit local workspace data from `tag_studio_workspace/`.
- Do not add real PDFs, real borrower data, or real credit memos.
- Do not expose raw internal IDs/hashes in the normal user flow.
- Do not rename public export concepts casually; users should see Review Workbook, Training File, and Audit Package.
- Do not break existing JSONL shape without updating backend, QA, and release docs.

