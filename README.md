# Tag Studio

Tag Studio is a local-first credit memo tagging app.

It helps credit professionals upload a memo, confirm the memo sections, tag the credit review with evidence, approve the result, and download the files needed for review and model tuning.

## Quick Start

Double-click:

```bat
Start Tag Studio.bat
```

The first launch may take a few minutes while Tag Studio sets itself up. After that, follow the six steps shown in the app:

1. Add Memo
2. Review Text Quality
3. Confirm Sections
4. Tag Credit Review
5. Quality Check
6. Download Results

## Notes

- Digital PDFs are extracted locally with PyMuPDF.
- Scanned PDFs need local OCR support installed on the computer. Tag Studio will warn you if scanned-PDF reading support is missing.
- Messy pages are flagged for human review before section tagging starts.
- Downloads are generated as a Review Workbook, Training File, and Audit Package.
- Local work is stored in `tag_studio_workspace/`, which is ignored by Git.
- Hosted Shakudo deployments can use S3-backed shared storage; see `README_SHAKUDO.md`.

See `README_TAG_STUDIO.md` for more detail.
