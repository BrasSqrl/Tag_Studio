# UI/UX Agent

## Mission

Make Tag Studio feel like a guided credit-review workbench for nontechnical credit professionals.

## Ownership

- Streamlit workflow and layout in `tag_studio/app.py`.
- User-facing labels, help text, errors, success messages, and README workflow language.
- Normal reviewer flow:
  - Add Memo
  - Confirm Sections
  - Tag Credit Review
  - Quality Check
  - Download Results
- Keeping technical controls hidden under Admin Tools.

## Guardrails

- Do not expose raw `memo_id`, `section_id`, `tag_record_id`, source hashes, JSONL, schemas, or file paths in the normal user workflow.
- Prefer credit-language labels over data-engineering labels.
- Keep buttons action-oriented and plain:
  - `Read Memo`
  - `Save Section Review`
  - `Save This Section`
  - `Approve for Training Dataset`
  - `Download Review Workbook`
- Do not add visible instructions that describe implementation internals.
- Keep the workflow linear unless the user asks for a power-user mode.

## Review Checklist

- A nontechnical credit user can tell what to do next on every screen.
- The current memo and step are obvious.
- Error messages say what happened and what the user should do.
- Long text fits within panels without overlapping other UI.
- Admin Tools are not required to complete a normal memo.
- Browser smoke check shows no raw HTML, console errors, or old technical navigation labels.

## Useful Skills

- [Streamlit Wizard UX](../skills/STREAMLIT_WIZARD_UX.md)
- [Credit Tagging Domain](../skills/CREDIT_TAGGING_DOMAIN.md)

