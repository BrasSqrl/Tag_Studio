from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .app_config import STATUS_LABELS
from .defaults import DEFAULT_OUTCOME_EVENT_TYPES, SCHEMA_VERSION
from .document_intelligence import load_extraction_warnings, load_page_quality, load_page_text, load_section_candidates
from .models import FacilityRecord, SectionDefinition, TagDefinition
from .sectioning import propose_section_candidates, propose_sections, required_section_gaps
from .storage import (
    active_schema_hash,
    append_audit,
    config_path,
    list_memo_ids,
    load_evidence,
    load_facilities,
    load_foreseeability_assessments,
    load_memo_record,
    load_outcome_events,
    load_outcome_summaries,
    load_review,
    load_scoring_rubric,
    load_sections,
    load_table_metrics,
    load_tags,
    memo_dir,
    read_json,
    save_review,
    save_sections,
    slugify,
    write_json,
)

LEARNED_HEADINGS_FILE = "learned_heading_matches.json"


@dataclass(frozen=True)
class MemoBundle:
    memo_id: str
    memo: dict[str, Any]
    review: dict[str, Any]
    sections: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    facilities: list[dict[str, Any]]
    outcome_summaries: list[dict[str, Any]]
    outcome_events: list[dict[str, Any]]
    foreseeability_assessments: list[dict[str, Any]]
    table_metrics: list[dict[str, Any]]
    page_quality: list[dict[str, Any]]
    page_text: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


SECTION_CONFIDENCE_THRESHOLD = 0.8
FACILITY_RELEVANT_SECTION_IDS = {
    "facility_structure",
    "repayment_analysis",
    "collateral",
    "covenants_reporting",
    "guarantor_sponsor",
}


@dataclass(frozen=True)
class SectionReviewItem:
    item_id: str
    queue: str
    title: str
    original_heading: str
    standard_section_id: str = ""
    standard_section_name: str = ""
    suggested_section_id: str = ""
    suggested_section_name: str = ""
    confidence: float = 0.0
    reasons: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    section: dict[str, Any] | None = None
    section_id: str = ""
    missing_section_id: str = ""
    missing_section_name: str = ""
    required: bool = False
    facility_relevant: bool = False
    page_start: int | None = None
    page_end: int | None = None
    text_preview: str = ""


@dataclass(frozen=True)
class SectionReviewSummary:
    must_fix: list[SectionReviewItem]
    can_review_later: list[SectionReviewItem]
    ready: list[SectionReviewItem]
    confidence_threshold: float = SECTION_CONFIDENCE_THRESHOLD

    @property
    def has_blockers(self) -> bool:
        return bool(self.must_fix)


@dataclass(frozen=True)
class SectionCleanupBlock:
    block_id: str
    label: str
    text: str
    page_start: int
    page_end: int
    ordinal: int


def facility_review_rows_to_records(memo_id: str, customer_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("Facility Name") or "").strip()
        if not name:
            continue
        status = str(row.get("Status") or "Confirmed").strip()
        if status not in {"Proposed", "Confirmed", "Rejected"}:
            status = "Confirmed"
        if status == "Proposed":
            status = "Confirmed"
        saved.append(
            FacilityRecord(
                facility_id=slugify(str(row.get("_facility_id") or f"facility_{name}")),
                memo_id=memo_id,
                customer_id=customer_id,
                facility_name=name,
                facility_type=str(row.get("Facility Type") or "Other"),
                amount=str(row.get("Amount") or ""),
                closing_date=str(row.get("Facility Closing Date") or ""),
                source_evidence=str(row.get("Why Suggested") or ""),
                reviewer_confirmed=status == "Confirmed",
                status=status,  # type: ignore[arg-type]
            ).model_dump()
        )
    return saved


def load_section_defs(workspace: Path) -> list[SectionDefinition]:
    return [SectionDefinition(**row) for row in read_json(config_path(workspace, "section_schema.json"), [])]


def save_section_defs(workspace: Path, sections: list[SectionDefinition]) -> None:
    write_json(config_path(workspace, "section_schema.json"), [section.model_dump() for section in sections])
    record_schema_change(workspace, "standard memo sections updated")


def load_tag_defs(workspace: Path) -> list[TagDefinition]:
    return [TagDefinition(**row) for row in read_json(config_path(workspace, "tag_schema.json"), [])]


def save_tag_defs(workspace: Path, tags: list[TagDefinition]) -> None:
    write_json(config_path(workspace, "tag_schema.json"), [tag.model_dump() for tag in tags])
    record_schema_change(workspace, "credit tags updated")


def load_outcome_taxonomy(workspace: Path) -> list[dict[str, Any]]:
    return read_json(config_path(workspace, "outcome_taxonomy.json"), [])


def save_outcome_taxonomy(workspace: Path, records: list[dict[str, Any]]) -> None:
    write_json(config_path(workspace, "outcome_taxonomy.json"), records)
    record_schema_change(workspace, "outcome taxonomy updated")


def save_scoring_rubric_defs(workspace: Path, records: list[dict[str, Any]]) -> None:
    write_json(config_path(workspace, "scoring_rubric.json"), records)
    record_schema_change(workspace, "scoring rubric updated")


