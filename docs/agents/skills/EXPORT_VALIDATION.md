# Skill Brief: Export Validation

Use this skill when changing Excel export, training-file export, audit packages, schemas, review status, or approval logic.

## Export Contracts

- Review Workbook: Excel workbook for human QA.
- Training File: JSONL files for tuning workflows.
- Audit Package: traceability bundle for QA.

The JSONL training files must keep top-level fields:

```json
{
  "instruction": "...",
  "context": "...",
  "response": "..."
}
```

`response` is a JSON string.

## Guardrails

- Approved records are exported by default.
- JSONL must parse line by line.
- The nested `response` value in each JSONL row must parse as JSON.
- Excel sheets should remain readable and filterable.
- Export changes must preserve memo, section, tag, evidence, review status, and schema version lineage.
- Evidence attached to exported tags must exist, belong to the same memo and section, and match the source hash.
- Draft/non-approved exports belong only in admin/debug workflows.

## Validation

Run:

```powershell
python verify_tag_studio.py
```

For manual checks:

- Confirm exported JSONL files exist and parse.
- Confirm every JSONL `response` field parses as JSON.
- Confirm Excel export contains memo, section, tag, evidence, review status, and export manifest data.
- Confirm normal UI labels remain plain-language.
