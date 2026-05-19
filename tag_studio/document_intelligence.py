from __future__ import annotations

import importlib.util
import statistics
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from .extraction import extract_pdf, tesseract_available
from .models import ExtractionWarningRecord, LayoutBlockRecord, PageQualityRecord, PageText
from .sectioning import heading_candidates, propose_section_candidates
from .storage import memo_dir, read_json, sync_path_to_remote, write_json


def _optional_module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def dependency_status() -> dict[str, bool]:
    return {
        "tesseract": tesseract_available(),
        "opencv": _optional_module_available("cv2"),
        "pypdfium2": _optional_module_available("pypdfium2"),
        "ocrmypdf": _optional_module_available("ocrmypdf"),
        "paddleocr": _optional_module_available("paddleocr"),
        "paddle": _optional_module_available("paddle"),
    }


def _image_quality_flags(image_path: Path, text: str, method: str) -> tuple[float, list[str]]:
    flags: list[str] = []
    score = 1.0
    with Image.open(image_path) as image:
        grayscale = image.convert("L")
        width, height = grayscale.size
        stat = ImageStat.Stat(grayscale)
        brightness = float(stat.mean[0])
        contrast = float(stat.stddev[0])
        pixel_count = width * height

    if pixel_count < 800_000:
        flags.append("Low resolution")
        score -= 0.18
    if contrast < 28:
        flags.append("Low contrast")
        score -= 0.18
    if brightness < 55 or brightness > 235:
        flags.append("Uneven brightness")
        score -= 0.12
    if len(text.strip()) < 80:
        flags.append("Very little readable text")
        score -= 0.28
    if method == "manual_correction":
        flags.append("Manual correction likely needed")
        score -= 0.22
    if _looks_like_table(text):
        flags.append("Table heavy")
        score -= 0.05
    if _looks_like_possible_handwriting(text):
        flags.append("Possible handwriting")
        score -= 0.10
    return max(0.0, min(1.0, score)), flags


