from __future__ import annotations

from tag_studio.models import SectionDefinition
from tag_studio.sectioning import ranked_section_matches
from tag_studio.services import (
    apply_section_cleanup,
    load_learned_heading_matches,
    save_learned_heading_match,
    section_cleanup_blocks,
    undo_last_section_cleanup,
)
from tag_studio.storage import create_memo_workspace, ensure_workspace, load_sections, save_sections


def _workspace_with_sections(tmp_path):
    workspace = tmp_path / "workspace"
    ensure_workspace(workspace)
    memo = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=b"%PDF-1.4\n% synthetic fixture\n",
        file_name="sample.pdf",
        memo_id="memo_cleanup_001",
        memo_type="Renewal",
        facility_type="Revolver",
        customer_id="1001",
        reviewer="tester",
    )
    sections = [
        {
            "section_id": "section_001",
            "memo_id": memo.memo_id,
            "canonical_section_id": "repayment_analysis",
            "canonical_section_name": "Repayment Analysis",
            "original_header": "Primary Repayment",
            "page_start": 1,
            "page_end": 1,
            "line_start": 1,
            "line_end": 4,
            "text": (
                "Cash flow is the primary repayment source.\n\n"
                "Collateral availability supports the borrowing base.\n\n"
                "Cash flow paragraph repeated by OCR."
            ),
            "extraction_method": "local_pdf_text",
            "reviewer_confirmed": False,
            "missing_required": False,
        },
        {
            "section_id": "section_002",
            "memo_id": memo.memo_id,
            "canonical_section_id": "collateral",
            "canonical_section_name": "Collateral",
            "original_header": "Collateral",
            "page_start": 1,
            "page_end": 1,
            "line_start": 5,
            "line_end": 6,
            "text": "Inventory and receivables are pledged.",
            "extraction_method": "local_pdf_text",
            "reviewer_confirmed": False,
            "missing_required": False,
        },
    ]
    save_sections(workspace, memo.memo_id, sections)
    definitions = {
        "repayment_analysis": SectionDefinition(section_id="repayment_analysis", display_name="Repayment Analysis"),
        "collateral": SectionDefinition(section_id="collateral", display_name="Collateral"),
        "risk_assessment": SectionDefinition(section_id="risk_assessment", display_name="Risk Assessment"),
    }
    return workspace, memo.memo_id, definitions


def test_section_cleanup_blocks_use_paragraphs_first(tmp_path) -> None:
    workspace, memo_id, _definitions = _workspace_with_sections(tmp_path)
    section = load_sections(workspace, memo_id)[0]

    blocks = section_cleanup_blocks(section)

    assert [block.label for block in blocks] == ["Text block 1", "Text block 2", "Text block 3"]
    assert blocks[1].text == "Collateral availability supports the borrowing base."


def test_apply_section_cleanup_moves_duplicates_and_undoes(tmp_path) -> None:
    workspace, memo_id, definitions = _workspace_with_sections(tmp_path)
    section = load_sections(workspace, memo_id)[0]
    blocks = section_cleanup_blocks(section)

    apply_section_cleanup(
        workspace,
        memo_id,
        "section_001",
        {
            blocks[0].block_id: {"action": "Keep Here"},
            blocks[1].block_id: {"action": "Move to Another Section", "target_section_id": "section_002"},
            blocks[2].block_id: {"action": "Mark as Duplicate"},
        },
        definitions,
    )

    updated = {section["section_id"]: section for section in load_sections(workspace, memo_id)}
    assert updated["section_001"]["text"] == "Cash flow is the primary repayment source."
    assert "Collateral availability supports the borrowing base." in updated["section_002"]["text"]
    assert "repeated by OCR" not in updated["section_001"]["text"]

    assert undo_last_section_cleanup(workspace, memo_id)
    restored = {section["section_id"]: section for section in load_sections(workspace, memo_id)}
    assert "Cash flow paragraph repeated by OCR." in restored["section_001"]["text"]
    assert "Collateral availability supports the borrowing base." not in restored["section_002"]["text"]


def test_apply_section_cleanup_can_start_new_section(tmp_path) -> None:
    workspace, memo_id, definitions = _workspace_with_sections(tmp_path)
    section = load_sections(workspace, memo_id)[0]
    blocks = section_cleanup_blocks(section)

    apply_section_cleanup(
        workspace,
        memo_id,
        "section_001",
        {
            blocks[0].block_id: {"action": "Keep Here"},
            blocks[1].block_id: {"action": "Start New Section Here", "new_standard_section_id": "risk_assessment"},
            blocks[2].block_id: {"action": "Keep Here"},
        },
        definitions,
    )

    sections = load_sections(workspace, memo_id)
    created = [section for section in sections if section["canonical_section_id"] == "risk_assessment"]
    assert len(created) == 1
    assert created[0]["canonical_section_name"] == "Risk Assessment"
    assert created[0]["text"] == "Collateral availability supports the borrowing base."


def test_learned_heading_match_is_used_by_section_ranking(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    ensure_workspace(workspace)
    definitions = [
        SectionDefinition(section_id="repayment_analysis", display_name="Repayment Analysis"),
        SectionDefinition(section_id="collateral", display_name="Collateral"),
    ]

    save_learned_heading_match(workspace, "repayment_analysis", "Debt Service Support")
    learned = load_learned_heading_matches(workspace)
    ranked = ranked_section_matches("Debt Service Support", definitions, learned_headings=learned)

    assert learned == {"repayment_analysis": ["Debt Service Support"]}
    assert ranked[0][0].section_id == "repayment_analysis"
    assert ranked[0][1] >= 0.9
