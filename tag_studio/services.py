from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .app_config import STATUS_LABELS
from .defaults import SCHEMA_VERSION
from .document_intelligence import load_extraction_warnings, load_page_quality, load_page_text
from .models import MemoLockRecord, SectionDefinition, TagDefinition
from .sectioning import propose_section_candidates, propose_sections, required_section_gaps
from .storage import (
    active_schema_hash,
    config_path,
    list_memo_ids,
    load_active_lock,
    load_evidence,
    load_facilities,
    load_memo_record,
    load_outcomes,
    load_review,
    load_scoring_rubric,
    load_sections,
    load_table_metrics,
    load_tags,
    memo_dir,
    read_json,
    save_active_lock,
    save_review,
    save_sections,
    write_json,
)


@dataclass(frozen=True)
class MemoBundle:
    memo_id: str
    memo: dict[str, Any]
    review: dict[str, Any]
    sections: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    facilities: list[dict[str, Any]]
    outcomes: list[dict[str, Any]]
    table_metrics: list[dict[str, Any]]
    page_quality: list[dict[str, Any]]
    page_text: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


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


def load_memo_bundle(workspace: Path, memo_id: str) -> MemoBundle:
    return MemoBundle(
        memo_id=memo_id,
        memo=load_memo_record(workspace, memo_id),
        review=load_review(workspace, memo_id),
        sections=load_sections(workspace, memo_id),
        tags=load_tags(workspace, memo_id),
        evidence=load_evidence(workspace, memo_id),
        facilities=load_facilities(workspace, memo_id),
        outcomes=load_outcomes(workspace, memo_id),
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
    borrower = memo.get("borrower_name_or_hash") or Path(memo.get("source_file_name", memo_id)).stem
    status = STATUS_LABELS.get(review.get("status", "Draft"), review.get("status", "Draft"))
    return f"{borrower} - {memo.get('memo_type', 'Memo')} - {status}"


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


def rebuild_sections_from_page_text(workspace: Path, memo_id: str, extraction_method: str) -> None:
    pages = load_page_text(workspace, memo_id)
    definitions = load_section_defs(workspace)
    proposed = propose_sections(
        memo_id=memo_id,
        pages=pages,
        definitions=definitions,
        extraction_method=extraction_method,
    )
    save_sections(workspace, memo_id, [section.model_dump() for section in proposed])
    candidates = propose_section_candidates(memo_id, pages, definitions)
    write_json(memo_dir(workspace, memo_id) / "sections" / "section_candidates.json", [candidate.model_dump() for candidate in candidates])


def step_summary(workspace: Path, memo_id: str | None) -> dict[str, str]:
    if not memo_id:
        return {
            "Add Memo": "Needs Review",
            "Review Text Quality": "Not Started",
            "Confirm Sections": "Not Started",
            "Set Up Facilities": "Not Started",
            "Tag Credit Review": "Not Started",
            "Tag Outcomes": "Not Started",
            "Quality Check": "Not Started",
            "Download Results": "Not Started",
        }

    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    review = load_review(workspace, memo_id)
    section_defs = load_section_defs(workspace)
    gaps = required_section_gaps(sections, section_defs, memo.get("memo_type", ""), memo.get("facility_type", ""))

    quality_complete = text_quality_complete(workspace, memo_id)
    sections_complete = bool(sections) and not gaps and all(section.get("reviewer_confirmed") for section in sections)
    facilities = load_facilities(workspace, memo_id)
    outcomes = load_outcomes(workspace, memo_id)
    confirmed_facilities = [facility for facility in facilities if facility.get("status") == "Confirmed" or facility.get("reviewer_confirmed")]
    tags_complete = not quality_findings(workspace, memo_id)[0]
    approved = review.get("status") == "Approved Gold"
    exported = review.get("status") == "Exported"

    return {
        "Add Memo": "Complete",
        "Review Text Quality": "Complete" if quality_complete else "Needs Review",
        "Confirm Sections": "Complete" if sections_complete else ("Needs Review" if quality_complete else "Not Started"),
        "Set Up Facilities": "Complete" if confirmed_facilities else ("Needs Review" if sections_complete else "Not Started"),
        "Tag Credit Review": "Complete" if tags_complete else ("Needs Review" if confirmed_facilities else "Not Started"),
        "Tag Outcomes": "Complete" if outcomes else ("Needs Review" if confirmed_facilities else "Not Started"),
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
    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    section_defs = load_section_defs(workspace)
    tags = load_tags(workspace, memo_id)
    evidence = load_evidence(workspace, memo_id)
    page_quality = load_page_quality(workspace, memo_id)
    warnings = load_extraction_warnings(workspace, memo_id)
    facilities = load_facilities(workspace, memo_id)
    outcomes = load_outcomes(workspace, memo_id)
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

    gaps = required_section_gaps(sections, section_defs, memo.get("memo_type", ""), memo.get("facility_type", ""))
    if gaps:
        findings.append("Missing required sections: " + ", ".join(gap.display_name for gap in gaps))

    unconfirmed = [section for section in sections if not section.get("reviewer_confirmed")]
    if unconfirmed:
        findings.append(f"{len(unconfirmed)} section(s) still need confirmation.")

    confirmed_facilities = [facility for facility in facilities if facility.get("status") == "Confirmed" or facility.get("reviewer_confirmed")]
    if not confirmed_facilities:
        findings.append("At least one facility must be confirmed before approval.")

    if not outcomes:
        findings.append("Outcome tagging must be completed, even if the outcome is Unknown / Not seasoned yet.")

    if not tags:
        findings.append("No credit tags have been saved yet.")

    section_ids_with_tags = {tag.get("section_id") for tag in tags}
    untagged_sections = [section for section in sections if section.get("section_id") not in section_ids_with_tags]
    if untagged_sections:
        findings.append(f"{len(untagged_sections)} confirmed section(s) do not have saved tags.")

    evidence_ids = {item.get("evidence_id") for item in evidence}
    tag_defs = {definition.tag_id: definition for definition in load_tag_defs(workspace)}
    section_defs_by_key = {definition.section_id: definition for definition in section_defs}
    missing_required_tags: list[str] = []
    for section in sections:
        if not section.get("reviewer_confirmed"):
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
        "outcomes_total": len(outcomes),
    }
    return findings, metrics


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def acquire_or_refresh_lock(
    workspace: Path,
    memo_id: str,
    *,
    session_id: str,
    owner_name: str,
    current_step: str,
    ttl_minutes: int = 30,
) -> tuple[bool, str, dict[str, Any]]:
    now = datetime.now(UTC)
    existing = load_active_lock(workspace, memo_id)
    expires_at = _parse_dt(str(existing.get("expires_at", ""))) if existing else None
    if existing and existing.get("owner_session_id") != session_id and expires_at and expires_at > now:
        return False, f"This memo is currently being reviewed by {existing.get('owner_name') or 'another user'}.", existing

    lock = MemoLockRecord(
        memo_id=memo_id,
        lock_id=str(existing.get("lock_id") or f"lock_{uuid4().hex[:10]}"),
        owner_session_id=session_id,
        owner_name=owner_name,
        current_step=current_step,
        acquired_at=str(existing.get("acquired_at") or now.isoformat()),
        heartbeat_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=ttl_minutes)).isoformat(),
    )
    save_active_lock(workspace, memo_id, lock)
    return True, "Memo lock active.", lock.model_dump()


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
