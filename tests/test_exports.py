from __future__ import annotations

import json

from tag_studio.exporters import export_jsonl
from tag_studio.models import EvidenceRecord, ReviewRecord, TagRecord
from tag_studio.storage import (
    create_memo_workspace,
    ensure_workspace,
    memo_dir,
    save_evidence,
    save_review,
    save_sections,
    save_tags,
    write_json,
)


def test_jsonl_export_preserves_instruction_context_response_shape(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    ensure_workspace(workspace)
    memo = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=b"%PDF-1.4\n% synthetic fixture\n",
        file_name="sample.pdf",
        memo_id="memo_export_001",
        memo_type="Renewal",
        facility_type="Revolver",
        borrower_name_or_hash="SYNTHETIC",
        reviewer="tester",
    )
    section = {
        "section_id": "section_001",
        "memo_id": memo.memo_id,
        "canonical_section_id": "repayment_analysis",
        "canonical_section_name": "Repayment Analysis",
        "original_header": "Primary Repayment",
        "page_start": 1,
        "page_end": 1,
        "text": "Primary repayment is operating cash flow with DSCR of 1.45x.",
        "extraction_method": "local_pdf_text",
        "reviewer_confirmed": True,
        "missing_required": False,
    }
    save_sections(workspace, memo.memo_id, [section])
    evidence = EvidenceRecord(
        evidence_id="ev_001",
        memo_id=memo.memo_id,
        section_id=section["section_id"],
        page_number=1,
        selected_text="Primary repayment is operating cash flow.",
        source_location="p.1 / Primary Repayment",
        evidence_role="supporting_fact",
        citation_confidence="High",
        source_document_hash=memo.source_hash,
    )
    save_evidence(workspace, memo.memo_id, [evidence.model_dump()])
    tag = TagRecord(
        tag_record_id="tag_001",
        memo_id=memo.memo_id,
        section_id=section["section_id"],
        tag_id="primary_repayment_source",
        tag_label="Primary repayment source",
        value="Operating cash flow",
        confidence="High",
        evidence_ids=[evidence.evidence_id],
        tagger="tester",
    )
    save_tags(workspace, memo.memo_id, [tag.model_dump()])
    save_review(
        workspace,
        memo.memo_id,
        ReviewRecord(memo_id=memo.memo_id, status="Approved Gold", reviewer="tester").model_dump(),
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
            }
        ],
    )
    write_json(memo_dir(workspace, memo.memo_id) / "extraction" / "ocr_warnings.json", [])

    paths = export_jsonl(workspace, include_only_approved=True)

    for path in paths.values():
        assert path.exists()
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if "instruction" in record:
                assert set(record) == {"instruction", "context", "response"}
                assert isinstance(record["instruction"], str)
                assert isinstance(record["context"], str)
                json.loads(record["response"])
