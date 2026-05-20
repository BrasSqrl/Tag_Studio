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


def pdf_page_count(pdf_path: Path) -> int:
    fitz = _require_fitz()
    with fitz.open(pdf_path) as doc:
        return len(doc)


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


def preprocess_image_for_ocr(image_path: Path) -> Path:
    """Create a deskewed high-contrast OCR copy when OpenCV is available."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return image_path

    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return image_path

    denoised = cv2.fastNlMeansDenoising(image, None, 12, 7, 21)
    thresholded = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresholded < 255))
    if coords.size:
        angle = cv2.minAreaRect(coords)[-1]
        angle = -(90 + angle) if angle < -45 else -angle
        if 0.5 <= abs(angle) <= 12:
            height, width = thresholded.shape[:2]
            matrix = cv2.getRotationMatrix2D((width // 2, height // 2), angle, 1.0)
            thresholded = cv2.warpAffine(
                thresholded,
                matrix,
                (width, height),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )

    output_dir = image_path.parent / "ocr_preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / image_path.name
    cv2.imwrite(str(output_path), thresholded)
    return output_path


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
        raise RuntimeError("Local scanned-PDF reading support is not installed or is not on PATH.")

    pages: list[PageText] = []
    for index, image_path in enumerate(image_paths, start=1):
        try:
            page_number = int(image_path.stem.split("_")[-1])
        except ValueError:
            page_number = index
        ocr_path = preprocess_image_for_ocr(image_path)
        with Image.open(ocr_path) as image:
            text = pytesseract.image_to_string(image).strip()
        pages.append(PageText(page_number=page_number, text=text, extraction_method="local_ocr"))
    return pages


def extract_pdf(pdf_path: Path, pages_dir: Path, force_ocr: bool = False) -> tuple[list[PageText], list[Path], str, str | None]:
    rendered = render_pdf_pages(pdf_path, pages_dir)
    warning: str | None = None

    embedded_pages = extract_embedded_text(pdf_path)
    if force_ocr:
        pages_to_ocr = set(range(1, len(rendered) + 1))
    else:
        pages_to_ocr = {
            page.page_number
            for page in embedded_pages
            if len(page.text.strip()) < MIN_TEXT_CHARS_PER_PAGE
        }
    if not pages_to_ocr:
        return embedded_pages, rendered, "local_pdf_text", warning

    page_lookup = {page.page_number: page for page in embedded_pages}
    try:
        ocr_rendered = [path for path in rendered if int(path.stem.split("_")[-1]) in pages_to_ocr]
        ocr_lookup = {page.page_number: page for page in ocr_images(ocr_rendered)}
        mixed_pages: list[PageText] = []
        for page_number in range(1, len(rendered) + 1):
            if page_number in pages_to_ocr:
                mixed_pages.append(ocr_lookup.get(page_number) or page_lookup.get(page_number) or PageText(page_number=page_number, text="", extraction_method="manual_correction"))
            else:
                mixed_pages.append(page_lookup[page_number])
        method = "local_ocr" if len(pages_to_ocr) == len(rendered) else "local_pdf_text"
        return mixed_pages, rendered, method, warning
    except RuntimeError as exc:
        warning = str(exc)
        if pages_to_ocr:
            warning += f" {len(pages_to_ocr)} page(s) had little embedded text and need review or manual correction."
        return embedded_pages, rendered, "manual_correction", warning
