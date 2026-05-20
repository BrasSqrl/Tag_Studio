from __future__ import annotations

from tag_studio.services import quality_findings
from tag_studio.storage import create_memo_workspace, ensure_workspace, memo_dir, save_sections, write_json


def test_quality_findings_flags_unreviewed_pages_and_missing_tags(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    ensure_workspace(workspace)
    memo = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=b"%PDF-1.4\n% synthetic fixture\n",
        file_name="sample.pdf",
        memo_id="memo_quality_001",
        memo_type="Renewal",
        facility_type="Revolver",
        borrower_name_or_hash="SYNTHETIC",
        reviewer="tester",
    )
    save_sections(
        workspace,
        memo.memo_id,
        [
            {
                "section_id": "section_001",
                "memo_id": memo.memo_id,
                "canonical_section_id": "executive_summary",
                "canonical_section_name": "Executive Summary",
                "original_header": "Executive Summary",
                "page_start": 1,
                "page_end": 1,
                "text": "Credit request summary.",
                "extraction_method": "local_pdf_text",
                "reviewer_confirmed": True,
                "missing_required": False,
            }
        ],
    )
    write_json(
        memo_dir(workspace, memo.memo_id) / "extraction" / "page_quality.json",
        [
            {
                "memo_id": memo.memo_id,
                "page_number": 1,
                "status": "Hard to Read",
                "text_quality_score": 0.3,
                "extraction_method": "local_pdf_text",
                "flags": ["low_text_density"],
                "reviewer_confirmed": False,
                "reviewer_notes": "",
            }
        ],
    )
    write_json(memo_dir(workspace, memo.memo_id) / "extraction" / "ocr_warnings.json", [])

    findings, metrics = quality_findings(workspace, memo.memo_id)

    assert metrics["pages_need_review"] == 1
    assert any("Hard-to-read pages" in finding for finding in findings)
    assert any("No credit tags" in finding for finding in findings)
    assert any("Missing required tags" in finding for finding in findings)
