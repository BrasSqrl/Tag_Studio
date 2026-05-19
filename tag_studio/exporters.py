from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .defaults import SCHEMA_VERSION
from .storage import (
    list_memo_ids,
    load_evidence,
    load_memo_record,
    load_review,
    load_sections,
    load_tags,
    memo_dir,
)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _approved_memo_ids(workspace: Path, include_only_approved: bool) -> list[str]:
    memo_ids = list_memo_ids(workspace)
    if not include_only_approved:
        return memo_ids
    return [memo_id for memo_id in memo_ids if load_review(workspace, memo_id).get("status") == "Approved Gold"]


def build_export_tables(workspace: Path, include_only_approved: bool = True) -> dict[str, list[dict[str, Any]]]:
    memo_ids = _approved_memo_ids(workspace, include_only_approved)
    tables = {
        "Memos": [],
        "Sections": [],
        "Section Mapping": [],
        "Tags": [],
        "Evidence": [],
        "Scores": [],
        "Outcomes": [],
        "Review Status": [],
        "Export Manifest": [],
    }

    for memo_id in memo_ids:
        memo = load_memo_record(workspace, memo_id)
        review = load_review(workspace, memo_id)
        sections = load_sections(workspace, memo_id)
        tags = load_tags(workspace, memo_id)
        evidence = load_evidence(workspace, memo_id)

        tables["Memos"].append(memo)
        tables["Review Status"].append(review)
        tables["Sections"].extend(sections)
        tables["Section Mapping"].extend(
            {
                "memo_id": memo_id,
                "section_id": section.get("section_id"),
                "original_header": section.get("original_header"),
                "canonical_section_id": section.get("canonical_section_id"),
                "canonical_section_name": section.get("canonical_section_name"),
                "page_start": section.get("page_start"),
                "page_end": section.get("page_end"),
                "reviewer_confirmed": section.get("reviewer_confirmed"),
            }
            for section in sections
        )
        tables["Tags"].extend(tags)
        tables["Evidence"].extend(evidence)
        tables["Scores"].extend(tag for tag in tags if "score" in str(tag.get("tag_id", "")))
        tables["Outcomes"].extend(tag for tag in tags if str(tag.get("tag_id", "")).startswith("outcome"))

    tables["Export Manifest"].append(
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "include_only_approved": include_only_approved,
            "memo_count": len(memo_ids),
            "memo_ids": ", ".join(memo_ids),
        }
    )
    return tables


def export_excel(workspace: Path, include_only_approved: bool = True) -> Path:
    export_dir = workspace / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"tag_studio_export_{_now_stamp()}.xlsx"
    tables = build_export_tables(workspace, include_only_approved=include_only_approved)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, rows in tables.items():
            df = pd.DataFrame(rows)
            if df.empty:
                df = pd.DataFrame([{"note": "No records exported"}])
            df.to_excel(writer, index=False, sheet_name=sheet_name[:31])

    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = load_workbook(path)
    header_fill = PatternFill("solid", fgColor="17324D")
    header_font = Font(color="FFFFFF", bold=True)
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
        for column_cells in sheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in column_cells)
            sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(max_len + 2, 12), 50)
    workbook.save(path)
    return path


def _tags_for_section(tags: list[dict[str, Any]], section_id: str) -> list[dict[str, Any]]:
    return [tag for tag in tags if tag.get("section_id") == section_id]


