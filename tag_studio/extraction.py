from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from .models import PageText


MIN_TEXT_CHARS_PER_PAGE = 80


def _require_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF extraction. Install with: pip install PyMuPDF") from exc
    return fitz


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def render_pdf_pages(pdf_path: Path, pages_dir: Path, zoom: float = 1.6) -> list[Path]:
    fitz = _require_fitz()
    pages_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    with fitz.open(pdf_path) as doc:
        matrix = fitz.Matrix(zoom, zoom)
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            path = pages_dir / f"page_{index:03}.png"
            pix.save(path)
            rendered.append(path)
    return rendered


def extract_embedded_text(pdf_path: Path) -> list[PageText]:
    fitz = _require_fitz()
    pages: list[PageText] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            pages.append(PageText(page_number=index, text=text, extraction_method="local_pdf_text"))
    return pages


def ocr_images(image_paths: list[Path]) -> list[PageText]:
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pytesseract is required for OCR. Install with: pip install pytesseract") from exc
    if not tesseract_available():
        raise RuntimeError("The Tesseract OCR engine is not installed or is not on PATH.")

    pages: list[PageText] = []
    for index, image_path in enumerate(image_paths, start=1):
        with Image.open(image_path) as image:
            text = pytesseract.image_to_string(image).strip()
        pages.append(PageText(page_number=index, text=text, extraction_method="local_ocr"))
    return pages


def extract_pdf(pdf_path: Path, pages_dir: Path, force_ocr: bool = False) -> tuple[list[PageText], list[Path], str, str | None]:
    rendered = render_pdf_pages(pdf_path, pages_dir)
    warning: str | None = None

    if not force_ocr:
        embedded_pages = extract_embedded_text(pdf_path)
        avg_chars = sum(len(page.text) for page in embedded_pages) / max(len(embedded_pages), 1)
        if avg_chars >= MIN_TEXT_CHARS_PER_PAGE:
            return embedded_pages, rendered, "local_pdf_text", warning

    try:
        ocr_pages = ocr_images(rendered)
        return ocr_pages, rendered, "local_ocr", warning
    except RuntimeError as exc:
        fallback_pages = extract_embedded_text(pdf_path)
        warning = str(exc)
        if not any(page.text for page in fallback_pages):
            warning += " No embedded text was found; use manual correction or install Tesseract."
        return fallback_pages, rendered, "manual_correction", warning
