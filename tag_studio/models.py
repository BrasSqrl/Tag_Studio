from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ReviewStatus = Literal["Draft", "Ready for Review", "Changes Requested", "Approved Gold", "Exported"]
ExtractionMethod = Literal["local_pdf_text", "local_ocr", "aws_textract_optional", "manual_correction"]
PageQualityStatus = Literal["Ready", "Needs Review", "Hard to Read", "Possible Handwriting", "Table Heavy"]
LayoutBlockType = Literal["heading", "paragraph", "table", "handwritten_note", "footer", "signature", "unknown"]


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


class TagDefinition(BaseModel):
    tag_id: str
    label: str
    category: str
    data_type: Literal["text", "long_text", "enum", "multi_select", "number", "boolean"] = "text"
    allowed_values: list[str] = Field(default_factory=list)
    required: bool = False
    evidence_required: bool = False
    scoring_use: str = ""
    export_use: Literal["section", "memo", "both", "none"] = "both"
    help_text: str = ""


class MemoRecord(BaseModel):
    memo_id: str
    source_file_name: str
    source_hash: str
    memo_type: str = "Renewal"
    facility_type: str = "Multiple"
    borrower_name_or_hash: str = ""
    reviewer: str = ""
    extraction_method: ExtractionMethod = "local_pdf_text"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class PageText(BaseModel):
    page_number: int
    text: str
    extraction_method: ExtractionMethod
    extraction_confidence: float | None = None


class PageQualityRecord(BaseModel):
    memo_id: str
    page_number: int
    status: PageQualityStatus
    text_quality_score: float
    extraction_method: ExtractionMethod
    flags: list[str] = Field(default_factory=list)
    reviewer_confirmed: bool = False
    reviewer_notes: str = ""


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
    text: str
    extraction_method: ExtractionMethod
    reviewer_confirmed: bool = False
    missing_required: bool = False


class EvidenceRecord(BaseModel):
    evidence_id: str
    memo_id: str
    section_id: str
    page_number: int | None = None
    selected_text: str
    source_location: str = ""
    evidence_role: str = "supporting_fact"
    citation_confidence: Literal["High", "Medium", "Low"] = "Medium"
    source_document_hash: str
    created_at: str = Field(default_factory=utc_now)


class TagRecord(BaseModel):
    tag_record_id: str
    memo_id: str
    section_id: str
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
    adjudicator: str = ""
    adjudication_notes: str = ""
    approved_at: str | None = None
    updated_at: str = Field(default_factory=utc_now)


class ExportManifest(BaseModel):
    export_id: str
    memo_ids: list[str]
    include_only_approved: bool = True
    schema_version: str
    created_at: str = Field(default_factory=utc_now)