def _evidence_by_id(evidence: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item.get("evidence_id"): item for item in evidence}


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def export_jsonl(workspace: Path, include_only_approved: bool = True) -> dict[str, Path]:
    export_dir = workspace / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    section_path = export_dir / f"training_sections_{stamp}.jsonl"
    memo_path = export_dir / f"training_memos_{stamp}.jsonl"
    audit_path = export_dir / f"audit_records_{stamp}.jsonl"

    memo_ids = _approved_memo_ids(workspace, include_only_approved)
    with section_path.open("w", encoding="utf-8") as section_file, memo_path.open("w", encoding="utf-8") as memo_file, audit_path.open("w", encoding="utf-8") as audit_file:
        for memo_id in memo_ids:
            memo = load_memo_record(workspace, memo_id)
            review = load_review(workspace, memo_id)
            sections = load_sections(workspace, memo_id)
            tags = load_tags(workspace, memo_id)
            evidence = load_evidence(workspace, memo_id)
            evidence_lookup = _evidence_by_id(evidence)

            for section in sections:
                section_tags = _tags_for_section(tags, section.get("section_id"))
                section_evidence_ids = {
                    evidence_id
                    for tag in section_tags
                    for evidence_id in tag.get("evidence_ids", [])
                    if evidence_id in evidence_lookup
                }
                response = {
                    "schema_version": SCHEMA_VERSION,
                    "memo_id": memo_id,
                    "section_id": section.get("section_id"),
                    "canonical_section_id": section.get("canonical_section_id"),
                    "canonical_section_name": section.get("canonical_section_name"),
                    "original_header": section.get("original_header"),
                    "tags": section_tags,
                    "evidence": [evidence_lookup[evidence_id] for evidence_id in sorted(section_evidence_ids)],
                }
                context = (
                    f"Memo ID: {memo_id}\n"
                    f"Memo type: {memo.get('memo_type', '')}\n"
                    f"Facility type: {memo.get('facility_type', '')}\n"
                    f"Original heading: {section.get('original_header', '')}\n"
                    f"Canonical section: {section.get('canonical_section_name', '')}\n"
                    f"Page range: {section.get('page_start')} to {section.get('page_end')}\n\n"
                    f"Section text:\n{section.get('text', '')}"
                )
                section_file.write(
                    _json_dumps(
                        {
                            "instruction": "Extract CRAIG underwriting tags for this credit memo section using the canonical section mapping and cited evidence.",
                            "context": context,
                            "response": _json_dumps(response),
                        }
                    )
                    + "\n"
                )

            memo_text = "\n\n".join(
                f"[{section.get('canonical_section_name')} / {section.get('original_header')}]\n{section.get('text', '')}"
                for section in sections
            )
            memo_response = {
                "schema_version": SCHEMA_VERSION,
                "memo_id": memo_id,
                "memo": memo,
                "review": review,
                "sections": [
                    {
                        "section_id": section.get("section_id"),
                        "canonical_section_id": section.get("canonical_section_id"),
                        "canonical_section_name": section.get("canonical_section_name"),
                        "original_header": section.get("original_header"),
                    }
                    for section in sections
                ],
                "tags": tags,
                "evidence": evidence,
            }
            memo_file.write(
                _json_dumps(
                    {
                        "instruction": "Produce a complete CRAIG RCO-assistive memo review from the tagged credit memo, including completeness, underwriting strength, cited weaknesses, and structure enhancement opportunities.",
                        "context": (
                            f"Memo ID: {memo_id}\n"
                            f"Memo type: {memo.get('memo_type', '')}\n"
                            f"Facility type: {memo.get('facility_type', '')}\n"
                            f"Source hash: {memo.get('source_hash', '')}\n\n"
                            f"Memo text:\n{memo_text}"
                        ),
                        "response": _json_dumps(memo_response),
                    }
                )
                + "\n"
            )
            audit_file.write(
                _json_dumps(
                    {
                        "memo_id": memo_id,
                        "schema_version": SCHEMA_VERSION,
                        "source_hash": memo.get("source_hash", ""),
                        "review_status": review.get("status"),
                        "exported_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                + "\n"
            )

    return {"sections": section_path, "memos": memo_path, "audit": audit_path}


def export_memo_bundle(workspace: Path, memo_id: str) -> Path:
    export_dir = memo_dir(workspace, memo_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{memo_id}_bundle_{_now_stamp()}.json"
    payload = {
        "memo": load_memo_record(workspace, memo_id),
        "review": load_review(workspace, memo_id),
        "sections": load_sections(workspace, memo_id),
        "tags": load_tags(workspace, memo_id),
        "evidence": load_evidence(workspace, memo_id),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
