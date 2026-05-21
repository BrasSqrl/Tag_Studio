from __future__ import annotations

from tag_studio.models import SectionDefinition
from tag_studio.services import facility_review_rows_to_records, save_section_defs, step_summary
from tag_studio.storage import (
    create_memo_workspace,
    ensure_workspace,
    memo_dir,
    save_facilities,
    save_sections,
    write_json,
)


def test_save_facility_review_confirms_completed_rows_by_default(tmp_path) -> None:
    records = facility_review_rows_to_records(
        "memo_facility_001",
        "1001",
        [
            {
                "_facility_id": "",
                "Facility Name": "Senior Revolver",
                "Facility Type": "Revolver",
                "Amount": "$22.5MM",
                "Facility Closing Date": "2025-03-31",
                "Status": "Proposed",
                "Why Suggested": "Borrowing base revolver described in loan structure.",
            }
        ],
    )

    assert len(records) == 1
    assert records[0]["status"] == "Confirmed"
    assert records[0]["reviewer_confirmed"] is True


def test_saved_facility_review_completes_step_four(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    ensure_workspace(workspace)
    save_section_defs(
        workspace,
        [
            SectionDefinition(
                section_id="facility_structure",
                display_name="Facility Structure",
                required=True,
                aliases=["Loan Structure"],
            )
        ],
    )
    memo = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=b"%PDF-1.4\n% synthetic fixture\n",
        file_name="sample.pdf",
        memo_id="memo_facility_001",
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
    save_sections(
        workspace,
        memo.memo_id,
        [
            {
                "section_id": "section_001",
                "memo_id": memo.memo_id,
                "canonical_section_id": "facility_structure",
                "canonical_section_name": "Facility Structure",
                "original_header": "Loan Structure",
                "page_start": 1,
                "page_end": 1,
                "line_start": 1,
                "line_end": 2,
                "text": "The request is for a senior secured revolving credit facility.",
                "extraction_method": "local_pdf_text",
                "reviewer_confirmed": True,
                "missing_required": False,
            }
        ],
    )
    facilities = facility_review_rows_to_records(
        memo.memo_id,
        "1001",
        [
            {
                "Facility Name": "Senior Revolver",
                "Facility Type": "Revolver",
                "Amount": "$22.5MM",
                "Facility Closing Date": "2025-03-31",
                "Status": "Proposed",
            }
        ],
    )

    save_facilities(workspace, memo.memo_id, facilities)

    assert step_summary(workspace, memo.memo_id)["Set Up Facilities"] == "Complete"
