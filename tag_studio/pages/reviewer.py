from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

from tag_studio.app_config import STATUS_LABELS, TAG_CATEGORY_ORDER
from tag_studio.defaults import (
    DEFAULT_FACILITY_TYPES,
    DEFAULT_MEMO_TYPES,
    DEFAULT_OUTCOME_AVAILABILITY_STATES,
    DEFAULT_OUTCOME_EVENT_TYPES,
    DEFAULT_OUTCOME_SOURCE_TYPES,
    SCHEMA_VERSION,
)
from tag_studio.document_intelligence import (
    dependency_status,
    load_extraction_warnings,
    load_page_quality,
    load_page_text,
    run_document_intelligence,
    save_extraction_warnings,
    save_page_quality,
    save_page_text,
    summarize_page_quality,
)
from tag_studio.exporters import export_excel, export_jsonl, export_memo_bundle
from tag_studio.extraction import pdf_page_count
from tag_studio.models import (
    EvidenceRecord,
    FacilityOutcomeSummaryRecord,
    FacilityRecord,
    ForeseeabilityAssessmentRecord,
    OutcomeEventRecord,
    TagDefinition,
    TagRecord,
    utc_now,
)
from tag_studio.sectioning import propose_sections
from tag_studio.services import (
    accept_section,
    accept_sections,
    apply_section_cleanup,
    classify_section_review,
    derive_primary_outcome,
    facility_review_rows_to_records,
    load_learned_heading_matches,
    load_section_defs,
    memo_display_name,
    outcome_event_severity,
    quality_findings,
    rebuild_sections_from_page_text,
    save_learned_heading_match,
    section_cleanup_blocks,
    step_summary,
    tags_for_section,
    text_quality_complete,
    undo_last_section_cleanup,
)
from tag_studio.storage import (
    active_schema_hash,
    active_schema_payload,
    append_audit,
    create_memo_workspace,
    list_memo_ids,
    load_evidence,
    load_facilities,
    load_foreseeability_assessments,
    load_memo_record,
    load_outcome_events,
    load_outcome_summaries,
    load_review,
    load_sections,
    load_tags,
    memo_dir,
    read_json,
    save_evidence,
    save_facilities,
    save_foreseeability_assessments,
    save_memo_record,
    save_outcome_events,
    save_outcome_summaries,
    save_review,
    save_sections,
    save_tags,
    slugify,
    write_json,
)
from tag_studio.ui_components import badge, blocked_step, extraction_message, go_to_step

MAX_UPLOAD_MB = 50
MAX_PDF_PAGES = 250
SCOPE_LABELS = {
    "memo": "Whole memo",
    "borrower": "Borrower",
    "facility": "Facility",
    "section": "This section",
    "outcome": "Outcome",
}


