# Tag Studio

Tag Studio is a local-first Streamlit application for creating golden-copy tagging data from credit memo PDFs.

## Run

```powershell
.\run_tag_studio.bat
```

Or:

```powershell
python -m streamlit run tag_studio\app.py
```

## What It Does

- Uploads a credit memo PDF.
- Extracts text locally with PyMuPDF.
- Falls back to local OCR with Tesseract when embedded text is weak and Tesseract is installed.
- Renders PDF pages as images.
- Lets users define canonical sections and heading aliases.
- Lets users map original memo headers to consistent canonical section IDs.
- Lets users tag section text, select evidence lines, correct OCR snippets, and submit for review.
- Supports reviewer approval to create `Approved Gold` records.
- Exports Excel and JSONL files for tuning workflows.

## Local Workspace

The app stores data in `tag_studio_workspace/` by default. This folder is the local system of record.

## OCR Note

PyMuPDF and pytesseract are Python packages, but scanned-PDF OCR also requires the Tesseract desktop engine to be installed and available on `PATH`. If Tesseract is not installed, the app still works for digital PDFs and clearly marks scanned PDFs as needing OCR setup or manual correction.
