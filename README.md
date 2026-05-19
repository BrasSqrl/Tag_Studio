# Tag Studio

Tag Studio is a local-first credit memo tagging app.

It helps credit professionals upload a memo, confirm the memo sections, tag the credit review with evidence, approve the result, and download the files needed for review and model tuning.

## Quick Start

Double-click:

```bat
Start Tag Studio.bat
```

The first launch may take a few minutes while Tag Studio sets itself up. After that, follow the five steps shown in the app:

1. Add Memo
2. Confirm Sections
3. Tag Credit Review
4. Quality Check
5. Download Results

## Notes

- Digital PDFs are extracted locally with PyMuPDF.
- Scanned PDFs need OCR support installed on the computer.
- Downloads are generated as a Review Workbook, Training File, and Audit Package.
- Local work is stored in `tag_studio_workspace/`, which is ignored by Git.

See `README_TAG_STUDIO.md` for more detail.
