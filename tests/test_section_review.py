from __future__ import annotations

from tag_studio.models import SectionDefinition
from tag_studio.services import classify_section_review, save_section_defs, step_summary
from tag_studio.storage import create_memo_workspace, ensure_workspace, memo_dir, save_sections, write_json


def _workspace_with_memo(tmp_path):
    workspace = tmp_path / "workspace"
    ensure_workspace(workspace)
    save_section_defs(
        workspace,
        [
            SectionDefinition(
                section_id="repayment_analysis",
                display_name="Repayment Analysis",
                aliases=["Primary Repayment"],
                required=True,
            ),
            SectionDefinition(
                section_id="policy_exceptions",
                display_name="Policy Exceptions",
                required=False,
            ),
        ],
    )
    memo = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=b"%PDF-1.4\n% synthetic fixture\n",
        file_name="sample.pdf",
        memo_id="memo_sections_001",
        memo_type="Renewal",
        facility_type="Revolver",
        customer_id="1001",
        reviewer="tester",
    )
    write_json(
        memo_dir(workspace, memo.memo_id) / "extraction" / "page_quality.json",
        [
            {
                "memo_id": memo.memo_id,
                "page_number": 1,
                "status": "Ready",
                "text_quality_score": 0.99,
                "extraction_method": "local_pdf_text",
                "flags": [],
                "reviewer_confirmed": False,
                "reviewer_notes": "",
                "disposition": "Reviewed - acceptable",
            }
        ],
    )
    return workspace, memo.memo_id


def _section(section_id: str, canonical_id: str = "repayment_analysis") -> dict:
    return {
        "section_id": section_id,
        "memo_id": "memo_sections_001",
        "canonical_section_id": canonical_id,
        "canonical_section_name": "Repayment Analysis" if canonical_id == "repayment_analysis" else "Policy Exceptions",
        "original_header": "Primary Repayment",
        "page_start": 1,
        "page_end": 1,
        "line_start": 1,
        "line_end": 6,
        "text": (
            "Primary repayment is supported by operating cash flow. DSCR is 1.45x and leverage is moderate. "
            "Historical performance shows stable EBITDA and adequate liquidity to support the proposed renewal."
        ),
        "extraction_method": "local_pdf_text",
        "reviewer_confirmed": False,
        "missing_required": False,
    }


def _candidate(memo_id: str, confidence: float, section_id: str = "repayment_analysis") -> dict:
    return {
        "candidate_id": "candidate_001",
        "memo_id": memo_id,
        "original_heading": "Primary Repayment",
        "suggested_section_id": section_id,
        "suggested_section_name": "Repayment Analysis" if section_id == "repayment_analysis" else "Policy Exceptions",
        "confidence": confidence,
        "alternate_matches": [],
        "page_start": 1,
        "page_end": 1,
        "line_index": 0,
        "reason": "heading resembles Primary Repayment",
    }


def test_high_confidence_section_is_ready_without_manual_confirmation(tmp_path) -> None:
    workspace, memo_id = _workspace_with_memo(tmp_path)
    save_sections(workspace, memo_id, [_section("section_001")])
    write_json(memo_dir(workspace, memo_id) / "sections" / "section_candidates.json", [_candidate(memo_id, 0.92)])

    summary = classify_section_review(workspace, memo_id)

    assert not summary.must_fix
    assert not summary.can_review_later
    assert len(summary.ready) == 1
    assert step_summary(workspace, memo_id)["Confirm Sections"] == "Complete"


def test_low_confidence_required_section_blocks_continuation(tmp_path) -> None:
    workspace, memo_id = _workspace_with_memo(tmp_path)
    save_sections(workspace, memo_id, [_section("section_001")])
    write_json(memo_dir(workspace, memo_id) / "sections" / "section_candidates.json", [_candidate(memo_id, 0.62)])

    summary = classify_section_review(workspace, memo_id)

    assert len(summary.must_fix) == 1
    assert "low_confidence_match" in summary.must_fix[0].reason_codes
    assert step_summary(workspace, memo_id)["Confirm Sections"] == "Needs Review"


def test_missing_required_section_blocks_continuation(tmp_path) -> None:
    workspace, memo_id = _workspace_with_memo(tmp_path)
    save_sections(workspace, memo_id, [])

    summary = classify_section_review(workspace, memo_id)

    assert len(summary.must_fix) == 1
    assert summary.must_fix[0].missing_section_id == "repayment_analysis"


def test_duplicate_required_section_mapping_blocks_continuation(tmp_path) -> None:
    workspace, memo_id = _workspace_with_memo(tmp_path)
    save_sections(workspace, memo_id, [_section("section_001"), _section("section_002")])
    write_json(memo_dir(workspace, memo_id) / "sections" / "section_candidates.json", [_candidate(memo_id, 0.92)])

    summary = classify_section_review(workspace, memo_id)

    assert len(summary.must_fix) == 2
    assert all("duplicate_standard_section" in item.reason_codes for item in summary.must_fix)