def record_schema_change(workspace: Path, reason: str) -> None:
    schema_hash = active_schema_hash(workspace)
    write_json(
        config_path(workspace, "schema_meta.json"),
        {
            "schema_version": SCHEMA_VERSION,
            "schema_hash": schema_hash,
            "updated_at": datetime.now(UTC).isoformat(),
            "reason": reason,
        },
    )
    for memo_id in list_memo_ids(workspace):
        memo = load_memo_record(workspace, memo_id)
        if memo.get("schema_hash") == schema_hash:
            continue
        review = load_review(workspace, memo_id)
        review.update(
            {
                "status": "Needs Revalidation",
                "assignment_status": "Needs Revalidation",
                "schema_version": SCHEMA_VERSION,
                "schema_hash": schema_hash,
            }
        )
        save_review(workspace, memo_id, review)


def section_defs_by_id(workspace: Path) -> dict[str, SectionDefinition]:
    return {section.section_id: section for section in load_section_defs(workspace)}


def accept_section(workspace: Path, memo_id: str, section_id: str) -> bool:
    sections = load_sections(workspace, memo_id)
    updated: list[dict[str, Any]] = []
    accepted = False
    accepted_section: dict[str, Any] = {}
    for section in sections:
        if section.get("section_id") == section_id:
            accepted_section = {**section, "reviewer_confirmed": True}
            updated.append(accepted_section)
            accepted = True
        else:
            updated.append(section)
    if not accepted:
        return False
    save_sections(workspace, memo_id, updated)
    append_audit(
        workspace,
        memo_id,
        "section_accepted",
        {
            "section_id": section_id,
            "standard_section": accepted_section.get("canonical_section_name", ""),
            "original_heading": accepted_section.get("original_header", ""),
        },
    )
    return True


def accept_sections(workspace: Path, memo_id: str, section_ids: list[str]) -> int:
    section_id_set = {section_id for section_id in section_ids if section_id}
    if not section_id_set:
        return 0
    sections = load_sections(workspace, memo_id)
    accepted_count = 0
    updated: list[dict[str, Any]] = []
    for section in sections:
        if section.get("section_id") in section_id_set and not section.get("reviewer_confirmed"):
            section = {**section, "reviewer_confirmed": True}
            accepted_count += 1
        updated.append(section)
    if accepted_count:
        save_sections(workspace, memo_id, updated)
        append_audit(
            workspace,
            memo_id,
            "sections_accepted",
            {"section_count": accepted_count},
        )
    return accepted_count


def load_learned_heading_matches(workspace: Path) -> dict[str, list[str]]:
    raw = read_json(config_path(workspace, LEARNED_HEADINGS_FILE), {})
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, list[str]] = {}
    for section_id, headings in raw.items():
        if not isinstance(headings, list):
            continue
        values = [str(heading).strip() for heading in headings if str(heading).strip()]
        if values:
            cleaned[str(section_id)] = sorted(set(values), key=str.casefold)
    return cleaned


def save_learned_heading_match(workspace: Path, section_id: str, heading: str) -> None:
    heading = " ".join(str(heading or "").split())
    if not section_id or not heading or heading == "Not found in memo":
        return
    learned = load_learned_heading_matches(workspace)
    headings = set(learned.get(section_id, []))
    headings.add(heading)
    learned[section_id] = sorted(headings, key=str.casefold)
    write_json(config_path(workspace, LEARNED_HEADINGS_FILE), learned)


def section_cleanup_blocks(section: dict[str, Any]) -> list[SectionCleanupBlock]:
    text = str(section.get("text", "") or "")
    raw_blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    if len(raw_blocks) <= 1:
        raw_blocks = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_blocks and text.strip():
        raw_blocks = [text.strip()]
    page_start = int(section.get("page_start", 1) or 1)
    page_end = int(section.get("page_end", page_start) or page_start)
    section_id = str(section.get("section_id", "section"))
    return [
        SectionCleanupBlock(
            block_id=f"{section_id}_block_{index:03}",
            label=f"Text block {index}",
            text=block,
            page_start=page_start,
            page_end=page_end,
            ordinal=index,
        )
        for index, block in enumerate(raw_blocks, start=1)
    ]


def _cleanup_history_path(workspace: Path, memo_id: str) -> Path:
    return memo_dir(workspace, memo_id) / "sections" / "section_cleanup_history.json"


def _push_cleanup_snapshot(workspace: Path, memo_id: str, sections: list[dict[str, Any]], action: str) -> None:
    path = _cleanup_history_path(workspace, memo_id)
    history = read_json(path, [])
    if not isinstance(history, list):
        history = []
    history.append({"created_at": datetime.now(UTC).isoformat(), "action": action, "sections": sections})
    write_json(path, history[-20:])


def undo_last_section_cleanup(workspace: Path, memo_id: str) -> bool:
    path = _cleanup_history_path(workspace, memo_id)
    history = read_json(path, [])
    if not history:
        return False
    last = history.pop()
    sections = last.get("sections", [])
    if not isinstance(sections, list):
        return False
    save_sections(workspace, memo_id, sections)
    write_json(path, history)
    append_audit(workspace, memo_id, "section_cleanup_undone", {"restored_at": datetime.now(UTC).isoformat()})
    return True


def _join_cleanup_text(parts: list[str]) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip()).strip()


