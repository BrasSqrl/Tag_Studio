# Backend Agent

## Mission

Keep Tag Studio's local extraction, storage, sectioning, schema, and export behavior reliable and traceable.

## Ownership

- PDF extraction and page rendering in `tag_studio/extraction.py`.
- Local file workspace and audit writes in `tag_studio/storage.py`.
- Section detection and required-section checks in `tag_studio/sectioning.py`.
- Data contracts in `tag_studio/models.py`.
- Default sections/tags in `tag_studio/defaults.py`.
- Excel, training-file, and audit export logic in `tag_studio/exporters.py`.

## Guardrails

- Preserve local-first operation. AWS/Textract or cloud dependencies must remain optional unless the user explicitly changes direction.
- Keep source PDFs, workspace outputs, and real memo data out of Git.
- Never mutate or replace `source/source.pdf` or `source_hash.txt`; regenerate derived extraction files only intentionally.
- Preserve evidence lineage: memo, section, page, selected text, reviewer, and schema version must remain traceable.
- Evidence attached to a tag must belong to the same memo and section, and the evidence source hash must match the memo source hash.
- Treat sectioning as a proposal. Final training eligibility requires reviewer confirmation or explicit missing-section marking.
- Default final exports must include only `Approved Gold` records. Draft export belongs only in admin/debug workflows.
- Do not overwrite user-customized workspace config after initialization.
- Do not change JSONL top-level shape without updating validation and release docs.
- Schema changes require `SCHEMA_VERSION` handling and export compatibility notes.
- Avoid backend changes that require nontechnical users to understand folders, schemas, or raw IDs.

## Review Checklist

- Digital PDF extraction still works.
- Scanned PDF fallback gives a clear nonfatal result when Tesseract is unavailable.
- Section records preserve original heading and standard section.
- Required-section checks still work by memo/facility type.
- Exported Excel opens and contains expected sheets.
- Exported training files are valid JSONL.
- Nested JSON in every JSONL `response` field parses.
- No dangling memo/section/tag/evidence references exist.
- `python verify_tag_studio.py` passes.

## Useful Skills

- [PDF Extraction and Storage](../skills/PDF_EXTRACTION_STORAGE.md)
- [Export Validation](../skills/EXPORT_VALIDATION.md)
