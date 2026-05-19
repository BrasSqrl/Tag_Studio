# Skill Brief: PDF Extraction and Storage

Use this skill when changing PDF reading, OCR fallback, page images, local workspace data, or audit records.

## Current Flow

1. User uploads a PDF in the app.
2. Tag Studio writes it to the local workspace.
3. PyMuPDF renders pages and extracts embedded text.
4. If embedded text is weak, local OCR is attempted when Tesseract is available.
5. Section proposals are generated and saved locally.

## Guardrails

- Local extraction must work without AWS credentials.
- Missing OCR support should produce a friendly warning, not a crash.
- Source hash, original filename, page images, extracted text, sections, tags, evidence, review status, and audit logs must remain traceable.
- Never mutate or replace the original `source/source.pdf` or `source_hash.txt`.
- Do not overwrite user-customized `config/section_schema.json` or `config/tag_schema.json` after workspace initialization.
- Sectioning output is a proposal until the reviewer confirms it.
- Workspace and source PDFs must stay out of Git.

## Validation

- Upload/read a digital PDF.
- Confirm page images are created.
- Confirm rendered page count matches extracted page count.
- Confirm extraction method is one of the supported values.
- Confirm audit JSONL parses line by line after extraction and save actions.
- Confirm `python verify_tag_studio.py` passes.
- If modifying OCR behavior, test the no-Tesseract path or inspect the warning path.