def apply_section_cleanup(
    workspace: Path,
    memo_id: str,
    section_id: str,
    block_actions: dict[str, dict[str, str]],
    definitions: dict[str, SectionDefinition],
) -> None:
    sections = load_sections(workspace, memo_id)
    section_index = next((idx for idx, section in enumerate(sections) if section.get("section_id") == section_id), -1)
    if section_index < 0:
        return

    _push_cleanup_snapshot(workspace, memo_id, sections, "clean_up_section_text")
    current = sections[section_index]
    blocks = section_cleanup_blocks(current)
    current_text: list[str] = []
    additions_by_section: dict[str, list[str]] = {}
    new_sections: list[dict[str, Any]] = []
    previous_section_id = str(sections[section_index - 1].get("section_id", "")) if section_index > 0 else ""

    for block in blocks:
        action = block_actions.get(block.block_id, {}).get("action", "Keep Here")
        text = block.text.strip()
        if not text:
            continue
        if action == "Move to Another Section":
            target_section_id = block_actions.get(block.block_id, {}).get("target_section_id", "")
            if target_section_id and target_section_id != section_id:
                additions_by_section.setdefault(target_section_id, []).append(text)
            else:
                current_text.append(text)
        elif action == "Start New Section Here":
            standard_id = block_actions.get(block.block_id, {}).get("new_standard_section_id", current.get("canonical_section_id", ""))
            definition = definitions.get(standard_id)
            new_sections.append(
                {
                    **current,
                    "section_id": f"section_{uuid4().hex[:10]}",
                    "canonical_section_id": standard_id,
                    "canonical_section_name": definition.display_name if definition else str(current.get("canonical_section_name", "")),
                    "original_header": definition.display_name if definition else "New section from selected text",
                    "text": text,
                    "line_start": 1,
                    "line_end": max(1, len(text.splitlines())),
                    "reviewer_confirmed": True,
                    "missing_required": False,
                    "section_cleanup_note": "Created from selected text during reviewer cleanup.",
                }
            )
        elif action == "Add to Previous Section" and previous_section_id:
            additions_by_section.setdefault(previous_section_id, []).append(text)
        elif action == "Mark as Duplicate":
            continue
        else:
            current_text.append(text)

    updated_sections: list[dict[str, Any]] = []
    for idx, section in enumerate(sections):
        updated = dict(section)
        if section.get("section_id") == section_id:
            updated["text"] = _join_cleanup_text(current_text)
            updated["line_start"] = 1
            updated["line_end"] = max(1, len(updated["text"].splitlines()))
            updated["reviewer_confirmed"] = True
            updated["section_cleanup_note"] = "Reviewer cleaned up this section text."
        if section.get("section_id") in additions_by_section:
            updated["text"] = _join_cleanup_text([str(updated.get("text", "")), *additions_by_section[str(section.get("section_id"))]])
            updated["line_end"] = max(1, len(updated["text"].splitlines()))
            updated["reviewer_confirmed"] = True
            updated["section_cleanup_note"] = "Reviewer added text from another section."
        updated_sections.append(updated)
        if idx == section_index:
            updated_sections.extend(new_sections)

    save_sections(workspace, memo_id, updated_sections)
    append_audit(
        workspace,
        memo_id,
        "section_text_cleaned_up",
        {"section_id": section_id, "block_count": len(blocks), "new_section_count": len(new_sections)},
    )


def load_memo_bundle(workspace: Path, memo_id: str) -> MemoBundle:
    return MemoBundle(
        memo_id=memo_id,
        memo=load_memo_record(workspace, memo_id),
        review=load_review(workspace, memo_id),
        sections=load_sections(workspace, memo_id),
        tags=load_tags(workspace, memo_id),
        evidence=load_evidence(workspace, memo_id),
        facilities=load_facilities(workspace, memo_id),
        outcome_summaries=load_outcome_summaries(workspace, memo_id),
        outcome_events=load_outcome_events(workspace, memo_id),
        foreseeability_assessments=load_foreseeability_assessments(workspace, memo_id),
        table_metrics=load_table_metrics(workspace, memo_id),
        page_quality=load_page_quality(workspace, memo_id),
        page_text=load_page_text(workspace, memo_id),
        warnings=load_extraction_warnings(workspace, memo_id),
    )


def memo_display_name(workspace: Path, memo_id: str) -> str:
    memo = load_memo_record(workspace, memo_id)
    review = load_review(workspace, memo_id)
    return memo_display_name_from_records(memo, review, memo_id)


def memo_display_name_from_records(memo: dict[str, Any], review: dict[str, Any], memo_id: str) -> str:
    customer = memo.get("customer_id") or Path(memo.get("source_file_name", memo_id)).stem
    status = STATUS_LABELS.get(review.get("status", "Draft"), review.get("status", "Draft"))
    return f"{customer} - {memo.get('memo_type', 'Memo')} - {status}"


