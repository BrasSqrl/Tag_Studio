from __future__ import annotations

import json
import shutil
from pathlib import Path

import fitz  # type: ignore

from tag_studio.defaults import SCHEMA_VERSION
from tag_studio.exporters import export_excel, export_jsonl
from tag_studio.extraction import extract_pdf
from tag_studio.models import EvidenceRecord, ReviewRecord, TagRecord
from tag_studio.sectioning import propose_sections
from tag_studio.storage import (
    create_memo_workspace,
    ensure_workspace,
    load_evidence,
    load_sections,
    load_tags,
    memo_dir,
    read_json,
    save_evidence,
    save_review,
    save_sections,
    save_tags,
)


def create_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "EXECUTIVE SUMMARY\n"
        "Borrower requests renewal of a $15 million revolving credit facility.\n\n"
        "REPAYMENT ANALYSIS\n"
        "Primary repayment is operating cash flow. DSCR is 1.45x with moderate leverage.\n\n"
        "COVENANTS\n"
        "Borrower will maintain minimum fixed charge coverage and submit monthly borrowing base certificates.\n"
    )
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


def main() -> None:
    workspace = Path("tag_studio_test_workspace")
    if workspace.exists():
        shutil.rmtree(workspace)
    ensure_workspace(workspace)

    sample_pdf = workspace / "sample_credit_memo.pdf"
    create_sample_pdf(sample_pdf)
    pdf_bytes = sample_pdf.read_bytes()
    memo = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=pdf_bytes,
        file_name="sample_credit_memo.pdf",
        memo_id="memo_test_001",
        memo_type="Renewal",
        facility_type="Revolver",
        borrower_name_or_hash="TEST_BORROWER",
        reviewer="tester",
    )

    base = memo_dir(workspace, memo.memo_id)
    pages, _images, method, warning = extract_pdf(base / "source" / "source.pdf", base / "pages")
    if warning:
        raise AssertionError(warning)
    page_dicts = [page.model_dump() for page in pages]
    section_defs = [item for item in read_json(workspace / "config" / "section_schema.json", [])]
    from tag_studio.models import SectionDefinition

    sections = propose_sections(
        memo_id=memo.memo_id,
        pages=page_dicts,
        definitions=[SectionDefinition(**item) for item in section_defs],
        extraction_method=method,
    )
    saved_sections = [section.model_dump() for section in sections]
    for section in saved_sections:
        section["reviewer_confirmed"] = True
    save_sections(workspace, memo.memo_id, saved_sections)

    repayment_section = next(section for section in saved_sections if section["canonical_section_id"] in {"executive_summary", "repayment_analysis"})
    evidence = EvidenceRecord(
        evidence_id="ev_test_001",
        memo_id=memo.memo_id,
        section_id=repayment_section["section_id"],
        page_number=1,
        selected_text="Primary repayment is operating cash flow.",
        source_location="p.1 / REPAYMENT ANALYSIS",
        evidence_role="supporting_fact",
        citation_confidence="High",
        source_document_hash=memo.source_hash,
    )
    save_evidence(workspace, memo.memo_id, [evidence.model_dump()])

    tag = TagRecord(
        tag_record_id="tag_test_001",
        memo_id=memo.memo_id,
        section_id=repayment_section["section_id"],
        tag_id="primary_repayment_source",
        tag_label="Primary repayment source",
        value="Operating cash flow",
        confidence="High",
        evidence_ids=[evidence.evidence_id],
        tagger="tester",
        status="Approved",
    )
    save_tags(workspace, memo.memo_id, [tag.model_dump()])
    save_review(workspace, memo.memo_id, ReviewRecord(memo_id=memo.memo_id, status="Approved Gold", reviewer="tester", adjudicator="tester").model_dump())

    excel_path = export_excel(workspace, include_only_approved=True)
    jsonl_paths = export_jsonl(workspace, include_only_approved=True)

    if not excel_path.exists():
        raise AssertionError("Excel export was not created.")
    for label, path in jsonl_paths.items():
        if not path.exists():
            raise AssertionError(f"{label} JSONL export was not created.")
        for line in path.read_text(encoding="utf-8").splitlines():
            json.loads(line)

    assert load_sections(workspace, memo.memo_id), "Sections were not saved."
    assert load_tags(workspace, memo.memo_id), "Tags were not saved."
    assert load_evidence(workspace, memo.memo_id), "Evidence was not saved."
    print(
        json.dumps(
            {
                "status": "ok",
                "schema_version": SCHEMA_VERSION,
                "extraction_method": method,
                "excel": str(excel_path),
                "jsonl": {key: str(value) for key, value in jsonl_paths.items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