def _preflight_upload(workspace: Path, file_name: str, pdf_bytes: bytes) -> tuple[bool, str]:
    if len(pdf_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        return False, f"PDF is larger than the {MAX_UPLOAD_MB} MB limit."
    preflight_dir = workspace / "_preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    preflight_path = preflight_dir / f"{uuid4().hex}_{slugify(Path(file_name).stem)}.pdf"
    try:
        preflight_path.write_bytes(pdf_bytes)
        page_count = pdf_page_count(preflight_path)
    except Exception as exc:  # noqa: BLE001 - keep intake message user-facing.
        return False, f"Tag Studio could not inspect this PDF before upload: {exc}"
    finally:
        if preflight_path.exists():
            preflight_path.unlink()
    if page_count > MAX_PDF_PAGES:
        return False, f"PDF has {page_count} pages. The current limit is {MAX_PDF_PAGES} pages."
    return True, ""


def _suggest_facilities(memo_id: str, customer_id: str, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keywords = {
        "Revolver": ["revolver", "revolving", "line of credit"],
        "Term Loan": ["term loan"],
        "ABL": ["abl", "asset based", "borrowing base"],
        "CRE": ["cre", "commercial real estate", "real estate"],
        "Equipment": ["equipment"],
        "Acquisition Finance": ["acquisition"],
        "LOC": ["letter of credit", "loc"],
    }
    facilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in sections:
        text = f"{section.get('canonical_section_name', '')}\n{section.get('text', '')}".lower()
        for facility_type, terms in keywords.items():
            if facility_type in seen:
                continue
            if any(term in text for term in terms):
                seen.add(facility_type)
                facilities.append(
                    FacilityRecord(
                        facility_id=f"facility_{slugify(facility_type)}",
                        memo_id=memo_id,
                        customer_id=customer_id,
                        facility_name=facility_type,
                        facility_type=facility_type,
                        proposed_from_text=True,
                        confidence=0.75,
                        source_section_id=str(section.get("section_id", "")),
                        source_evidence=str(section.get("text", ""))[:500],
                    ).model_dump()
                )
    if not facilities:
        facilities.append(
            FacilityRecord(
                facility_id="facility_primary",
                memo_id=memo_id,
                customer_id=customer_id,
                facility_name="Primary Facility",
                facility_type="Multiple",
                confidence=0.25,
            ).model_dump()
        )
    return facilities


def add_memo_page(workspace: Path) -> None:
    st.subheader("Add Memo")

    memo_ids = list_memo_ids(workspace)
    if memo_ids:
        st.markdown("##### Continue an Existing Memo")
        st.caption("Use this when the memo has already been uploaded. Choose it here, then continue with the review steps on the left.")
        labels = {memo_id: memo_display_name(workspace, memo_id) for memo_id in memo_ids}
        active = st.session_state.get("active_memo_id") or memo_ids[0]
        active = st.selectbox(
            "Existing memo",
            memo_ids,
            index=memo_ids.index(active) if active in memo_ids else 0,
            format_func=lambda memo_id: labels.get(memo_id, memo_id),
            help="This only selects a memo that is already in Tag Studio. It does not upload or read a new PDF.",
        )
        st.session_state["active_memo_id"] = active
        if st.button("Continue Review", type="primary"):
            go_to_step("Review Text Quality")

    st.divider()
    st.markdown("##### Upload a New Credit Memo")
    st.caption("Use this only when you need to add a new PDF to Tag Studio.")
    deps = dependency_status()
    if not deps.get("tesseract"):
        st.warning(
            "Scanned memo setup is incomplete. Digital PDFs can still be read, but scanned PDFs may need local scanned-page support "
            "or manual text correction before Tag Studio can reliably read page images."
        )
    with st.form("add_memo_form"):
        uploaded = st.file_uploader(
            "Credit memo PDF",
            type=["pdf"],
            help="Choose the memo you want reviewed and tagged. Use a PDF that contains no information outside the review packet.",
        )
        customer_id = st.text_input(
            "Customer ID",
            help="Use the bank-assigned numeric or opaque customer identifier. Do not enter the customer name.",
        )
        col1, col2 = st.columns(2)
        with col1:
            memo_type = st.selectbox(
                "Memo type",
                DEFAULT_MEMO_TYPES,
                index=1,
                help="Pick the closest credit action so required sections and review expectations match the memo.",
            )
        with col2:
            facility_type = st.selectbox(
                "Facility type",
                DEFAULT_FACILITY_TYPES,
                index=7,
                help="Pick the main facility type so Tag Studio can apply the right section and tagging expectations.",
            )
        reviewer = st.text_input("Reviewer name")
        submitted = st.form_submit_button("Read Memo", type="primary")

    if not submitted:
        return
    if uploaded is None:
        st.error("Choose a new credit memo PDF before reading the uploaded memo.")
        return
    pdf_bytes = uploaded.getvalue()
    ok, preflight_message = _preflight_upload(workspace, uploaded.name, pdf_bytes)
    if not ok:
        st.error(preflight_message)
        return

    memo_id = f"memo_{slugify(Path(uploaded.name).stem)}_{uuid4().hex[:8]}"
    record = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=pdf_bytes,
        file_name=uploaded.name,
        memo_id=memo_id,
        memo_type=memo_type,
        facility_type=facility_type,
        customer_id=customer_id,
        reviewer=reviewer,
    )

    with st.spinner("Reading memo text..."):
        try:
            section_defs = load_section_defs(workspace)
            learned_headings = load_learned_heading_matches(workspace)
            intelligence = run_document_intelligence(workspace, memo_id, section_defs, learned_headings=learned_headings)
        except Exception as exc:  # noqa: BLE001 - show a friendly error in the UI.
            st.error("Tag Studio could not read this PDF. Confirm the file opens normally, then try again.")
            append_audit(workspace, memo_id, "extraction_failed", {"error": str(exc)})
            return

        page_text = intelligence["pages"]
        method = intelligence["method"]
        warning = intelligence["warning"]
        memo_record = record.model_dump()
        memo_record["extraction_method"] = method
        save_memo_record(workspace, memo_id, memo_record)

        proposed = propose_sections(
            memo_id=memo_id,
            pages=[page.model_dump() for page in page_text],
            definitions=section_defs,
            extraction_method=method,
            learned_headings=learned_headings,
        )
        save_sections(workspace, memo_id, [section.model_dump() for section in proposed])

    st.session_state["active_memo_id"] = memo_id
    extraction_message(method, warning, len(page_text))
    go_to_step("Review Text Quality")


def review_text_quality_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Review Text Quality")
    if not memo_id:
        blocked_step("Add a memo before reviewing text quality.", "Add Memo")
        return

    memo = load_memo_record(workspace, memo_id)
    page_quality = load_page_quality(workspace, memo_id)
    page_text = load_page_text(workspace, memo_id)
    warnings = load_extraction_warnings(workspace, memo_id)
    if not page_quality or not page_text:
        st.warning("This memo needs the new text-quality review files before it can continue.")
        st.write("Use the button below to read the saved PDF again and create the page review workspace.")
        if st.button("Create Text Quality Review", type="primary"):
            with st.spinner("Reading the saved memo..."):
                try:
                    section_defs = load_section_defs(workspace)
                    learned_headings = load_learned_heading_matches(workspace)
                    intelligence = run_document_intelligence(workspace, memo_id, section_defs, learned_headings=learned_headings)
                except Exception as exc:  # noqa: BLE001 - keep the reviewer-facing message plain.
                    st.error("Tag Studio could not read the saved PDF. Confirm the original PDF is still available in the memo workspace.")
                    append_audit(workspace, memo_id, "text_quality_rebuild_failed", {"error": str(exc)})
                    return
                memo_record = memo.copy()
                memo_record["extraction_method"] = intelligence["method"]
                save_memo_record(workspace, memo_id, memo_record)
                if not load_tags(workspace, memo_id):
                    proposed = propose_sections(
                        memo_id=memo_id,
                        pages=[page.model_dump() for page in intelligence["pages"]],
                        definitions=section_defs,
                        extraction_method=intelligence["method"],
                        learned_headings=learned_headings,
                    )
                    save_sections(workspace, memo_id, [section.model_dump() for section in proposed])
                append_audit(workspace, memo_id, "text_quality_rebuilt", {"method": intelligence["method"]})
                st.success("Text quality review files created.")
                st.rerun()
        return

    summary = summarize_page_quality(page_quality)
    cols = st.columns(4)
    metrics = [
        ("Pages", summary["page_count"]),
        ("Average Read Quality", f"{int(summary['average_score'] * 100)}%"),
        ("Needs Review", summary["needs_review_count"]),
        ("Text Reading Warnings", len([warning for warning in warnings if not warning.get("resolved")])),
    ]
    for col, (label, value) in zip(cols, metrics, strict=True):
        col.markdown(f'<div class="metric-card"><div class="label">{label}</div><div class="value">{value}</div></div>', unsafe_allow_html=True)

    if warnings:
        st.markdown("##### Items to Check")
        for warning in warnings[:6]:
            severity = warning.get("severity", "Review")
            status = "Hard to Read" if severity == "Blocking" else "Needs Review"
            st.markdown(
                f'<div class="section-suggestion">{badge(severity, status)} '
                f'{warning.get("message", "")}<br><span class="small-muted">{warning.get("action", "")}</span></div>',
                unsafe_allow_html=True,
            )

    selected_default = st.session_state.get(f"selected_quality_page_{memo_id}", 1)
    page_numbers = [int(record["page_number"]) for record in page_quality]
    if selected_default not in page_numbers:
        selected_default = page_numbers[0]

    st.markdown("##### Page Review")
    thumb_cols = st.columns(min(4, max(1, len(page_quality))))
    for idx, record in enumerate(page_quality):
        page_number = int(record["page_number"])
        active = page_number == selected_default
        status = str(record.get("status", "Needs Review"))
        with thumb_cols[idx % len(thumb_cols)]:
            st.markdown(
                f'<div class="quality-card {"active" if active else ""}">'
                f"<b>Page {page_number}</b><br>{badge(status, status)}"
                f'<div class="small-muted">Read quality: {int(float(record.get("text_quality_score", 0)) * 100)}%</div>'
                f'<div class="small-muted">{"Reviewed" if record.get("reviewer_confirmed") else "Needs user check"}</div>'
                "</div>",
                unsafe_allow_html=True,
            )
            if st.button(f"Open Page {page_number}", key=f"open_quality_page_{memo_id}_{page_number}"):
                st.session_state[f"selected_quality_page_{memo_id}"] = page_number
                st.rerun()

    selected_page_number = int(st.session_state.get(f"selected_quality_page_{memo_id}", selected_default))
    selected_record = next(record for record in page_quality if int(record["page_number"]) == selected_page_number)
    selected_text = next((record for record in page_text if int(record["page_number"]) == selected_page_number), {})

    left, right = st.columns([1.05, 1.3])
    with left:
        st.markdown(f"##### Page {selected_page_number} Image")
        image_path = memo_dir(workspace, memo_id) / "pages" / f"page_{selected_page_number:03}.png"
        if image_path.exists():
            st.image(str(image_path), width="stretch")
        else:
            st.info("Page image is not available.")
        st.markdown(
            f'{badge(str(selected_record.get("status", "Needs Review")), str(selected_record.get("status", "Needs Review")))} '
            f'<span class="small-muted">Flags: {", ".join(selected_record.get("flags", [])) or "None"}</span>',
            unsafe_allow_html=True,
        )

    with right:
        st.markdown("##### Extracted Text")
        corrected_text = st.text_area(
            "Correct this text if the page image shows text-reading mistakes.",
            value=selected_text.get("text", ""),
            height=500,
            key=f"quality_text_{memo_id}_{selected_page_number}",
        )
        notes = st.text_area(
            "Reviewer notes",
            value=selected_record.get("reviewer_notes", ""),
            height=90,
            key=f"quality_notes_{memo_id}_{selected_page_number}",
            help="Use this for handwriting, unreadable text, or table issues.",
        )
        disposition_options = ["Corrected", "Reviewed - acceptable", "Not material", "Unable to read", "Needs escalation"]
        current_disposition = selected_record.get("disposition", "Reviewed - acceptable" if selected_record.get("status") == "Ready" else "Unresolved")
        disposition = st.selectbox(
            "Page review decision",
            disposition_options,
            index=disposition_options.index(current_disposition) if current_disposition in disposition_options else 1,
            key=f"quality_disposition_{memo_id}_{selected_page_number}",
            help="Every non-ready page needs a final disposition before approval.",
        )
        disposition_rationale = st.text_area(
            "Reason for this decision",
            value=selected_record.get("disposition_rationale", ""),
            height=70,
            key=f"quality_disposition_rationale_{memo_id}_{selected_page_number}",
            help="Required when a page is unable to read, not material, or needs escalation.",
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "Save Page Review",
                type="primary",
                help="Save corrected page text and mark this page as reviewed for section mapping.",
            ):
                for record in page_text:
                    if int(record["page_number"]) == selected_page_number:
                        record.setdefault("original_text", record.get("text", ""))
                        record["text"] = corrected_text
                        record["corrected_text"] = corrected_text
                        record["source_text_version"] = "corrected" if corrected_text != record.get("original_text", "") else "reviewed"
                for record in page_quality:
                    if int(record["page_number"]) == selected_page_number:
                        record["reviewer_confirmed"] = True
                        record["reviewer_notes"] = notes
                        record["disposition"] = disposition
                        record["disposition_rationale"] = disposition_rationale
                        if record.get("status") == "Hard to Read" and corrected_text.strip():
                            record["status"] = "Needs Review"
                for warning in warnings:
                    if not warning.get("page_number") or int(warning.get("page_number")) == selected_page_number:
                        warning["resolved"] = disposition not in {"Unresolved", "Needs escalation"}
                save_page_text(workspace, memo_id, page_text)
                save_page_quality(workspace, memo_id, page_quality)
                save_extraction_warnings(workspace, memo_id, warnings)
                rebuild_sections_from_page_text(workspace, memo_id, memo.get("extraction_method", "manual_correction"))
                append_audit(workspace, memo_id, "page_quality_review_saved", {"page_number": selected_page_number})
                st.success("Page review saved.")
                st.rerun()
        with col2:
            if st.button(
                "Mark Page Reviewed",
                help="Use this only when the extracted text already matches the page image closely enough for tagging.",
            ):
                for record in page_quality:
                    if int(record["page_number"]) == selected_page_number:
                        record["reviewer_confirmed"] = True
                        record["disposition"] = "Reviewed - acceptable"
                        record["disposition_rationale"] = notes
                for warning in warnings:
                    if not warning.get("page_number") or int(warning.get("page_number")) == selected_page_number:
                        warning["resolved"] = True
                save_page_quality(workspace, memo_id, page_quality)
                save_extraction_warnings(workspace, memo_id, warnings)
                append_audit(workspace, memo_id, "page_quality_marked_reviewed", {"page_number": selected_page_number})
                st.rerun()

    remaining = [record for record in load_page_quality(workspace, memo_id) if not record.get("reviewer_confirmed") and record.get("status") != "Ready"]
    st.markdown("##### Next Action")
    if remaining:
        st.warning(f"{len(remaining)} page(s) still need review before memo sections are reviewed.")
    else:
        st.success("Text quality review is complete.")
        if st.button("Continue to Review Memo Sections", type="primary"):
            go_to_step("Review Memo Sections")


def _next_section_id(sections: list[dict[str, Any]]) -> str:
    existing = {str(section.get("section_id", "")) for section in sections}
    index = len(sections) + 1
    while f"section_{index:03}" in existing:
        index += 1
    return f"section_{index:03}"


def _save_section_mapping(
    workspace: Path,
    memo_id: str,
    section_id: str,
    canonical_id: str,
    canonical_name: str,
) -> None:
    sections = load_sections(workspace, memo_id)
    updated = []
    original_heading = ""
    for section in sections:
        if section.get("section_id") == section_id:
            original_heading = str(section.get("original_header", ""))
            section = {
                **section,
                "canonical_section_id": canonical_id,
                "canonical_section_name": canonical_name,
                "reviewer_confirmed": True,
                "missing_required": False,
            }
        updated.append(section)
    save_sections(workspace, memo_id, updated)
    save_learned_heading_match(workspace, canonical_id, original_heading)
    append_audit(workspace, memo_id, "section_exception_resolved", {"section_id": section_id, "canonical_section_id": canonical_id})


def _save_missing_section_not_addressed(workspace: Path, memo_id: str, canonical_id: str, canonical_name: str) -> None:
    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    sections.append(
        {
            "section_id": _next_section_id(sections),
            "memo_id": memo_id,
            "canonical_section_id": canonical_id,
            "canonical_section_name": canonical_name,
            "original_header": "Not found in memo",
            "page_start": 1,
            "page_end": 1,
            "text": "Not addressed in memo.",
            "extraction_method": memo.get("extraction_method", "manual_correction"),
            "reviewer_confirmed": True,
            "missing_required": True,
        }
    )
    save_sections(workspace, memo_id, sections)
    append_audit(workspace, memo_id, "missing_section_marked_not_addressed", {"canonical_section_id": canonical_id})


def _save_manual_section(
    workspace: Path,
    memo_id: str,
    canonical_id: str,
    canonical_name: str,
    original_heading: str,
    page_start: int,
    page_end: int,
    text: str,
    reason: str,
) -> None:
    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    sections.append(
        {
            "section_id": _next_section_id(sections),
            "memo_id": memo_id,
            "canonical_section_id": canonical_id,
            "canonical_section_name": canonical_name,
            "original_header": original_heading or canonical_name,
            "page_start": page_start,
            "page_end": page_end,
            "line_start": 1,
            "line_end": max(1, len(text.splitlines())),
            "text": text,
            "extraction_method": memo.get("extraction_method", "manual_correction"),
            "reviewer_confirmed": True,
            "missing_required": False,
            "manual_section_reason": reason,
        }
    )
    save_sections(workspace, memo_id, sections)
    append_audit(workspace, memo_id, "manual_section_added", {"canonical_section_id": canonical_id, "reason": reason})


def _render_status_count(label: str, value: int, tone: str) -> None:
    color = {"hard": "#9b1c1c", "review": "#7a4c00", "ready": "#176b3a"}.get(tone, "#172333")
    st.markdown(
        f'<div class="metric-card"><div class="label">{escape(label)}</div>'
        f'<div class="value" style="color:{color}">{value}</div></div>',
        unsafe_allow_html=True,
    )


def _render_section_item_header(item) -> None:
    confidence = f"{int(item.confidence * 100)}%" if item.confidence else "Not available"
    page_range = f"Pages {item.page_start} to {item.page_end}" if item.page_start and item.page_end else "Page not available"
    st.markdown(f"##### {item.title}")
    st.caption(f"{page_range} | Match confidence: {confidence}")
    if item.standard_section_name:
        st.write(f"**Current standard section:** {item.standard_section_name}")
    if item.suggested_section_name:
        st.write(f"**Suggested standard section:** {item.suggested_section_name}")


def _render_section_item_details(item) -> None:
    for reason in item.reasons:
        st.write(f"- {reason}")
    if item.text_preview:
        st.markdown("**Section text preview**")
        st.write(item.text_preview)


def _render_section_acceptance_action(workspace: Path, memo_id: str, item, *, key_prefix: str) -> None:
    if not item.section_id or item.missing_section_id or not item.standard_section_id:
        return
    accepted = bool((item.section or {}).get("reviewer_confirmed"))
    cols = st.columns([2.7, 1])
    with cols[0]:
        if accepted:
            st.success("Accepted for section review. This confirms the text is assigned to the right Standard Memo Section.")
        else:
            st.info("Needs acceptance. Confirm this heading and text belong under the Standard Memo Section shown above.")
    with cols[1]:
        if accepted:
            st.button("Accepted", key=f"{key_prefix}_accepted_{memo_id}_{item.section_id}", disabled=True)
        elif st.button(
            "Accept This Section",
            type="primary",
            key=f"{key_prefix}_accept_{memo_id}_{item.section_id}",
            help="Use this when the section heading and text are grouped under the right Standard Memo Section. This is not a credit approval.",
        ):
            accept_section(workspace, memo_id, item.section_id)
            st.rerun()


def _render_section_cleanup_tools(
    workspace: Path,
    memo_id: str,
    item,
    definitions: dict[str, Any],
    sections: list[dict[str, Any]],
) -> None:
    if not item.section_id:
        return
    with st.expander("Clean Up Section Text"):
        st.caption(
            "Use this only when a paragraph was placed under the wrong memo section. "
            "Leave the text alone if it already belongs here."
        )
        blocks = section_cleanup_blocks(item.section or {})
        if not blocks:
            st.caption("There is no section text to clean up.")
            return
        if st.button("Undo Last Cleanup", key=f"undo_cleanup_{memo_id}_{item.section_id}"):
            if undo_last_section_cleanup(workspace, memo_id):
                st.success("Last section cleanup was undone.")
                st.rerun()
            st.warning("No section cleanup is available to undo.")

        section_choices = [
            section
            for section in sections
            if section.get("section_id") != item.section_id and not section.get("missing_required")
        ]
        section_labels = {
            str(section.get("section_id")): f"{section.get('canonical_section_name')} - {section.get('original_header')}"
            for section in section_choices
        }
        standard_options = list(definitions.keys())
        cleanup_actions: dict[str, dict[str, str]] = {}
        with st.form(f"cleanup_section_{memo_id}_{item.section_id}"):
            st.markdown("**Before saving**")
            st.write(f"This section currently has {len(blocks)} text block(s). Choose only the blocks that need cleanup.")
            for block in blocks:
                st.markdown('<div class="soft-panel">', unsafe_allow_html=True)
                st.markdown(f"**{block.label}**")
                st.write(block.text)
                action = st.selectbox(
                    "Where should this text go?",
                    [
                        "Keep Here",
                        "Move to Another Section",
                        "Start New Section Here",
                        "Add to Previous Section",
                        "Mark as Duplicate",
                    ],
                    key=f"cleanup_action_{memo_id}_{item.section_id}_{block.block_id}",
                    help="Choose the plain-English outcome for this paragraph. Most paragraphs should stay here.",
                )
                action_record = {"action": action}
                if action == "Move to Another Section" and section_choices:
                    target_section_id = st.selectbox(
                        "Move this text to",
                        list(section_labels),
                        format_func=lambda value: section_labels.get(value, value),
                        key=f"cleanup_target_{memo_id}_{item.section_id}_{block.block_id}",
                    )
                    action_record["target_section_id"] = target_section_id
                elif action == "Move to Another Section":
                    st.caption("No other sections are available yet. Choose a different action or create a new section.")
                if action == "Start New Section Here":
                    new_standard_section_id = st.selectbox(
                        "What section should this become?",
                        standard_options,
                        index=standard_options.index(item.standard_section_id) if item.standard_section_id in standard_options else 0,
                        format_func=lambda value: definitions[value].display_name,
                        key=f"cleanup_new_section_{memo_id}_{item.section_id}_{block.block_id}",
                    )
                    action_record["new_standard_section_id"] = new_standard_section_id
                cleanup_actions[block.block_id] = action_record
                st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("**After saving**")
            st.caption("Tag Studio will update the affected section text and keep an undo point for this cleanup.")
            submitted = st.form_submit_button("Save Cleaned Text", type="primary")
        if submitted:
            apply_section_cleanup(workspace, memo_id, item.section_id, cleanup_actions, definitions)
            st.success("Section text cleanup saved.")
            st.rerun()


def _render_section_exception_card(workspace: Path, memo_id: str, item, definitions: dict[str, Any], sections: list[dict[str, Any]]) -> None:
    st.markdown('<div class="review-card">', unsafe_allow_html=True)
    _render_section_item_header(item)
    _render_section_acceptance_action(workspace, memo_id, item, key_prefix="exception")
    _render_section_item_details(item)
    section_options = list(definitions.keys())
    if (
        item.section_id
        and item.suggested_section_id
        and "low_confidence_match" in item.reason_codes
        and item.suggested_section_id in definitions
        and st.button("Accept Suggested Section", type="primary", key=f"accept_{memo_id}_{item.section_id}")
    ):
        _save_section_mapping(
            workspace,
            memo_id,
            item.section_id,
            item.suggested_section_id,
            definitions[item.suggested_section_id].display_name,
        )
        st.rerun()

    if item.section_id:
        with st.expander("Choose Different Section"):
            current_id = item.standard_section_id if item.standard_section_id in definitions else section_options[0]
            selected_id = st.selectbox(
                "What kind of memo section is this?",
                section_options,
                index=section_options.index(current_id),
                format_func=lambda value: definitions[value].display_name,
                key=f"change_standard_{memo_id}_{item.section_id}",
            )
            if st.button("Accept Selected Section", key=f"save_mapping_{memo_id}_{item.section_id}"):
                _save_section_mapping(
                    workspace,
                    memo_id,
                    item.section_id,
                    selected_id,
                    definitions[selected_id].display_name,
                )
                st.rerun()
        if item.required and st.button("Mark Not Addressed", key=f"not_addressed_existing_{memo_id}_{item.section_id}"):
            _save_section_mapping(
                workspace,
                memo_id,
                item.section_id,
                item.standard_section_id,
                item.standard_section_name,
            )
            updated_sections = []
            for section in load_sections(workspace, memo_id):
                if section.get("section_id") == item.section_id:
                    section = {**section, "missing_required": True, "text": "Not addressed in memo.", "reviewer_confirmed": True}
                updated_sections.append(section)
            save_sections(workspace, memo_id, updated_sections)
            st.rerun()
        _render_section_cleanup_tools(workspace, memo_id, item, definitions, sections)

    if item.missing_section_id:
        with st.expander("Find It In Memo"):
            detected_sections = [section for section in sections if not section.get("missing_required")]
            if detected_sections:
                labels = {
                    section["section_id"]: f"{section.get('original_header')} - p.{section.get('page_start')}-{section.get('page_end')}"
                    for section in detected_sections
                }
                selected_section_id = st.selectbox(
                    "Detected section",
                    list(labels),
                    format_func=lambda value: labels[value],
                    key=f"map_missing_{memo_id}_{item.missing_section_id}",
                )
                if st.button("Use Selected Section", key=f"map_missing_save_{memo_id}_{item.missing_section_id}"):
                    _save_section_mapping(
                        workspace,
                        memo_id,
                        selected_section_id,
                        item.missing_section_id,
                        item.missing_section_name,
                    )
                    st.rerun()
            else:
                st.caption("No detected sections are available to map.")
        if st.button("Mark Not Addressed", key=f"missing_not_addressed_{memo_id}_{item.missing_section_id}"):
            _save_missing_section_not_addressed(workspace, memo_id, item.missing_section_id, item.missing_section_name)
            st.rerun()
        with st.expander("Add Manual Section"):
            with st.form(f"manual_section_{memo_id}_{item.missing_section_id}"):
                original_heading = st.text_input("Original memo heading", value=item.missing_section_name)
                page_col1, page_col2 = st.columns(2)
                with page_col1:
                    page_start = st.number_input("Page start", min_value=1, value=1, step=1)
                with page_col2:
                    page_end = st.number_input("Page end", min_value=1, value=1, step=1)
                reason = st.selectbox("Reason", ["Text reader missed it", "Memo heading was not found", "Scanned page issue", "Other"])
                manual_text = st.text_area("Section text", height=160)
                submitted = st.form_submit_button("Save Manual Section")
            if submitted:
                if not manual_text.strip():
                    st.error("Add section text before saving a manual section.")
                else:
                    _save_manual_section(
                        workspace,
                        memo_id,
                        item.missing_section_id,
                        item.missing_section_name,
                        original_heading,
                        int(page_start),
                        int(page_end),
                        manual_text,
                        reason,
                    )
                    st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_ready_section_card(workspace: Path, memo_id: str, item) -> None:
    st.markdown('<div class="review-card">', unsafe_allow_html=True)
    _render_section_item_header(item)
    _render_section_acceptance_action(workspace, memo_id, item, key_prefix="ready")
    _render_section_item_details(item)
    st.markdown("</div>", unsafe_allow_html=True)


def confirm_sections_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Review Memo Sections")
    st.caption("Make sure the memo text is grouped under the right standard sections before tagging.")
    if not memo_id:
        blocked_step("Add a memo before reviewing memo sections.", "Add Memo")
        return

    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    if not sections:
        blocked_step("No memo sections were found. Add the memo again or use Admin Tools to inspect the text reading result.", "Add Memo")
        return

    extraction_summary = read_json(memo_dir(workspace, memo_id) / "extraction" / "extraction_summary.json", {})
    if extraction_summary:
        extraction_message(
            str(extraction_summary.get("method", memo.get("extraction_method", ""))),
            extraction_summary.get("warning"),
            int(extraction_summary.get("page_count") or 0),
        )

    section_defs = load_section_defs(workspace)
    definitions = {section.section_id: section for section in section_defs}

    if not text_quality_complete(workspace, memo_id):
        blocked_step("Review the memo text quality before reviewing memo sections.", "Review Text Quality")
        return

    summary = classify_section_review(workspace, memo_id)
    unaccepted_sections = [section for section in sections if not section.get("reviewer_confirmed")]
    accepted_sections = [section for section in sections if section.get("reviewer_confirmed")]
    count_cols = st.columns(3)
    with count_cols[0]:
        _render_status_count("Needs Fix", len(summary.must_fix), "hard")
    with count_cols[1]:
        _render_status_count("Needs Acceptance", len(unaccepted_sections), "review")
    with count_cols[2]:
        _render_status_count("Accepted", len(accepted_sections), "ready")

    st.caption("Accepting a section means the heading and text are assigned to the right Standard Memo Section. It is not a credit approval.")

    if summary.must_fix:
        st.markdown("##### Needs Your Attention")
        for item in summary.must_fix:
            _render_section_exception_card(workspace, memo_id, item, definitions, sections)
    else:
        st.success("All required memo section issues are resolved.")

    if summary.can_review_later:
        st.markdown("##### Optional Checks")
        st.caption("These items are worth a quick look, but they do not stop you from continuing.")
        for item in summary.can_review_later:
            _render_section_exception_card(workspace, memo_id, item, definitions, sections)

    ready_unaccepted_ids = [
        item.section_id
        for item in summary.ready
        if item.section_id and not (item.section or {}).get("reviewer_confirmed")
    ]
    with st.expander(f"Looks Good ({len(summary.ready)})", expanded=bool(ready_unaccepted_ids)):
        if not summary.ready:
            st.caption("No ready sections yet.")
        elif ready_unaccepted_ids and st.button(
            "Accept All Looks Good Sections",
            type="primary",
            help="Accepts only the high-confidence sections shown in this Looks Good list.",
        ):
            accepted_count = accept_sections(workspace, memo_id, ready_unaccepted_ids)
            st.success(f"Accepted {accepted_count} section(s).")
            st.rerun()
        for item in summary.ready:
            _render_ready_section_card(workspace, memo_id, item)

    st.markdown("##### Next Action")
    if summary.must_fix:
        st.warning(f"Review {len(summary.must_fix)} item(s) before continuing.")
        st.button("Review Items Above First", disabled=True)
    elif unaccepted_sections:
        st.warning(f"Accept {len(unaccepted_sections)} section(s) before continuing.")
        st.button("Accept Sections Above First", disabled=True)
    elif st.button("Continue to Set Up Facilities", type="primary"):
        go_to_step("Set Up Facilities")


def _display_required(label: str, required: bool) -> str:
    return f"{label} *" if required else label


def _enum_options(definition: TagDefinition) -> list[str]:
    options = ["", *definition.allowed_values]
    for option in ["Not addressed in memo", "Not applicable"]:
        if option not in options:
            options.append(option)
    return options


def _render_tag_input(definition: TagDefinition, key: str):
    label = _display_required(definition.label, definition.required)
    help_text = definition.help_text or "What would a credit officer need to know here?"
    if definition.data_type == "enum":
        return st.selectbox(label, _enum_options(definition), key=key, help=help_text)
    if definition.data_type == "multi_select":
        options = definition.allowed_values + [option for option in ["Not addressed in memo", "Not applicable"] if option not in definition.allowed_values]
        return st.multiselect(label, options, key=key, help=help_text)
    if definition.data_type == "number":
        return st.number_input(label, min_value=0.0, max_value=100.0, step=1.0, key=key, help=help_text)
    if definition.data_type == "boolean":
        return st.selectbox(label, ["", "Yes", "No", "Not addressed in memo", "Not applicable"], key=key, help=help_text)
    if definition.data_type == "long_text":
        return st.text_area(label, key=key, help=help_text, height=95)
    return st.text_input(label, key=key, help=help_text)


def set_up_facilities_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Set Up Facilities")
    st.caption("Confirm the facilities that will receive facility-specific tags and outcome records.")
    if not memo_id:
        blocked_step("Add a memo before setting up facilities.", "Add Memo")
        return
    statuses = step_summary(workspace, memo_id)
    if statuses["Review Memo Sections"] != "Complete":
        blocked_step("Review memo sections before setting up facilities.", "Review Memo Sections")
        return

    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    facilities = load_facilities(workspace, memo_id)
    if not facilities:
        facilities = _suggest_facilities(memo_id, str(memo.get("customer_id", "")), sections)
        save_facilities(workspace, memo_id, facilities)

    st.caption("Review the suggested facilities. Saving confirms each completed facility unless you mark it Rejected.")
    rows = [
        {
            "_facility_id": facility.get("facility_id"),
            "Facility Name": facility.get("facility_name"),
            "Facility Type": facility.get("facility_type"),
            "Amount": facility.get("amount", ""),
            "Facility Closing Date": facility.get("closing_date", ""),
            "Status": "Confirmed" if facility.get("reviewer_confirmed") else facility.get("status", "Proposed"),
            "Why Suggested": facility.get("source_evidence", "")[:180],
        }
        for facility in facilities
    ]
    edited = st.data_editor(
        pd.DataFrame(rows),
        num_rows="dynamic",
        width="stretch",
        key=f"facility_editor_{memo_id}",
        column_config={
            "_facility_id": None,
            "Facility Type": st.column_config.SelectboxColumn("Facility Type", options=DEFAULT_FACILITY_TYPES),
            "Status": st.column_config.SelectboxColumn("Status", options=["Proposed", "Confirmed", "Rejected"]),
            "Why Suggested": st.column_config.TextColumn("Why Suggested", disabled=True),
        },
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Facility Review", type="primary"):
            saved = facility_review_rows_to_records(
                memo_id,
                str(memo.get("customer_id", "")),
                edited.fillna("").to_dict("records"),
            )
            save_facilities(workspace, memo_id, saved)
            confirmed_count = len([facility for facility in saved if facility.get("reviewer_confirmed") or facility.get("status") == "Confirmed"])
            if confirmed_count:
                st.success("Facility review saved. This step is complete.")
            else:
                st.warning("Facility review saved, but no facilities are confirmed. Confirm at least one facility before continuing.")
            st.rerun()
    with col2:
        confirmed = [facility for facility in facilities if facility.get("reviewer_confirmed") or facility.get("status") == "Confirmed"]
        if confirmed and st.button("Continue to Tag Credit Review"):
            go_to_step("Tag Credit Review")


def tag_credit_review_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Tag Credit Review")
    st.caption("Review one memo section at a time, capture the credit judgment, and attach the evidence that supports it.")
    if not memo_id:
        blocked_step("Add a memo before tagging the credit review.", "Add Memo")
        return

    statuses = step_summary(workspace, memo_id)
    if statuses["Set Up Facilities"] != "Complete":
        blocked_step("Confirm facilities before tagging the credit review.", "Set Up Facilities")
        return

    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    tags = load_tags(workspace, memo_id)
    evidence = load_evidence(workspace, memo_id)
    facilities = [facility for facility in load_facilities(workspace, memo_id) if facility.get("status") == "Confirmed" or facility.get("reviewer_confirmed")]
    facility_options = ["", *[str(facility.get("facility_id")) for facility in facilities]]
    facility_labels = {"": "Memo / no facility", **{str(facility.get("facility_id")): f"{facility.get('facility_name')} ({facility.get('facility_type')})" for facility in facilities}}

    section_labels = {
        section["section_id"]: f"{section.get('canonical_section_name')} - p.{section.get('page_start')}-{section.get('page_end')}"
        for section in sections
    }
    section_id = st.selectbox("Memo section to tag", list(section_labels.keys()), format_func=lambda value: section_labels[value])
    section = next(item for item in sections if item["section_id"] == section_id)
    relevant_tags = tags_for_section(workspace, section)

    left, center, right = st.columns([1.05, 1.35, 1])
    with left:
        st.markdown("##### Memo Page")
        page_path = memo_dir(workspace, memo_id) / "pages" / f"page_{int(section.get('page_start', 1)):03}.png"
        if page_path.exists():
            st.image(str(page_path), width="stretch")
        else:
            st.info("Page image is not available.")

    with center:
        st.markdown("##### Section Text")
        st.text_area(
            "Text for review",
            section.get("text", ""),
            height=520,
            key=f"section_text_{memo_id}_{section_id}",
            label_visibility="collapsed",
        )

    with right:
        st.markdown("##### Evidence")
        raw_lines = [line.strip() for line in str(section.get("text", "")).splitlines() if line.strip()]
        selected_line_indices = st.multiselect(
            "Select evidence lines",
            list(range(len(raw_lines))),
            format_func=lambda idx: f"Line {idx + 1}: {raw_lines[idx][:100]}",
            key=f"evidence_lines_{memo_id}_{section_id}",
            help="Select the exact lines that support the tag values you plan to save.",
        )
        selected_line_text = "\n".join(raw_lines[idx] for idx in selected_line_indices)
        if selected_line_text:
            st.text_area("Selected evidence", selected_line_text, height=90, disabled=True)
        manual_evidence_text = st.text_area(
            "Evidence correction or note",
            height=90,
            key=f"evidence_text_{memo_id}_{section_id}",
            help="Use this when the extracted text needs correction.",
        )
        evidence_role = st.selectbox(
            "Evidence type",
            ["Supporting fact", "Missing information", "Contradiction", "Score support", "Policy exception", "Outcome support"],
            key=f"evidence_role_{memo_id}_{section_id}",
            help="Classify why this evidence matters for the credit review.",
        )
        citation_confidence = st.selectbox(
            "Citation confidence",
            ["High", "Medium", "Low"],
            index=1,
            key=f"citation_confidence_{memo_id}_{section_id}",
            help="Use High when the selected text directly supports the point. Use Low when it needs reviewer caution.",
        )
        evidence_facilities = st.multiselect(
            "Related facilities",
            [str(facility.get("facility_id")) for facility in facilities],
            format_func=lambda value: facility_labels.get(value, value),
            key=f"evidence_facilities_{memo_id}_{section_id}",
        )
        if st.button("Add Evidence", key=f"add_evidence_{memo_id}_{section_id}"):
            evidence_text = manual_evidence_text.strip() or selected_line_text.strip()
            if not evidence_text:
                st.error("Select evidence lines or enter a correction before adding evidence.")
            else:
                record = EvidenceRecord(
                    evidence_id=f"ev_{uuid4().hex[:10]}",
                    memo_id=memo_id,
                    section_id=section_id,
                    facility_ids=evidence_facilities,
                    page_number=int(section.get("page_start", 1)),
                    line_start=(min(selected_line_indices) + int(section.get("line_start", 1))) if selected_line_indices else None,
                    line_end=(max(selected_line_indices) + int(section.get("line_start", 1))) if selected_line_indices else None,
                    selected_text=evidence_text,
                    corrected_text_used=True,
                    source_text_version="corrected",
                    source_location=f"p.{section.get('page_start')} / {section.get('original_header')}",
                    evidence_role=slugify(evidence_role),
                    citation_confidence=citation_confidence,  # type: ignore[arg-type]
                    source_document_hash=memo.get("source_hash", ""),
                )
                evidence.append(record.model_dump())
                save_evidence(workspace, memo_id, evidence)
                st.success("Evidence added.")
                st.rerun()

        section_evidence = [item for item in evidence if item.get("section_id") == section_id]
        evidence_options = {
            item["evidence_id"]: f"{item.get('selected_text', '')[:90]}..." if len(item.get("selected_text", "")) > 90 else item.get("selected_text", "")
            for item in section_evidence
        }
        selected_evidence = st.multiselect(
            "Use this evidence for saved tags",
            list(evidence_options.keys()),
            format_func=lambda value: evidence_options[value],
        )

    st.markdown("##### Credit Tags")
    with st.form(f"tag_form_{memo_id}_{section_id}"):
        values = {}
        scopes = {}
        facility_assignments = {}
        grouped: dict[str, list[TagDefinition]] = {}
        for definition in relevant_tags:
            grouped.setdefault(definition.category, []).append(definition)

        ordered_categories = [category for category in TAG_CATEGORY_ORDER if category in grouped] + sorted(set(grouped) - set(TAG_CATEGORY_ORDER))
        for category in ordered_categories:
            with st.expander(category, expanded=category in {"Completeness", "Repayment", "Financial Analysis", "Structure"}):
                cols = st.columns(2)
                for idx, definition in enumerate(grouped[category]):
                    with cols[idx % 2]:
                        scopes[definition.tag_id] = st.selectbox(
                            f"{definition.label} applies to",
                            definition.allowed_scopes or ["section"],
                            index=(definition.allowed_scopes or ["section"]).index(definition.default_scope)
                            if definition.default_scope in (definition.allowed_scopes or ["section"])
                            else 0,
                            key=f"scope_{memo_id}_{section_id}_{definition.tag_id}",
                            format_func=lambda value: SCOPE_LABELS.get(str(value), str(value).title()),
                            help="Choose the part of the credit review this tag describes.",
                        )
                        if definition.facility_required or "facility" in (definition.allowed_scopes or []):
                            facility_assignments[definition.tag_id] = st.selectbox(
                                f"{definition.label} facility reviewed",
                                facility_options,
                                format_func=lambda value: facility_labels.get(value, value),
                                key=f"facility_{memo_id}_{section_id}_{definition.tag_id}",
                            )
                        values[definition.tag_id] = _render_tag_input(definition, key=f"input_{memo_id}_{section_id}_{definition.tag_id}")

        confidence = st.selectbox(
            "Overall confidence for this section",
            ["High", "Medium", "Low"],
            index=1,
            help="Rate how confident you are that the saved tags accurately reflect this section.",
        )
        tagger = st.text_input("Reviewer name", value=memo.get("reviewer", ""))
        save_batch = st.form_submit_button("Save This Section", type="primary")

    if save_batch:
        existing = [tag for tag in tags if not (tag.get("section_id") == section_id and tag.get("tag_id") in values)]
        new_records = []
        for definition in relevant_tags:
            value = values.get(definition.tag_id)
            empty = value in (None, "", []) or (definition.data_type == "number" and value == 0.0 and not definition.required)
            if empty:
                continue
            if definition.evidence_required and value not in {"Not addressed in memo", "Not applicable"} and not selected_evidence:
                st.error(f"{definition.label} requires evidence before it can be saved.")
                return
            facility_id = facility_assignments.get(definition.tag_id, "")
            if definition.facility_required and not facility_id and value not in {"Not addressed in memo", "Not applicable"}:
                st.error(f"{definition.label} requires a facility assignment.")
                return
            new_records.append(
                TagRecord(
                    tag_record_id=f"tag_{uuid4().hex[:10]}",
                    memo_id=memo_id,
                    section_id=section_id,
                    scope=scopes.get(definition.tag_id, definition.default_scope),  # type: ignore[arg-type]
                    facility_id=facility_id,
                    customer_id=str(memo.get("customer_id", "")),
                    tag_id=definition.tag_id,
                    tag_label=definition.label,
                    value=value,
                    confidence=confidence,  # type: ignore[arg-type]
                    evidence_ids=selected_evidence,
                    tagger=tagger,
                ).model_dump()
            )
        save_tags(workspace, memo_id, existing + new_records)
        st.success(f"Saved {len(new_records)} tag(s) for this section.")

    existing_section_tags = [tag for tag in load_tags(workspace, memo_id) if tag.get("section_id") == section_id]
    if existing_section_tags:
        display_rows = [
            {
                "Tag": tag.get("tag_label"),
                "Value": tag.get("value"),
                "Confidence": tag.get("confidence"),
                "Evidence Attached": len(tag.get("evidence_ids", [])),
            }
            for tag in existing_section_tags
        ]
        st.markdown("##### Saved Tags for This Section")
        st.dataframe(pd.DataFrame(display_rows), width="stretch", hide_index=True)


def _source_type_options() -> list[str]:
    return ["", *DEFAULT_OUTCOME_SOURCE_TYPES]


def _memo_evidence_label(evidence: dict[str, Any]) -> str:
    location = evidence.get("source_location") or f"p.{evidence.get('page_number', '')}"
    text = str(evidence.get("selected_text", "")).replace("\n", " ")
    return f"{location}: {text[:90]}"


def tag_outcomes_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Tag Outcomes")
    if not memo_id:
        blocked_step("Add a memo before tagging outcomes.", "Add Memo")
        return
    statuses = step_summary(workspace, memo_id)
    if statuses["Set Up Facilities"] != "Complete":
        blocked_step("Set up facilities before tagging outcomes.", "Set Up Facilities")
        return

    memo = load_memo_record(workspace, memo_id)
    facilities = [facility for facility in load_facilities(workspace, memo_id) if facility.get("status") == "Confirmed" or facility.get("reviewer_confirmed")]
    summaries = load_outcome_summaries(workspace, memo_id)
    outcome_events = load_outcome_events(workspace, memo_id)
    foreseeability_assessments = load_foreseeability_assessments(workspace, memo_id)
    memo_evidence = [item for item in load_evidence(workspace, memo_id) if item.get("evidence_type", "memo_evidence") == "memo_evidence"]
    summary_by_facility = {summary.get("facility_id", ""): summary for summary in summaries}
    events_by_facility: dict[str, list[dict[str, Any]]] = {}
    for event in outcome_events:
        events_by_facility.setdefault(str(event.get("facility_id", "")), []).append(event)
    assessments_by_event = {assessment.get("outcome_event_id", ""): assessment for assessment in foreseeability_assessments}
    event_type_options = ["", *[str(item["event_type"]) for item in DEFAULT_OUTCOME_EVENT_TYPES]]
    source_type_options = _source_type_options()
    source_confidence_options = ["High", "Medium", "Low"]
    foreseeability_options = ["Visible in memo", "Partially visible", "Hindsight-only", "Not assessed", "N/A"]

    st.caption(
        "Record what happened after credit was extended. If the deal is too new and nothing adverse has happened, mark it as not seasoned yet."
    )
    saved_summaries: list[dict[str, Any]] = []
    saved_events: list[dict[str, Any]] = []
    saved_assessments: list[dict[str, Any]] = []
    facility_closing_dates: dict[str, str] = {}
    with st.form(f"outcomes_{memo_id}"):
        for facility in facilities:
            facility_id = str(facility.get("facility_id"))
            existing_summary = summary_by_facility.get(facility_id, {})
            existing_events = events_by_facility.get(facility_id, [])
            existing_primary = derive_primary_outcome(existing_events)
            existing_assessment = assessments_by_event.get(str(existing_primary.get("outcome_event_id"))) if existing_primary else {}
            st.markdown(f"##### {facility.get('facility_name')} ({facility.get('facility_type')})")
            col1, col2, col3 = st.columns(3)
            with col1:
                availability_state = st.selectbox(
                    "What do we know about this facility outcome?",
                    DEFAULT_OUTCOME_AVAILABILITY_STATES,
                    index=DEFAULT_OUTCOME_AVAILABILITY_STATES.index(existing_summary.get("outcome_availability_state"))
                    if existing_summary.get("outcome_availability_state") in DEFAULT_OUTCOME_AVAILABILITY_STATES
                    else DEFAULT_OUTCOME_AVAILABILITY_STATES.index("Outcome Not Checked"),
                    key=f"outcome_state_{memo_id}_{facility_id}",
                )
                seasoning_months = st.number_input(
                    "Months needed before a clean outcome is seasoned",
                    min_value=1,
                    max_value=120,
                    value=int(existing_summary.get("seasoning_months") or 12),
                    key=f"seasoning_{memo_id}_{facility_id}",
                )
            with col2:
                closing_date = st.text_input(
                    "Facility closing date",
                    value=facility.get("closing_date", ""),
                    key=f"closing_date_{memo_id}_{facility_id}",
                    help="Use the date credit was legally extended.",
                )
                facility_closing_dates[facility_id] = closing_date
                summary_source_type = st.selectbox(
                    "Where was the outcome checked?",
                    source_type_options,
                    index=source_type_options.index(existing_summary.get("source_type")) if existing_summary.get("source_type") in source_type_options else 0,
                    key=f"summary_source_type_{memo_id}_{facility_id}",
                )
            with col3:
                summary_checked_date = st.text_input(
                    "Date outcome was checked",
                    value=existing_summary.get("source_checked_date", ""),
                    key=f"summary_checked_{memo_id}_{facility_id}",
                )
                summary_confidence = st.selectbox(
                    "Confidence in outcome information",
                    source_confidence_options,
                    index=source_confidence_options.index(existing_summary.get("source_confidence", "Medium"))
                    if existing_summary.get("source_confidence", "Medium") in source_confidence_options
                    else 1,
                    key=f"summary_confidence_{memo_id}_{facility_id}",
                )
            summary_note = st.text_area(
                "Outcome note",
                value=existing_summary.get("source_note", ""),
                key=f"summary_note_{memo_id}_{facility_id}",
                height=70,
                help="Required when outcome data is unavailable, source type is Reviewer attestation or Other, or source confidence is Low.",
            )

            event_rows = [
                {
                    "_outcome_event_id": event.get("outcome_event_id"),
                    "Event Type": event.get("event_type"),
                    "Event Date": event.get("event_date", ""),
                    "Source Type": event.get("source_type") or "",
                    "Source Checked Date": event.get("source_checked_date", ""),
                    "Source Confidence": event.get("source_confidence", "Medium"),
                    "Source Note": event.get("source_note", ""),
                }
                for event in existing_events
            ]
            event_columns = [
                "_outcome_event_id",
                "Event Type",
                "Event Date",
                "Source Type",
                "Source Checked Date",
                "Source Confidence",
                "Source Note",
            ]
            st.markdown("###### Adverse Outcome Events")
            st.caption("If more than one adverse event occurred, Tag Studio will treat the most severe observed event as primary.")
            edited_events = st.data_editor(
                pd.DataFrame(event_rows, columns=event_columns),
                num_rows="dynamic",
                width="stretch",
                key=f"outcome_events_{memo_id}_{facility_id}",
                column_config={
                    "_outcome_event_id": None,
                    "Event Type": st.column_config.SelectboxColumn("Event Type", options=event_type_options),
                    "Source Type": st.column_config.SelectboxColumn("Source Type", options=source_type_options),
                    "Source Confidence": st.column_config.SelectboxColumn("Source Confidence", options=source_confidence_options),
                },
            )
            facility_events: list[dict[str, Any]] = []
            for row in edited_events.fillna("").to_dict("records"):
                event_type = str(row.get("Event Type") or "").strip()
                if not event_type:
                    continue
                facility_events.append(
                    OutcomeEventRecord(
                        outcome_event_id=str(row.get("_outcome_event_id") or f"outcome_event_{uuid4().hex[:10]}"),
                        memo_id=memo_id,
                        facility_id=facility_id,
                        event_type=event_type,
                        event_date=str(row.get("Event Date") or ""),
                        severity_rank=outcome_event_severity(event_type),
                        source_type=str(row.get("Source Type")) if row.get("Source Type") else None,  # type: ignore[arg-type]
                        source_checked_date=str(row.get("Source Checked Date") or ""),
                        source_confidence=str(row.get("Source Confidence") or "Medium"),  # type: ignore[arg-type]
                        source_note=str(row.get("Source Note") or ""),
                    ).model_dump()
                )
            primary_event = derive_primary_outcome(facility_events)
            primary_event_id = str(primary_event.get("outcome_event_id", "")) if primary_event else ""
            if primary_event:
                st.caption(
                    f"Primary adverse outcome: {primary_event.get('event_type')} "
                    f"(severity {primary_event.get('severity_rank')})."
                )

            st.markdown("###### Warning Signs in the Memo")
            assessment = assessments_by_event.get(primary_event_id) if primary_event_id else existing_assessment or {}
            col_a, col_b = st.columns([1, 1.3])
            with col_a:
                foreseeability = st.selectbox(
                    "Could the issue be seen in the memo?",
                    foreseeability_options,
                    index=foreseeability_options.index(assessment.get("foreseeability", "Not assessed"))
                    if assessment.get("foreseeability", "Not assessed") in foreseeability_options
                    else 3,
                    key=f"foreseeability_{memo_id}_{facility_id}",
                )
            with col_b:
                memo_evidence_ids = st.multiselect(
                    "Memo evidence showing warning signs",
                    [str(item.get("evidence_id")) for item in memo_evidence],
                    default=[item for item in assessment.get("memo_evidence_ids", []) if item in {e.get("evidence_id") for e in memo_evidence}],
                    format_func=lambda evidence_id: _memo_evidence_label(next((item for item in memo_evidence if item.get("evidence_id") == evidence_id), {})),
                    key=f"foreseeability_evidence_{memo_id}_{facility_id}",
                    help="Required when foreseeability is Visible in memo or Partially visible.",
                )
            rationale = st.text_area(
                "Why this outcome was or was not visible",
                value=assessment.get("rationale", ""),
                key=f"outcome_rationale_{memo_id}_{facility_id}",
                height=80,
            )

            saved_events.extend(facility_events)
            saved_summaries.append(
                FacilityOutcomeSummaryRecord(
                    outcome_summary_id=str(existing_summary.get("outcome_summary_id") or f"outcome_summary_{facility_id}"),
                    memo_id=memo_id,
                    customer_id=str(memo.get("customer_id", "")),
                    facility_id=facility_id,
                    outcome_availability_state=availability_state,  # type: ignore[arg-type]
                    seasoning_months=int(seasoning_months),
                    primary_adverse_outcome=str(primary_event.get("event_type", "")) if primary_event else "",
                    primary_outcome_event_id=primary_event_id,
                    primary_event_date=str(primary_event.get("event_date", "")) if primary_event else "",
                    primary_severity_rank=int(primary_event.get("severity_rank", 0)) if primary_event else 0,
                    no_adverse_outcome_observed_date=summary_checked_date if availability_state == "No Adverse Outcome Observed" else "",
                    source_type=summary_source_type or None,  # type: ignore[arg-type]
                    source_checked_date=summary_checked_date,
                    source_confidence=summary_confidence,  # type: ignore[arg-type]
                    source_note=summary_note,
                    approval_ready=availability_state != "Outcome Not Checked",
                ).model_dump()
            )
            if primary_event_id:
                saved_assessments.append(
                    ForeseeabilityAssessmentRecord(
                        foreseeability_id=str(assessment.get("foreseeability_id") or f"foreseeability_{primary_event_id}"),
                        memo_id=memo_id,
                        facility_id=facility_id,
                        outcome_event_id=primary_event_id,
                        foreseeability=foreseeability,  # type: ignore[arg-type]
                        memo_evidence_ids=memo_evidence_ids,
                        rationale=rationale,
                    ).model_dump()
                )
            st.divider()
        submitted = st.form_submit_button("Save Outcome Review", type="primary")
    if submitted:
        updated_facilities = []
        for facility in load_facilities(workspace, memo_id):
            facility_id = str(facility.get("facility_id", ""))
            if facility_id in facility_closing_dates:
                facility["closing_date"] = facility_closing_dates[facility_id]
                facility["updated_at"] = utc_now()
            updated_facilities.append(facility)
        save_facilities(workspace, memo_id, updated_facilities)
        save_outcome_summaries(workspace, memo_id, saved_summaries)
        save_outcome_events(workspace, memo_id, saved_events)
        save_foreseeability_assessments(workspace, memo_id, saved_assessments)
        st.success("Outcome review saved.")
        go_to_step("Quality Check")


def quality_check_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Quality Check")
    st.caption("Confirm the memo is complete enough to approve for the training dataset.")
    if not memo_id:
        blocked_step("Add a memo before running the quality check.", "Add Memo")
        return

    findings, metrics = quality_findings(workspace, memo_id)
    review = load_review(workspace, memo_id)

    cols = st.columns(5)
    for col, (label, value) in zip(
        cols,
        [
            ("Pages Checked", f"{metrics['pages_checked']} / {metrics['pages_total']}"),
            ("Memo Sections", f"{metrics['sections_confirmed']} / {metrics['sections_total']}"),
            ("Facilities", f"{metrics['facilities_confirmed']} / {metrics['facilities_total']}"),
            ("Outcomes", metrics["outcomes_total"]),
            ("Review Status", STATUS_LABELS.get(review.get("status", "Draft"), review.get("status", "Draft"))),
        ],
        strict=True,
    ):
        col.markdown(f'<div class="metric-card"><div class="label">{label}</div><div class="value">{value}</div></div>', unsafe_allow_html=True)

    st.markdown("##### Readiness")
    if findings:
        st.warning("This memo is not ready for the training dataset.")
        for finding in findings:
            st.write(f"- {finding}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Return to Review Memo Sections"):
                go_to_step("Review Memo Sections")
        with col2:
            if st.button("Return to Tag Credit Review"):
                go_to_step("Tag Credit Review")
        return

    st.success("This memo is ready to approve for the training dataset.")
    with st.form(f"approve_{memo_id}"):
        reviewer = st.text_input("Reviewer name", value=review.get("reviewer", load_memo_record(workspace, memo_id).get("reviewer", "")))
        adjudicator = st.text_input("Approver", value=review.get("adjudicator", ""))
        if reviewer and adjudicator and reviewer == adjudicator:
            st.warning("You are approving your own review. This is allowed, and the approval will be audited.")
        notes = st.text_area("Approval notes", value=review.get("adjudication_notes", ""), height=110)
        approved = st.form_submit_button(
            "Approve for Training Dataset",
            type="primary",
            help="Approve only when required sections, tags, and evidence are complete enough to be used as training data.",
        )
    if approved:
        memo = load_memo_record(workspace, memo_id)
        schema_hash = active_schema_hash(workspace)
        memo.update({"schema_version": SCHEMA_VERSION, "schema_hash": schema_hash})
        save_memo_record(workspace, memo_id, memo)
        write_json(
            memo_dir(workspace, memo_id) / "schema" / "schema_snapshot.json",
            {
                **active_schema_payload(workspace),
                "schema_hash": schema_hash,
                "created_at": utc_now(),
            },
        )
        review.update(
            {
                "memo_id": memo_id,
                "status": "Approved Gold",
                "assignment_status": "Approved for Training Dataset",
                "reviewer": reviewer,
                "adjudicator": adjudicator,
                "adjudication_notes": notes,
                "approved_at": utc_now(),
                "schema_version": SCHEMA_VERSION,
                "schema_hash": schema_hash,
            }
        )
        save_review(workspace, memo_id, review)
        append_audit(workspace, memo_id, "approved_for_training_dataset", review)
        go_to_step("Download Results")


def download_results_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Download Results")
    st.caption("Create the reviewer workbook, training files, and audit package for the approved memo set.")
    if not memo_id:
        blocked_step("Add a memo before downloading results.", "Add Memo")
        return

    review = load_review(workspace, memo_id)
    if review.get("status") != "Approved Gold":
        st.warning("Approve this memo in Quality Check before downloading final results.")
        if st.button("Go to Quality Check", type="primary"):
            go_to_step("Quality Check")
        return

    st.markdown("##### Available Downloads")
    download_state_key = f"prepared_downloads_{memo_id}"
    prepared = st.session_state.setdefault(download_state_key, {})
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown('<div class="soft-panel"><b>Review Workbook</b><br><span class="small-muted">Excel workbook for human review.</span></div>', unsafe_allow_html=True)
        if st.button(
            "Prepare Review Workbook",
            type="primary",
            help="Create an Excel workbook for human QA and review.",
        ):
            prepared["review_workbook"] = str(export_excel(workspace, include_only_approved=True))
        review_path = Path(prepared["review_workbook"]) if prepared.get("review_workbook") else None
        if review_path and review_path.exists():
            st.download_button("Download Review Workbook", data=review_path.read_bytes(), file_name=review_path.name)
    with col2:
        st.markdown('<div class="soft-panel"><b>Training File</b><br><span class="small-muted">Structured files for the project team.</span></div>', unsafe_allow_html=True)
        if st.button(
            "Prepare Training File",
            type="primary",
            help="Create the training files from approved memo reviews.",
        ):
            paths = export_jsonl(workspace, include_only_approved=True)
            prepared["span_training"] = str(paths["spans"])
            prepared["section_training"] = str(paths["sections"])
            prepared["memo_training"] = str(paths["memos"])
            prepared["outcome_training"] = str(paths["outcomes"])
            prepared["training_audit"] = str(paths["audit"])
            prepared["training_manifest"] = str(paths["manifest"])
        span_training_path = Path(prepared["span_training"]) if prepared.get("span_training") else None
        section_training_path = Path(prepared["section_training"]) if prepared.get("section_training") else None
        memo_training_path = Path(prepared["memo_training"]) if prepared.get("memo_training") else None
        outcome_training_path = Path(prepared["outcome_training"]) if prepared.get("outcome_training") else None
        training_audit_path = Path(prepared["training_audit"]) if prepared.get("training_audit") else None
        training_manifest_path = Path(prepared["training_manifest"]) if prepared.get("training_manifest") else None
        if span_training_path and span_training_path.exists():
            st.download_button("Download Evidence Training File", data=span_training_path.read_bytes(), file_name=span_training_path.name)
        if section_training_path and section_training_path.exists():
            st.download_button("Download Section Training File", data=section_training_path.read_bytes(), file_name=section_training_path.name)
        if memo_training_path and memo_training_path.exists():
            st.download_button("Download Memo Training File", data=memo_training_path.read_bytes(), file_name=memo_training_path.name)
        if outcome_training_path and outcome_training_path.exists():
            st.download_button("Download Outcome Training File", data=outcome_training_path.read_bytes(), file_name=outcome_training_path.name)
        if training_audit_path and training_audit_path.exists():
            st.download_button("Download Training Audit Trail", data=training_audit_path.read_bytes(), file_name=training_audit_path.name)
        if training_manifest_path and training_manifest_path.exists():
            st.download_button("Download Training Summary", data=training_manifest_path.read_bytes(), file_name=training_manifest_path.name)
    with col3:
        st.markdown('<div class="soft-panel"><b>Audit Package</b><br><span class="small-muted">Traceability package for QA.</span></div>', unsafe_allow_html=True)
        if st.button(
            "Prepare Audit Package",
            help="Create a traceability package showing what was reviewed, tagged, and approved.",
        ):
            prepared["audit_package"] = str(export_memo_bundle(workspace, memo_id))
        audit_path = Path(prepared["audit_package"]) if prepared.get("audit_package") else None
        if audit_path and audit_path.exists():
            st.download_button("Download Audit Package", data=audit_path.read_bytes(), file_name=audit_path.name)
