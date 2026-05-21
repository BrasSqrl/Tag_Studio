# Skill Brief: Streamlit Wizard UX

Use this skill when changing the reviewer-facing Streamlit workflow.

## Procedure

1. Identify the user step being changed: Add Memo, Review Memo Sections, Tag Credit Review, Quality Check, or Download Results.
2. Keep the normal workflow linear and plain-language.
3. Hide implementation details unless the user is in Admin Tools.
4. Make the next action obvious with one primary button per screen section.
5. Browser-check the result after changes.

## UI Rules

- Use `Review Workbook`, `Training File`, and `Audit Package` instead of technical export names.
- Use `Standard Memo Section` instead of canonical/schema language in normal screens.
- Use `Approved for Training Dataset` in the UI, while preserving internal `Approved Gold` status if needed.
- Keep credit-review wording concise and direct.
- Do not render indented HTML through `st.markdown`; build HTML strings without leading indentation when `unsafe_allow_html=True`.

## Validation

- `python -m compileall tag_studio`
- Browser smoke check at `http://localhost:8501`
- Confirm no raw HTML, old labels, or technical workflow names appear in the normal flow.
