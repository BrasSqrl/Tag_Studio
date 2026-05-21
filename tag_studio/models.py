from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ReviewStatus = Literal[
    "Draft",
    "Ready for Review",
    "Changes Requested",
    "Approved Gold",
    "Exported",
    "Needs Revalidation",
]
ExtractionMethod = Literal["local_pdf_text", "local_ocr", "aws_textract_optional", "manual_correction"]
PageQualityStatus = Literal["Ready", "Needs Review", "Hard to Read", "Possible Handwriting", "Table Heavy"]
PageDisposition = Literal[
    "Unresolved",
    "Corrected",
    "Reviewed - acceptable",
    "Not material",
    "Unable to read",
    "Needs escalation",
]
LayoutBlockType = Literal["heading", "paragraph", "table", "handwritten_note", "footer", "signature", "unknown"]
TagScope = Literal["memo", "borrower", "facility", "section", "outcome"]
EvidenceType = Literal["memo_evidence", "outcome_source_evidence"]
OutcomeAvailabilityState = Literal[
    "Known Outcome",
    "Not Seasoned Yet",
    "Outcome Data Unavailable",
    "Outcome Not Checked",
    "No Adverse Outcome Observed",
]
OutcomeSourceType = Literal[
    "Servicing system",
    "Risk rating system",
    "Watchlist / criticized report",
    "Workout system",
    "Covenant tracking system",
    "Credit file",
    "Loan review report",
    "Reviewer attestation",
    "Other",
]
ForeseeabilityValue = Literal["Visible in memo", "Partially visible", "Hindsight-only", "Not assessed", "N/A"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SectionDefinition(BaseModel):
    section_id: str
    display_name: str
    description: str = ""
    required: bool = True
    memo_types: list[str] = Field(default_factory=list)
    facility_types: list[str] = Field(default_factory=list)
    expected_tag_ids: list[str] = Field(default_factory=list)
    evidence_required: bool = True
    aliases: list[str] = Field(default_factory=list)
    display_order: int = 100
    schema_version: str = ""


class TagDefinition(BaseModel):
    tag_id: str
    label: str
    category: str
    data_type: Literal["text", "long_text", "enum", "multi_select", "number", "boolean"] = "text"
    allowed_values: list[str] = Field(default_factory=list)
    required: bool = False
    evidence_required: bool = False
    material: bool = False
    allowed_scopes: list[TagScope] = Field(default_factory=lambda: ["section"])
    default_scope: TagScope = "section"
    facility_required: bool = False
    scoring_use: str = ""
    export_use: Literal["section", "memo", "both", "none"] = "both"
    help_text: str = ""
    schema_version: str = ""


class MemoRecord(BaseModel):
    memo_id: str
    source_file_name: str
    source_hash: str
    memo_type: str = "Renewal"
    facility_type: str = "Multiple"
    customer_id: str = ""
    reviewer: str = ""
    extraction_method: ExtractionMethod = "local_pdf_text"
    schema_version: str = ""
    schema_hash: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class PageText(BaseModel):
    page_number: int
    text: str
    extraction_method: ExtractionMethod
    extraction_confidence: float | None = None
    original_text: str = ""
    corrected_text: str = ""
    source_text_version: str = "extracted"


class PageQualityRecord(BaseModel):
    memo_id: str
    page_number: int
    status: PageQualityStatus
    text_quality_score: float
    extraction_method: ExtractionMethod
    flags: list[str] = Field(default_factory=list)
    reviewer_confirmed: bool = False
    reviewer_notes: str = ""
    disposition: PageDisposition = "Unresolved"
    disposition_rationale: str = ""


class LayoutBlockRecord(BaseModel):
    block_id: str
    memo_id: str
    page_number: int
    block_type: LayoutBlockType = "unknown"
    text: str = ""
    bbox: list[float] = Field(default_factory=list)
    confidence: float | None = None
    source: str = "local"
    reading_order: int = 0


class SectionCandidateRecord(BaseModel):
    candidate_id: str
    memo_id: str
    original_heading: str
    suggested_section_id: str
    suggested_section_name: str
    confidence: float
    alternate_matches: list[dict[str, Any]] = Field(default_factory=list)
    page_start: int
    page_end: int
    line_index: int = 0
    reason: str = ""


class ExtractionWarningRecord(BaseModel):
    warning_id: str
    memo_id: str
    page_number: int | None = None
    severity: Literal["Info", "Review", "Blocking"] = "Review"
    message: str
    action: str = ""
    resolved: bool = False


class SectionRecord(BaseModel):
    section_id: str
    memo_id: str
    canonical_section_id: str
    canonical_section_name: str
    original_header: str
    page_start: int
    page_end: int
    line_start: int = 1
    line_end: int = 1
    text: str
    extraction_method: ExtractionMethod
    reviewer_confirmed: bool = False
    missing_required: bool = False


class EvidenceRecord(BaseModel):
    evidence_id: str
    memo_id: str
    section_id: str
    evidence_type: EvidenceType = "memo_evidence"
    tag_record_ids: list[str] = Field(default_factory=list)
    facility_ids: list[str] = Field(default_factory=list)
    outcome_event_ids: list[str] = Field(default_factory=list)
    foreseeability_ids: list[str] = Field(default_factory=list)
    page_number: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    selected_text: str
    corrected_text_used: bool = False
    original_text: str = ""
    source_text_version: str = "extracted"
    source_location: str = ""
    evidence_role: str = "supporting_fact"
    citation_confidence: Literal["High", "Medium", "Low"] = "Medium"
    source_document_hash: str = ""
    source_type: OutcomeSourceType | None = None
    source_checked_date: str = ""
    source_confidence: Literal["High", "Medium", "Low"] = "Medium"
    source_note: str = ""
    source_document_reference: str = ""
    created_at: str = Field(default_factory=utc_now)


class TagRecord(BaseModel):
    tag_record_id: str
    memo_id: str
    section_id: str
    scope: TagScope = "section"
    facility_id: str = ""
    customer_id: str = ""
    outcome_id: str = ""
    tag_id: str
    tag_label: str
    value: Any
    confidence: Literal["High", "Medium", "Low"] = "Medium"
    evidence_ids: list[str] = Field(default_factory=list)
    tagger: str = ""
    status: Literal["Draft", "Submitted", "Approved", "Corrected"] = "Draft"
    adjudicator_notes: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ReviewRecord(BaseModel):
    memo_id: str
    status: ReviewStatus = "Draft"
    reviewer: str = ""
    assigned_to: str = ""
    assignment_status: Literal[
        "Unassigned",
        "Assigned to reviewer",
        "In review",
        "Ready for approval",
        "Approved for Training Dataset",
        "Needs Revalidation",
    ] = "Unassigned"
    adjudicator: str = ""
    adjudication_notes: str = ""
    approved_at: str | None = None
    schema_version: str = ""
    schema_hash: str = ""
    updated_at: str = Field(default_factory=utc_now)


class FacilityRecord(BaseModel):
    facility_id: str
    memo_id: str
    customer_id: str = ""
    facility_name: str
    facility_type: str
    amount: str = ""
    closing_date: str = ""
    proposed_from_text: bool = False
    confidence: float = 0.0
    source_section_id: str = ""
    source_evidence: str = ""
    reviewer_confirmed: bool = False
    status: Literal["Proposed", "Confirmed", "Rejected"] = "Proposed"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class FacilityOutcomeSummaryRecord(BaseModel):
    outcome_summary_id: str
    memo_id: str
    customer_id: str = ""
    facility_id: str = ""
    outcome_availability_state: OutcomeAvailabilityState = "Outcome Not Checked"
    seasoning_months: int = 12
    primary_adverse_outcome: str = ""
    primary_outcome_event_id: str = ""
    primary_event_date: str = ""
    primary_severity_rank: int = 0
    no_adverse_outcome_observed_date: str = ""
    source_type: OutcomeSourceType | None = None
    source_checked_date: str = ""
    source_confidence: Literal["High", "Medium", "Low"] = "Medium"
    source_note: str = ""
    approval_ready: bool = False
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class OutcomeEventRecord(BaseModel):
    outcome_event_id: str
    memo_id: str
    facility_id: str = ""
    event_type: str
    event_date: str = ""
    severity_rank: int = 0
    source_type: OutcomeSourceType | None = None
    source_checked_date: str = ""
    source_confidence: Literal["High", "Medium", "Low"] = "Medium"
    source_note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ForeseeabilityAssessmentRecord(BaseModel):
    foreseeability_id: str
    memo_id: str
    facility_id: str = ""
    outcome_event_id: str = ""
    foreseeability: ForeseeabilityValue = "Not assessed"
    memo_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class TableMetricRecord(BaseModel):
    metric_id: str
    memo_id: str
    section_id: str = ""
    facility_id: str = ""
    metric_name: str
    period: str = ""
    reported_value: str = ""
    adjusted_value: str = ""
    source_table: str = ""
    confidence: Literal["High", "Medium", "Low"] = "Medium"
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class ScoringRubricRecord(BaseModel):
    score_name: str
    component_tag_id: str
    weight: float = 0.0
    directionality: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    min_value: float = 0.0
    max_value: float = 100.0
    required_evidence: bool = True
    memo_types: list[str] = Field(default_factory=list)
    facility_types: list[str] = Field(default_factory=list)
    active: bool = True
    version: str = ""


class SchemaSnapshotRecord(BaseModel):
    schema_version: str
    schema_hash: str
    created_at: str = Field(default_factory=utc_now)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)
    facility_types: list[dict[str, Any]] = Field(default_factory=list)
    outcome_taxonomy: list[dict[str, Any]] = Field(default_factory=list)
    scoring_rubric: list[dict[str, Any]] = Field(default_factory=list)


class ExportManifest(BaseModel):
    export_id: str
    memo_ids: list[str]
    include_only_approved: bool = True
    schema_version: str
    schema_hash: str = ""
    include_legacy_approved: bool = False
    created_at: str = Field(default_factory=utc_now)