def _looks_like_table(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    numeric_lines = sum(any(char.isdigit() for char in line) and (line.count(" ") >= 4 or "\t" in line) for line in lines)
    return numeric_lines >= max(3, len(lines) // 4)


def _looks_like_possible_handwriting(text: str) -> bool:
    lowered = text.lower()
    note_terms = ["handwritten", "scribble", "initialed", "signature", "signed", "margin note"]
    return any(term in lowered for term in note_terms)


def _quality_status(score: float, flags: list[str]) -> str:
    if "Possible handwriting" in flags:
        return "Possible Handwriting"
    if "Table heavy" in flags:
        return "Table Heavy"
    if score < 0.45:
        return "Hard to Read"
    if flags:
        return "Needs Review"
    return "Ready"


def build_page_quality(memo_id: str, pages: list[PageText], page_images: list[Path], method: str) -> list[PageQualityRecord]:
    image_lookup = {int(path.stem.split("_")[-1]): path for path in page_images}
    records: list[PageQualityRecord] = []
    for page in pages:
        image_path = image_lookup.get(page.page_number)
        if image_path and image_path.exists():
            score, flags = _image_quality_flags(image_path, page.text, method)
        else:
            score, flags = 0.35, ["Page image missing"]
        records.append(
            PageQualityRecord(
                memo_id=memo_id,
                page_number=page.page_number,
                status=_quality_status(score, flags),  # type: ignore[arg-type]
                text_quality_score=round(score, 3),
                extraction_method=page.extraction_method,
                flags=flags,
                reviewer_confirmed=False,
            )
        )
    return records


def build_layout_blocks(memo_id: str, pages: list[PageText]) -> list[LayoutBlockRecord]:
    blocks: list[LayoutBlockRecord] = []
    for page in pages:
        headings = {line_idx for _heading, line_idx in heading_candidates(page.text)}
        order = 0
        for line_idx, line in enumerate(page.text.splitlines()):
            clean = line.strip()
            if not clean:
                continue
            order += 1
            block_type = "heading" if line_idx in headings else "paragraph"
            if _looks_like_table(clean):
                block_type = "table"
            if _looks_like_possible_handwriting(clean):
                block_type = "handwritten_note"
            blocks.append(
                LayoutBlockRecord(
                    block_id=f"block_p{page.page_number:03}_{order:04}",
                    memo_id=memo_id,
                    page_number=page.page_number,
                    block_type=block_type,  # type: ignore[arg-type]
                    text=clean,
                    bbox=[],
                    confidence=page.extraction_confidence,
                    source=page.extraction_method,
                    reading_order=order,
                )
            )
    return blocks


def build_warnings(memo_id: str, page_quality: list[PageQualityRecord], extraction_warning: str | None) -> list[ExtractionWarningRecord]:
    warnings: list[ExtractionWarningRecord] = []
    if extraction_warning:
        warnings.append(
            ExtractionWarningRecord(
                warning_id="warning_extraction_001",
                memo_id=memo_id,
                severity="Review",
                message=extraction_warning,
                action="Review extracted text before confirming sections.",
            )
        )
    for record in page_quality:
        if record.status != "Ready":
            warnings.append(
                ExtractionWarningRecord(
                    warning_id=f"warning_page_{record.page_number:03}",
                    memo_id=memo_id,
                    page_number=record.page_number,
                    severity="Review" if record.status != "Hard to Read" else "Blocking",
                    message=f"Page {record.page_number} is marked {record.status}.",
                    action="Open this page in Review Text Quality and confirm or correct the text.",
                )
            )
    return warnings


def run_document_intelligence(
    workspace: Path,
    memo_id: str,
    definitions: list[Any],
    force_ocr: bool = False,
) -> dict[str, Any]:
    base = memo_dir(workspace, memo_id)
    pages, rendered_paths, method, warning = extract_pdf(base / "source" / "source.pdf", base / "pages", force_ocr=force_ocr)
    sync_path_to_remote(workspace, base / "pages")
    page_quality = build_page_quality(memo_id, pages, rendered_paths, method)
    layout_blocks = build_layout_blocks(memo_id, pages)
    section_candidates = propose_section_candidates(memo_id, [page.model_dump() for page in pages], definitions)
    warnings = build_warnings(memo_id, page_quality, warning)

    reading_order = [
        {
            "memo_id": block.memo_id,
            "page_number": block.page_number,
            "block_id": block.block_id,
            "reading_order": block.reading_order,
            "block_type": block.block_type,
        }
        for block in layout_blocks
    ]

    write_json(base / "extraction" / "page_text.json", [page.model_dump() for page in pages])
    write_json(base / "extraction" / "page_quality.json", [record.model_dump() for record in page_quality])
    write_json(base / "extraction" / "layout_blocks.json", [record.model_dump() for record in layout_blocks])
    write_json(base / "extraction" / "reading_order.json", reading_order)
    write_json(base / "extraction" / "ocr_warnings.json", [record.model_dump() for record in warnings])
    write_json(base / "sections" / "section_candidates.json", [record.model_dump() for record in section_candidates])
    write_json(
        base / "extraction" / "extraction_summary.json",
        {
            "method": method,
            "warning": warning,
            "page_count": len(pages),
            "rendered_pages": [str(path) for path in rendered_paths],
            "dependency_status": dependency_status(),
            "quality_summary": summarize_page_quality([record.model_dump() for record in page_quality]),
        },
    )
    return {
        "pages": pages,
        "rendered_paths": rendered_paths,
        "method": method,
        "warning": warning,
        "page_quality": page_quality,
        "layout_blocks": layout_blocks,
        "section_candidates": section_candidates,
        "warnings": warnings,
    }


def load_page_quality(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "extraction" / "page_quality.json", [])


def save_page_quality(workspace: Path, memo_id: str, records: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "extraction" / "page_quality.json", records)


def load_page_text(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "extraction" / "page_text.json", [])


def save_page_text(workspace: Path, memo_id: str, records: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "extraction" / "page_text.json", records)


def load_extraction_warnings(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "extraction" / "ocr_warnings.json", [])


def load_section_candidates(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "sections" / "section_candidates.json", [])


def summarize_page_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(record.get("text_quality_score", 0)) for record in records]
    statuses: dict[str, int] = {}
    for record in records:
        statuses[str(record.get("status", "Needs Review"))] = statuses.get(str(record.get("status", "Needs Review")), 0) + 1
    return {
        "page_count": len(records),
        "average_score": round(statistics.mean(scores), 3) if scores else 0,
        "statuses": statuses,
        "needs_review_count": sum(
            1
            for record in records
            if record.get("status") != "Ready" and not record.get("reviewer_confirmed")
        ),
    }