def memo_display_labels(workspace: Path, memo_ids: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for memo_id in memo_ids:
        labels[memo_id] = memo_display_name(workspace, memo_id)
    return labels


def text_quality_complete(workspace: Path, memo_id: str) -> bool:
    page_quality = load_page_quality(workspace, memo_id)
    return bool(page_quality) and all(
        record.get("disposition") in {"Corrected", "Reviewed - acceptable", "Not material"}
        or (record.get("status") == "Ready" and record.get("disposition") != "Unable to read")
        for record in page_quality
    )


def outcome_event_severity(event_type: str) -> int:
    severity_lookup = {str(item.get("event_type")): int(item.get("severity_rank", 0)) for item in DEFAULT_OUTCOME_EVENT_TYPES}
    return severity_lookup.get(event_type, 0)


def derive_primary_outcome(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None

    def sort_key(event: dict[str, Any]) -> tuple[int, str]:
        severity = int(event.get("severity_rank") or outcome_event_severity(str(event.get("event_type", ""))))
        return (-severity, str(event.get("event_date") or "9999-12-31"))

    return sorted(events, key=sort_key)[0]


def candidate_for_section(section: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    original_header = str(section.get("original_header", "")).strip().lower()
    page_start = int(section.get("page_start", 1))
    matching = [
        candidate
        for candidate in candidates
        if str(candidate.get("original_heading", "")).strip().lower() == original_header
        and int(candidate.get("page_start", 1)) == page_start
    ]
    if not matching:
        matching = [
            candidate
            for candidate in candidates
            if str(candidate.get("original_heading", "")).strip().lower() == original_header
        ]
    if not matching:
        return None
    return sorted(matching, key=lambda item: float(item.get("confidence", 0)), reverse=True)[0]


def _definition_applies(definition: SectionDefinition, memo_type: str, facility_type: str) -> bool:
    memo_match = not definition.memo_types or memo_type in definition.memo_types
    facility_match = not definition.facility_types or facility_type in definition.facility_types
    return memo_match and facility_match


def _is_facility_relevant(definition: SectionDefinition | None) -> bool:
    if not definition:
        return False
    if definition.section_id in FACILITY_RELEVANT_SECTION_IDS or definition.facility_types:
        return True
    searchable = f"{definition.section_id} {definition.display_name}".lower()
    return any(term in searchable for term in ["facility", "repayment", "collateral", "covenant", "guarantor", "sponsor"])


def _section_text_preview(text: str, limit: int = 600) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _page_quality_for_section(section: dict[str, Any], page_quality: list[dict[str, Any]]) -> list[dict[str, Any]]:
    page_start = int(section.get("page_start", 1))
    page_end = int(section.get("page_end", page_start))
    return [
        record
        for record in page_quality
        if page_start <= int(record.get("page_number", 0) or 0) <= page_end
    ]


def _section_has_text_quality_issue(section: dict[str, Any], page_quality: list[dict[str, Any]]) -> tuple[bool, bool]:
    relevant_pages = _page_quality_for_section(section, page_quality)
    has_warning = any(record.get("status") in {"Needs Review", "Hard to Read", "Possible Handwriting", "Table Heavy"} for record in relevant_pages)
    has_blocker = any(
        record.get("disposition") in {"Unable to read", "Needs escalation"}
        or (record.get("status") in {"Hard to Read", "Possible Handwriting"} and not record.get("reviewer_confirmed"))
        for record in relevant_pages
    )
    return has_warning, has_blocker


def _section_has_suspicious_boundary(section: dict[str, Any]) -> bool:
    text = str(section.get("text", "") or "")
    line_count = len([line for line in text.splitlines() if line.strip()])
    text_length = len(text.strip())
    if section.get("missing_required"):
        return False
    return text_length < 120 or line_count > 180 or text_length > 12000


def _review_item_queue(
    reason_codes: list[str],
    *,
    required: bool,
    facility_relevant: bool,
) -> str:
    blocking_codes = {"no_standard_section", "missing_required_section"}
    required_sensitive_codes = {"low_confidence_match", "no_match", "duplicate_standard_section", "blocking_text_quality"}
    if any(code in blocking_codes for code in reason_codes):
        return "must_fix"
    if (required or facility_relevant) and any(code in required_sensitive_codes for code in reason_codes):
        return "must_fix"
    if reason_codes:
        return "can_review_later"
    return "ready"


def classify_section_review(
    workspace: Path,
    memo_id: str,
    confidence_threshold: float = SECTION_CONFIDENCE_THRESHOLD,
) -> SectionReviewSummary:
    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    definitions_list = load_section_defs(workspace)
    definitions = {definition.section_id: definition for definition in definitions_list}
    candidates = load_section_candidates(workspace, memo_id)
    page_quality = load_page_quality(workspace, memo_id)
    memo_type = str(memo.get("memo_type", ""))
    facility_type = str(memo.get("facility_type", ""))
    required_gaps = required_section_gaps(sections, definitions_list, memo_type, facility_type)
    duplicate_counts: dict[str, int] = {}
    for section in sections:
        if section.get("missing_required"):
            continue
        canonical_id = str(section.get("canonical_section_id", ""))
        duplicate_counts[canonical_id] = duplicate_counts.get(canonical_id, 0) + 1

    grouped: dict[str, list[SectionReviewItem]] = {"must_fix": [], "can_review_later": [], "ready": []}
    for gap in required_gaps:
        facility_relevant = _is_facility_relevant(gap)
        item = SectionReviewItem(
            item_id=f"missing_{gap.section_id}",
            queue="must_fix",
            title=f"{gap.display_name} is required and was not found.",
            original_heading="Not found in memo",
            standard_section_id=gap.section_id,
            standard_section_name=gap.display_name,
            missing_section_id=gap.section_id,
            missing_section_name=gap.display_name,
            reasons=(f"{gap.display_name} is required for this memo and was not found.",),
            reason_codes=("missing_required_section",),
            required=True,
            facility_relevant=facility_relevant,
        )
        grouped["must_fix"].append(item)

    for section in sections:
        canonical_id = str(section.get("canonical_section_id", ""))
        definition = definitions.get(canonical_id)
        applies = _definition_applies(definition, memo_type, facility_type) if definition else False
        required = bool(definition.required and applies) if definition else False
        facility_relevant = _is_facility_relevant(definition)
        candidate = candidate_for_section(section, candidates)
        confidence = float(candidate.get("confidence", 0)) if candidate else (1.0 if section.get("reviewer_confirmed") else 0.0)
        suggested_id = str(candidate.get("suggested_section_id", "")) if candidate else canonical_id
        suggested_name = str(candidate.get("suggested_section_name", "")) if candidate else str(section.get("canonical_section_name", ""))
        reasons: list[str] = []
        reason_codes: list[str] = []

        if not definition:
            reason_codes.append("no_standard_section")
            reasons.append("No Standard Memo Section is selected for this detected section.")
        if section.get("missing_required") and not section.get("reviewer_confirmed"):
            reason_codes.append("missing_required_section")
            reasons.append(f"{section.get('canonical_section_name', 'Required section')} still needs a missing-section decision.")
        if not section.get("reviewer_confirmed") and not candidate and not section.get("missing_required"):
            reason_codes.append("no_match")
            reasons.append("Tag Studio did not find a reliable standard section match.")
        if not section.get("reviewer_confirmed") and candidate and confidence < confidence_threshold:
            reason_codes.append("low_confidence_match")
            reasons.append(f"Suggested match confidence is {int(confidence * 100)}%, below the {int(confidence_threshold * 100)}% review threshold.")
        if not section.get("reviewer_confirmed") and duplicate_counts.get(canonical_id, 0) > 1 and canonical_id:
            reason_codes.append("duplicate_standard_section")
            reasons.append(f"More than one detected section maps to {section.get('canonical_section_name', canonical_id)}.")
        if _section_has_suspicious_boundary(section):
            reason_codes.append("suspicious_boundary")
            reasons.append("The section length looks unusual and may need a boundary check.")
        has_text_warning, has_text_blocker = _section_has_text_quality_issue(section, page_quality)
        if has_text_blocker:
            reason_codes.append("blocking_text_quality")
            reasons.append("One or more pages in this section still have unresolved text-quality issues.")
        elif has_text_warning:
            reason_codes.append("text_quality_warning")
            reasons.append("One or more pages in this section had text-quality warnings.")

        queue = _review_item_queue(reason_codes, required=required, facility_relevant=facility_relevant)
        item = SectionReviewItem(
            item_id=str(section.get("section_id", "")),
            queue=queue,
            title=str(section.get("original_header") or section.get("canonical_section_name") or "Detected section"),
            original_heading=str(section.get("original_header") or "Unlabeled section"),
            standard_section_id=canonical_id,
            standard_section_name=str(section.get("canonical_section_name") or (definition.display_name if definition else "")),
            suggested_section_id=suggested_id,
            suggested_section_name=suggested_name,
            confidence=confidence,
            reasons=tuple(reasons),
            reason_codes=tuple(reason_codes),
            section=section,
            section_id=str(section.get("section_id", "")),
            required=required,
            facility_relevant=facility_relevant,
            page_start=int(section.get("page_start", 1)),
            page_end=int(section.get("page_end", section.get("page_start", 1))),
            text_preview=_section_text_preview(str(section.get("text", ""))),
        )
        grouped[queue].append(item)

    return SectionReviewSummary(
        must_fix=grouped["must_fix"],
        can_review_later=grouped["can_review_later"],
        ready=grouped["ready"],
        confidence_threshold=confidence_threshold,
    )


def rebuild_sections_from_page_text(workspace: Path, memo_id: str, extraction_method: str) -> None:
    pages = load_page_text(workspace, memo_id)
    definitions = load_section_defs(workspace)
    learned_headings = load_learned_heading_matches(workspace)
    proposed = propose_sections(
        memo_id=memo_id,
        pages=pages,
        definitions=definitions,
        extraction_method=extraction_method,
        learned_headings=learned_headings,
    )
    save_sections(workspace, memo_id, [section.model_dump() for section in proposed])
    candidates = propose_section_candidates(memo_id, pages, definitions, learned_headings=learned_headings)
    write_json(memo_dir(workspace, memo_id) / "sections" / "section_candidates.json", [candidate.model_dump() for candidate in candidates])


def step_summary(workspace: Path, memo_id: str | None) -> dict[str, str]:
    if not memo_id:
        return {
            "Add Memo": "Needs Review",
            "Review Text Quality": "Not Started",
            "Review Memo Sections": "Not Started",
            "Set Up Facilities": "Not Started",
            "Tag Credit Review": "Not Started",
            "Tag Outcomes": "Not Started",
            "Quality Check": "Not Started",
            "Download Results": "Not Started",
        }

    sections = load_sections(workspace, memo_id)
    review = load_review(workspace, memo_id)

    quality_complete = text_quality_complete(workspace, memo_id)
    section_review = classify_section_review(workspace, memo_id) if sections else SectionReviewSummary([], [], [])
    sections_accepted = bool(sections) and all(section.get("reviewer_confirmed") for section in sections)
    sections_complete = bool(sections) and quality_complete and not section_review.has_blockers and sections_accepted
    facilities = load_facilities(workspace, memo_id)
    outcome_summaries = load_outcome_summaries(workspace, memo_id)
    confirmed_facilities = [facility for facility in facilities if facility.get("status") == "Confirmed" or facility.get("reviewer_confirmed")]
    tags_complete = not quality_findings(workspace, memo_id)[0]
    approved = review.get("status") == "Approved Gold"
    exported = review.get("status") == "Exported"

    return {
        "Add Memo": "Complete",
        "Review Text Quality": "Complete" if quality_complete else "Needs Review",
        "Review Memo Sections": "Complete" if sections_complete else ("Needs Review" if quality_complete else "Not Started"),
        "Set Up Facilities": "Complete" if confirmed_facilities else ("Needs Review" if sections_complete else "Not Started"),
        "Tag Credit Review": "Complete" if tags_complete else ("Needs Review" if confirmed_facilities else "Not Started"),
        "Tag Outcomes": "Complete" if outcome_summaries else ("Needs Review" if confirmed_facilities else "Not Started"),
        "Quality Check": "Complete" if approved else ("Needs Review" if tags_complete else "Not Started"),
        "Download Results": "Complete" if exported else ("Needs Review" if approved else "Not Started"),
    }


def tags_for_section(workspace: Path, section: dict[str, Any]) -> list[TagDefinition]:
    tag_defs = load_tag_defs(workspace)
    sections_by_id = section_defs_by_id(workspace)
    fallback = SectionDefinition(section_id="unknown", display_name="Unknown")
    expected_ids = set(sections_by_id.get(section.get("canonical_section_id"), fallback).expected_tag_ids)
    relevant = [tag for tag in tag_defs if tag.tag_id in expected_ids]
    return relevant or tag_defs


def quality_findings(workspace: Path, memo_id: str) -> tuple[list[str], dict[str, int]]:
    findings: list[str] = []
    sections = load_sections(workspace, memo_id)
    section_defs = load_section_defs(workspace)
    tags = load_tags(workspace, memo_id)
    evidence = load_evidence(workspace, memo_id)
    page_quality = load_page_quality(workspace, memo_id)
    warnings = load_extraction_warnings(workspace, memo_id)
    facilities = load_facilities(workspace, memo_id)
    outcome_summaries = load_outcome_summaries(workspace, memo_id)
    outcome_events = load_outcome_events(workspace, memo_id)
    foreseeability_assessments = load_foreseeability_assessments(workspace, memo_id)
    if not page_quality:
        findings.append("Text quality has not been reviewed.")
    else:
        unreviewed_pages = [
            record
            for record in page_quality
            if record.get("status") != "Ready" and not record.get("reviewer_confirmed")
        ]
        hard_pages = [record for record in unreviewed_pages if record.get("status") == "Hard to Read"]
        handwriting_pages = [record for record in unreviewed_pages if record.get("status") == "Possible Handwriting"]
        if hard_pages:
            findings.append("Hard-to-read pages still need review: " + ", ".join(f"p.{record.get('page_number')}" for record in hard_pages))
        elif unreviewed_pages:
            findings.append(f"{len(unreviewed_pages)} page(s) still need text quality review.")
        if handwriting_pages:
            findings.append("Possible handwritten or scribbled content needs human review: " + ", ".join(f"p.{record.get('page_number')}" for record in handwriting_pages))
        unresolved_dispositions = [
            record
            for record in page_quality
            if record.get("disposition", "Unresolved") == "Unresolved" and record.get("status") != "Ready"
        ]
        unusable_without_rationale = [
            record
            for record in page_quality
            if record.get("disposition") == "Unable to read" and not str(record.get("disposition_rationale", "")).strip()
        ]
        blocking_dispositions = [record for record in page_quality if record.get("disposition") == "Needs escalation"]
        if unresolved_dispositions:
            findings.append(f"{len(unresolved_dispositions)} page(s) still need a text quality disposition.")
        if unusable_without_rationale:
            findings.append("Unable-to-read pages require approver rationale before approval.")
        if blocking_dispositions:
            findings.append("Pages marked Needs escalation must be resolved before approval.")

    unreviewed_warning_pages = {
        int(record.get("page_number"))
        for record in page_quality
        if record.get("page_number") and record.get("status") != "Ready" and not record.get("reviewer_confirmed")
    }
    unreviewed_warnings = [
        warning
        for warning in warnings
        if not warning.get("resolved")
        and (
            not warning.get("page_number")
            or int(warning.get("page_number")) in unreviewed_warning_pages
        )
        and unreviewed_warning_pages
    ]
    if unreviewed_warnings:
        findings.append(f"{len(unreviewed_warnings)} text reading warning(s) still need review.")

    unresolved_warnings = [warning for warning in warnings if not warning.get("resolved")]
    if unresolved_warnings:
        findings.append(f"{len(unresolved_warnings)} extraction warning(s) still need final disposition.")

    section_review = classify_section_review(workspace, memo_id) if sections else SectionReviewSummary([], [], [])
    if section_review.must_fix:
        findings.append(
            "Section review has unresolved required item(s): "
            + "; ".join(item.title for item in section_review.must_fix[:6])
        )

    confirmed_facilities = [facility for facility in facilities if facility.get("status") == "Confirmed" or facility.get("reviewer_confirmed")]
    if not confirmed_facilities:
        findings.append("At least one facility must be confirmed before approval.")

    summary_by_facility = {str(summary.get("facility_id", "")): summary for summary in outcome_summaries}
    events_by_facility: dict[str, list[dict[str, Any]]] = {}
    for event in outcome_events:
        events_by_facility.setdefault(str(event.get("facility_id", "")), []).append(event)
    assessments_by_event = {str(assessment.get("outcome_event_id", "")): assessment for assessment in foreseeability_assessments}
    if confirmed_facilities and not outcome_summaries:
        findings.append("Outcome tagging must be completed for each confirmed facility.")

    for facility in confirmed_facilities:
        facility_id = str(facility.get("facility_id", ""))
        facility_name = str(facility.get("facility_name") or facility_id)
        summary = summary_by_facility.get(facility_id)
        if not summary:
            findings.append(f"{facility_name} needs an outcome availability state.")
            continue
        state = str(summary.get("outcome_availability_state") or "Outcome Not Checked")
        if state == "Outcome Not Checked":
            findings.append(f"{facility_name} outcome is not checked.")
        if state in {"Known Outcome", "Not Seasoned Yet", "No Adverse Outcome Observed"} and not str(facility.get("closing_date", "")).strip():
            findings.append(f"{facility_name} needs a facility closing date for outcome seasoning.")
        if state == "Outcome Data Unavailable" and not str(summary.get("source_note", "")).strip():
            findings.append(f"{facility_name} outcome data unavailable needs a source note.")
        if state == "No Adverse Outcome Observed":
            if not summary.get("source_type"):
                findings.append(f"{facility_name} no-adverse outcome needs an outcome source type.")
            if not summary.get("source_checked_date"):
                findings.append(f"{facility_name} no-adverse outcome needs a source checked date.")
            if (
                summary.get("source_type") in {"Reviewer attestation", "Other"}
                or summary.get("source_confidence") == "Low"
            ) and not str(summary.get("source_note", "")).strip():
                findings.append(f"{facility_name} no-adverse outcome needs a source note.")
        if state != "Known Outcome":
            continue

        facility_events = events_by_facility.get(facility_id, [])
        if not facility_events:
            findings.append(f"{facility_name} is marked Known Outcome but has no adverse outcome events.")
            continue
        for event in facility_events:
            event_label = str(event.get("event_type") or "Outcome event")
            if not event.get("event_type"):
                findings.append(f"{facility_name} has an outcome event without an event type.")
            if not event.get("event_date"):
                findings.append(f"{facility_name} {event_label} needs an event date.")
            if not event.get("source_type"):
                findings.append(f"{facility_name} {event_label} needs a source type.")
            if not event.get("source_checked_date"):
                findings.append(f"{facility_name} {event_label} needs a source checked date.")
            if (
                event.get("source_type") in {"Reviewer attestation", "Other"}
                or event.get("source_confidence") == "Low"
            ) and not str(event.get("source_note", "")).strip():
                findings.append(f"{facility_name} {event_label} needs a source note.")

        primary = derive_primary_outcome(facility_events)
        if not primary:
            continue
        primary_event_id = str(primary.get("outcome_event_id", ""))
        assessment = assessments_by_event.get(primary_event_id)
        if not assessment:
            findings.append(f"{facility_name} primary adverse outcome needs a foreseeability assessment.")
            continue
        foreseeability = str(assessment.get("foreseeability") or "Not assessed")
        if foreseeability == "Not assessed":
            findings.append(f"{facility_name} primary adverse outcome foreseeability is not assessed.")
        if foreseeability in {"Visible in memo", "Partially visible"} and not assessment.get("memo_evidence_ids"):
            findings.append(f"{facility_name} {foreseeability} needs linked memo evidence.")

    if not tags:
        findings.append("No credit tags have been saved yet.")

    section_ids_with_tags = {tag.get("section_id") for tag in tags}
    untagged_sections = [
        section
        for section in sections
        if not section.get("missing_required") and section.get("section_id") not in section_ids_with_tags
    ]
    if untagged_sections:
        findings.append(f"{len(untagged_sections)} confirmed section(s) do not have saved tags.")

    evidence_ids = {item.get("evidence_id") for item in evidence}
    memo_evidence_ids = {item.get("evidence_id") for item in evidence if item.get("evidence_type", "memo_evidence") == "memo_evidence"}
    for assessment in foreseeability_assessments:
        missing_memo_evidence = [item for item in assessment.get("memo_evidence_ids", []) if item not in memo_evidence_ids]
        if missing_memo_evidence:
            findings.append("Foreseeability assessment has missing memo evidence links.")
    tag_defs = {definition.tag_id: definition for definition in load_tag_defs(workspace)}
    section_defs_by_key = {definition.section_id: definition for definition in section_defs}
    missing_required_tags: list[str] = []
    for section in sections:
        if section.get("missing_required"):
            continue
        definition = section_defs_by_key.get(section.get("canonical_section_id"))
        if not definition:
            continue
        saved_tag_ids = {
            tag.get("tag_id")
            for tag in tags
            if tag.get("section_id") == section.get("section_id")
        }
        for expected_tag_id in definition.expected_tag_ids:
            tag_definition = tag_defs.get(expected_tag_id)
            if tag_definition and tag_definition.required and expected_tag_id not in saved_tag_ids:
                missing_required_tags.append(f"{section.get('canonical_section_name')}: {tag_definition.label}")
    if missing_required_tags:
        sample = "; ".join(missing_required_tags[:8])
        suffix = f" and {len(missing_required_tags) - 8} more" if len(missing_required_tags) > 8 else ""
        findings.append(f"Missing required tags: {sample}{suffix}.")

    for tag in tags:
        definition = tag_defs.get(tag.get("tag_id"))
        if definition and definition.evidence_required and tag.get("value") not in {"Not addressed in memo", "Not applicable"} and not tag.get("evidence_ids"):
            findings.append(f"{tag.get('tag_label')} needs evidence.")
        if definition and definition.facility_required and confirmed_facilities and not tag.get("facility_id"):
            findings.append(f"{tag.get('tag_label')} needs a facility assignment.")
        missing = [item for item in tag.get("evidence_ids", []) if item not in evidence_ids]
        if missing:
            findings.append(f"{tag.get('tag_label')} has missing evidence links.")

    metrics = {
        "pages_total": len(page_quality),
        "pages_checked": len([record for record in page_quality if record.get("status") == "Ready" or record.get("reviewer_confirmed")]),
        "pages_need_review": len([record for record in page_quality if record.get("status") != "Ready" and not record.get("reviewer_confirmed")]),
        "sections_total": len(sections),
        "sections_confirmed": len([section for section in sections if section.get("reviewer_confirmed")]),
        "tags_total": len(tags),
        "evidence_total": len(evidence),
        "facilities_total": len(facilities),
        "facilities_confirmed": len(confirmed_facilities),
        "outcomes_total": len(outcome_summaries),
        "outcome_events_total": len(outcome_events),
        "foreseeability_total": len(foreseeability_assessments),
    }
    return findings, metrics


def schema_usage_warnings(
    workspace: Path,
    previous_sections: list[SectionDefinition],
    previous_tags: list[TagDefinition],
    new_sections: list[SectionDefinition] | None,
    new_tags: list[TagDefinition] | None,
) -> list[str]:
    warnings: list[str] = []
    if new_sections is not None:
        removed_sections = {section.section_id for section in previous_sections} - {section.section_id for section in new_sections}
        if removed_sections:
            used_sections: set[str] = set()
            for memo_id in list_memo_ids(workspace):
                used_sections.update(str(section.get("canonical_section_id", "")) for section in load_sections(workspace, memo_id))
            affected = sorted(removed_sections & used_sections)
            if affected:
                warnings.append(
                    "Removed section ID(s) are already used in saved memo records: "
                    + ", ".join(affected)
                    + ". Keep stable IDs whenever possible."
                )
    if new_tags is not None:
        removed_tags = {tag.tag_id for tag in previous_tags} - {tag.tag_id for tag in new_tags}
        if removed_tags:
            used_tags: set[str] = set()
            for memo_id in list_memo_ids(workspace):
                used_tags.update(str(tag.get("tag_id", "")) for tag in load_tags(workspace, memo_id))
            affected = sorted(removed_tags & used_tags)
            if affected:
                warnings.append(
                    "Removed tag ID(s) are already used in saved memo records: "
                    + ", ".join(affected)
                    + ". Existing tags remain stored, but comparability is cleaner when IDs stay stable."
                )
    return warnings


class MemoReadService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def bundle(self, memo_id: str) -> MemoBundle:
        return load_memo_bundle(self.workspace, memo_id)

    def display_labels(self, memo_ids: list[str]) -> dict[str, str]:
        return memo_display_labels(self.workspace, memo_ids)


class WorkflowService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def step_summary(self, memo_id: str | None) -> dict[str, str]:
        return step_summary(self.workspace, memo_id)

    def quality_findings(self, memo_id: str) -> tuple[list[str], dict[str, int]]:
        return quality_findings(self.workspace, memo_id)


class TagSetupService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def load_sections(self) -> list[SectionDefinition]:
        return load_section_defs(self.workspace)

    def save_sections(self, sections: list[SectionDefinition]) -> None:
        save_section_defs(self.workspace, sections)

    def load_tags(self) -> list[TagDefinition]:
        return load_tag_defs(self.workspace)

    def save_tags(self, tags: list[TagDefinition]) -> None:
        save_tag_defs(self.workspace, tags)

    def load_outcomes(self) -> list[dict[str, Any]]:
        return load_outcome_taxonomy(self.workspace)

    def save_outcomes(self, records: list[dict[str, Any]]) -> None:
        save_outcome_taxonomy(self.workspace, records)

    def load_scoring(self) -> list[dict[str, Any]]:
        return load_scoring_rubric(self.workspace)

    def save_scoring(self, records: list[dict[str, Any]]) -> None:
        save_scoring_rubric_defs(self.workspace, records)
