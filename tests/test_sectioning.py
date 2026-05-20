from __future__ import annotations

from tag_studio.defaults import DEFAULT_SECTIONS
from tag_studio.models import SectionDefinition
from tag_studio.sectioning import ranked_section_matches, required_section_gaps


def test_alias_heading_ranks_repayment_analysis_first() -> None:
    ranked = ranked_section_matches("Primary Repayment", DEFAULT_SECTIONS)

    assert ranked
    assert ranked[0][0].section_id == "repayment_analysis"
    assert ranked[0][1] >= 0.9


def test_required_section_gaps_respect_memo_and_facility_filters() -> None:
    definitions = [
        SectionDefinition(
            section_id="repayment_analysis",
            display_name="Repayment Analysis",
            required=True,
            memo_types=["Renewal"],
            facility_types=["Revolver"],
        ),
        SectionDefinition(
            section_id="optional_notes",
            display_name="Optional Notes",
            required=False,
        ),
    ]

    assert [gap.section_id for gap in required_section_gaps([], definitions, "Renewal", "Revolver")] == [
        "repayment_analysis"
    ]
    assert required_section_gaps([], definitions, "Origination", "Revolver") == []
    assert required_section_gaps([], definitions, "Renewal", "Term Loan") == []
    assert required_section_gaps(
        [{"canonical_section_id": "repayment_analysis"}],
        definitions,
        "Renewal",
        "Revolver",
    ) == []
