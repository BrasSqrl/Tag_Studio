# Tag Studio

Tag Studio is a local-first Python/Streamlit application for creating golden-copy tagging data from credit memo PDFs.

It is designed for the CRAIG workflow: upload a credit memo, extract text locally, map memo headings to canonical credit-review sections, tag the memo with evidence, approve the result as gold data, and export Excel plus JSONL files for model tuning.

## Quick Start

```bat
setup_tag_studio.bat
run_tag_studio.bat
```

Then open the local Streamlit URL shown in the terminal, usually:

```text
http://localhost:8501
```

## Notes

- Digital PDFs are extracted locally with PyMuPDF.
- Scanned PDFs require the Tesseract OCR engine to be installed and available on `PATH`.
- Exports are generated as Excel and JSONL files.
- Local workspace data is stored in `tag_studio_workspace/`, which is ignored by Git.

See `README_TAG_STUDIO.md` for more detail.
