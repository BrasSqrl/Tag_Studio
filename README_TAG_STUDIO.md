# Tag Studio

Tag Studio is a local-first Streamlit application for creating golden-copy tagging data from credit memo PDFs.

## Run

For normal users, double-click:

```powershell
.\Start Tag Studio.bat
```

For admin/debug use, run Streamlit directly:

```powershell
python -m streamlit run tag_studio\app.py
```

## What It Does

- Uploads a credit memo PDF.
- Extracts text locally with PyMuPDF.
- Renders PDF pages as images.
- Falls back to local OCR when embedded text is weak and local OCR support is installed.
- Uses optional OpenCV preprocessing to improve OCR on skewed, low-contrast, or noisy page images.
- Creates page-quality records, layout blocks, reading order, text-reading warnings, and section candidates.
- Lets users review page text quality before section confirmation.
- Lets users define standard memo sections and heading aliases.
- Lets users map original memo headers to consistent standard section IDs.
- Lets users tag section text, select evidence lines, correct OCR snippets, and submit for review.
- Supports reviewer approval to create `Approved Gold` records.
- Exports Excel and JSONL files for tuning workflows.

## Local Workspace

The app stores data in `tag_studio_workspace/` by default. This folder is the local system of record.

For hosted Shakudo deployments, Tag Studio can run with `TAG_STUDIO_STORAGE_BACKEND=s3`. In that mode, S3 is the durable system of record and the local workspace is only a working cache.

## OCR Note

Amazon Textract is AWS's cloud document-analysis and OCR service. Tag Studio does not currently call Textract. The current scanned-PDF path is local-first and uses the Tesseract desktop OCR engine through `pytesseract`, so it can run without AWS credentials.

PyMuPDF and pytesseract are Python packages, but scanned-PDF OCR also requires the local Tesseract desktop engine to be installed and available on `PATH`. If local OCR support is not installed, the app still works for digital PDFs and clearly marks scanned PDFs as needing OCR setup or manual correction.

The robust intake path also installs OCR/layout Python packages listed in `requirements.txt`. Paddle runtime support is pinned for Python versions before 3.13 because Paddle packages may lag newer Python releases; Python 3.11 is the recommended runtime for full OCR/layout support.
