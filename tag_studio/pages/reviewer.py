from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

from tag_studio.app_config import STATUS_LABELS, TAG_CATEGORY_ORDER
from tag_studio.defaults import DEFAULT_FACILITY_TYPES, DEFAULT_MEMO_TYPES
from tag_studio.document_intelligence import (
    dependency_status,
    load_extraction_warnings,
    load_page_quality,
    load_page_text,
    load_section_candidates,
    run_document_intelligence,
    save_page_quality,
    save_page_text,
    summarize_page_quality,
)
from tag_studio.exporters import export_excel, export_jsonl, export_memo_bundle
from tag_studio.models import EvidenceRecord, TagDefinition, TagRecord, utc_now
from tag_studio.sectioning import propose_sections, required_section_gaps
from tag_studio.services import (
    candidate_for_section,
    load_section_defs,
    memo_display_name,
    quality_findings,
    rebuild_sections_from_page_text,
    save_section_defs,
    step_summary,
    tags_for_section,
    text_quality_complete,
)
from tag_studio.storage import (
    append_audit,
    create_memo_workspace,
    list_memo_ids,
    load_evidence,
    load_memo_record,
    load_review,
    load_sections,
    load_tags,
    memo_dir,
    read_json,
    save_evidence,
    save_memo_record,
    save_review,
    save_sections,
    save_tags,
    slugify,
)
from tag_studio.ui_components import badge, blocked_step, extraction_message, go_to_step


def add_memo_page(workspace: Path) -> None:
    st.subheader("Add Memo")

    memo_ids = list_memo_ids(workspace)
    if memo_ids:
        st.markdown("##### Current Memo")
        labels = {memo_id: memo_display_name(workspace, memo_id) for memo_id in memo_ids}
        active = st.session_state.get("active_memo_id") or memo_ids[0]
        active = st.selectbox(
            "Choose a memo to work on",
            memo_ids,
            index=memo_ids.index(active) if active in memo_ids else 0,
            format_func=lambda memo_id: labels.get(memo_id, memo_id),
        )
        st.session_state["active_memo_id"] = active

    st.markdown("##### Add a New Credit Memo")
    deps = dependency_status()
    if not deps.get("tesseract"):
        st.warning(
            "Scanned memo setup is incomplete. Digital PDFs can still be read, but scanned PDFs may need local OCR support "
            "or manual text correction before Tag Studio can reliably read page images."
        )
    with st.form("add_memo_form"):
        uploaded = st.file_uploader(
            "Credit memo PDF",
            type=["pdf"],
            help="Choose the memo you want reviewed and tagged. Use a PDF that contains no information outside the review packet.",
        )
        borrower = st.text_input("Borrower name or internal borrower ID")
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
        st.error("Choose a credit memo PDF before continuing.")
        return

    memo_id = f"memo_{slugify(Path(uploaded.name).stem)}_{uuid4().hex[:8]}"
    record = create_memo_workspace(
        workspace=workspace,
        pdf_bytes=uploaded.getvalue(),
        file_name=uploaded.name,
        memo_id=memo_id,
        memo_type=memo_type,
        facility_type=facility_type,
        borrower_name_or_hash=borrower,
        reviewer=reviewer,
    )

    with st.spinner("Reading memo text..."):
        try:
            intelligence = run_document_intelligence(workspace, memo_id, load_section_defs(workspace))
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
            definitions=load_section_defs(workspace),
            extraction_method=method,
        )
        save_sections(workspace, memo_id, [section.model_dump() for section in proposed])

    st.session_state["active_memo_id"] = memo_id
    extraction_message(method, warning, len(page_text))
    st.session_state["selected_step"] = "Review Text Quality"
    st.rerun()


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
                    intelligence = run_document_intelligence(workspace, memo_id, load_section_defs(workspace))
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
                        definitions=load_section_defs(workspace),
                        extraction_method=intelligence["method"],
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
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "Save Page Review",
                type="primary",
                help="Save corrected page text and mark this page as reviewed for section mapping.",
            ):
                for record in page_text:
                    if int(record["page_number"]) == selected_page_number:
                        record["text"] = corrected_text
                for record in page_quality:
                    if int(record["page_number"]) == selected_page_number:
                        record["reviewer_confirmed"] = True
                        record["reviewer_notes"] = notes
                        if record.get("status") == "Hard to Read" and corrected_text.strip():
                            record["status"] = "Needs Review"
                save_page_text(workspace, memo_id, page_text)
                save_page_quality(workspace, memo_id, page_quality)
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
                save_page_quality(workspace, memo_id, page_quality)
                append_audit(workspace, memo_id, "page_quality_marked_reviewed", {"page_number": selected_page_number})
                st.rerun()

    remaining = [record for record in load_page_quality(workspace, memo_id) if not record.get("reviewer_confirmed") and record.get("status") != "Ready"]
    st.markdown("##### Next Action")
    if remaining:
        st.warning(f"{len(remaining)} page(s) still need review before sections are confirmed.")
    else:
        st.success("Text quality review is complete.")
        if st.button("Continue to Confirm Sections", type="primary"):
            go_to_step("Confirm Sections")


def add_missing_required_sections(workspace: Path, memo_id: str) -> None:
    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    gaps = required_section_gaps(sections, load_section_defs(workspace), memo.get("memo_type", ""), memo.get("facility_type", ""))
    if not gaps:
        return
    st.warning("These required sections were not found: " + ", ".join(gap.display_name for gap in gaps))
    if st.button("Add Missing Section Records"):
        for gap in gaps:
            sections.append(
                {
                    "section_id": f"section_{len(sections) + 1:03}",
                    "memo_id": memo_id,
                    "canonical_section_id": gap.section_id,
                    "canonical_section_name": gap.display_name,
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
        st.success("Missing section records added.")
        st.rerun()


def confirm_sections_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Confirm Sections")
    if not memo_id:
        blocked_step("Add a memo before confirming sections.", "Add Memo")
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
    section_options = list(definitions.keys())
    candidates = load_section_candidates(workspace, memo_id)

    if not text_quality_complete(workspace, memo_id):
        blocked_step("Review the memo text quality before confirming sections.", "Review Text Quality")
        return

    add_missing_required_sections(workspace, memo_id)

    st.markdown("##### Review Detected Sections")
    saved_sections: list[dict[str, Any]] = []
    remember_aliases: dict[str, list[str]] = {}
    with st.form(f"confirm_sections_{memo_id}"):
        for idx, section in enumerate(sections):
            current_id = section.get("canonical_section_id")
            if current_id not in definitions:
                current_id = section_options[0]
            st.markdown('<div class="review-card">', unsafe_allow_html=True)
            st.markdown(f"**Original memo heading:** {section.get('original_header', 'Unlabeled section')}")
            st.caption(f"Pages {section.get('page_start')} to {section.get('page_end')}")
            candidate = candidate_for_section(section, candidates)
            if candidate:
                alternates = candidate.get("alternate_matches", [])
                alt_text = ""
                if alternates:
                    alt_text = " Alternate: " + ", ".join(
                        f"{item.get('section_name')} ({int(float(item.get('confidence', 0)) * 100)}%)"
                        for item in alternates[:2]
                    )
                st.markdown(
                    '<div class="section-suggestion">'
                    f'{badge("Suggestion", "Ready")} '
                    f'{escape(str(candidate.get("suggested_section_name", "")))} '
                    f'({int(float(candidate.get("confidence", 0)) * 100)}% confidence)<br>'
                    f'<span class="small-muted">{escape(str(candidate.get("reason", "")))}{escape(alt_text)}</span>'
                    "</div>",
                    unsafe_allow_html=True,
                )
            col1, col2 = st.columns([1.2, 1])
            with col1:
                canonical_id = st.selectbox(
                    "Standard Memo Section",
                    section_options,
                    index=section_options.index(current_id),
                    format_func=lambda value: definitions[value].display_name,
                    key=f"confirm_standard_{memo_id}_{section.get('section_id')}_{idx}",
                    help="Choose the standard section name that best matches the memo heading, even if the memo uses different wording.",
                )
            with col2:
                status = st.radio(
                    "Section status",
                    ["Confirmed", "Needs more review", "Missing from memo"],
                    index=2 if section.get("missing_required") else (0 if section.get("reviewer_confirmed") else 1),
                    horizontal=True,
                    key=f"confirm_status_{memo_id}_{section.get('section_id')}_{idx}",
                    help="Confirm the section when the text and standard section are correct. Use missing only when the memo does not address a required topic.",
                )
            remember = st.checkbox(
                "Remember this heading next time",
                value=False,
                key=f"remember_alias_{memo_id}_{section.get('section_id')}_{idx}",
                help="Save this memo's heading as an accepted name for the selected standard section in future memos.",
            )
            text = st.text_area(
                "Section text",
                value=section.get("text", ""),
                height=135,
                key=f"confirm_text_{memo_id}_{section.get('section_id')}_{idx}",
            )
            st.markdown("</div>", unsafe_allow_html=True)
            saved_sections.append(
                {
                    **section,
                    "canonical_section_id": canonical_id,
                    "canonical_section_name": definitions[canonical_id].display_name,
                    "reviewer_confirmed": status in {"Confirmed", "Missing from memo"},
                    "missing_required": status == "Missing from memo",
                    "text": text or ("Not addressed in memo." if status == "Missing from memo" else ""),
                }
            )
            if remember and section.get("original_header") and section.get("original_header") != "Not found in memo":
                remember_aliases.setdefault(canonical_id, []).append(str(section["original_header"]))

        submitted = st.form_submit_button("Save Section Review", type="primary")

    if submitted:
        if remember_aliases:
            updated_defs = []
            for definition in section_defs:
                aliases = list(definition.aliases)
                for alias in remember_aliases.get(definition.section_id, []):
                    if alias not in aliases:
                        aliases.append(alias)
                updated_defs.append(definition.model_copy(update={"aliases": aliases}))
            save_section_defs(workspace, updated_defs)
        save_sections(workspace, memo_id, saved_sections)
        if all(section.get("reviewer_confirmed") for section in saved_sections):
            st.session_state["selected_step"] = "Tag Credit Review"
            st.rerun()
        st.success("Section review saved. Sections still needing review remain marked.")


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


def tag_credit_review_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Tag Credit Review")
    if not memo_id:
        blocked_step("Add a memo before tagging the credit review.", "Add Memo")
        return

    statuses = step_summary(workspace, memo_id)
    if statuses["Confirm Sections"] != "Complete":
        blocked_step("Confirm the memo sections before tagging the credit review.", "Confirm Sections")
        return

    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    tags = load_tags(workspace, memo_id)
    evidence = load_evidence(workspace, memo_id)

    section_labels = {
        section["section_id"]: f"{section.get('canonical_section_name')} - p.{section.get('page_start')}-{section.get('page_end')}"
        for section in sections
    }
    section_id = st.selectbox("Section to review", list(section_labels.keys()), format_func=lambda value: section_labels[value])
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
            "Correction or note",
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
        if st.button("Add Evidence", key=f"add_evidence_{memo_id}_{section_id}"):
            evidence_text = manual_evidence_text.strip() or selected_line_text.strip()
            if not evidence_text:
                st.error("Select evidence lines or enter a correction before adding evidence.")
            else:
                record = EvidenceRecord(
                    evidence_id=f"ev_{uuid4().hex[:10]}",
                    memo_id=memo_id,
                    section_id=section_id,
                    page_number=int(section.get("page_start", 1)),
                    selected_text=evidence_text,
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
        selected_evidence = st.multiselect("Attach evidence to saved tags", list(evidence_options.keys()), format_func=lambda value: evidence_options[value])

    st.markdown("##### Credit Tags")
    with st.form(f"tag_form_{memo_id}_{section_id}"):
        values = {}
        grouped: dict[str, list[TagDefinition]] = {}
        for definition in relevant_tags:
            grouped.setdefault(definition.category, []).append(definition)

        ordered_categories = [category for category in TAG_CATEGORY_ORDER if category in grouped] + sorted(set(grouped) - set(TAG_CATEGORY_ORDER))
        for category in ordered_categories:
            with st.expander(category, expanded=category in {"Completeness", "Repayment", "Financial Analysis", "Structure"}):
                cols = st.columns(2)
                for idx, definition in enumerate(grouped[category]):
                    with cols[idx % 2]:
                        values[definition.tag_id] = _render_tag_input(definition, key=f"input_{memo_id}_{section_id}_{definition.tag_id}")

        confidence = st.selectbox(
            "Overall confidence for this section",
            ["High", "Medium", "Low"],
            index=1,
            help="Rate how confident you are that the saved tags accurately reflect this section.",
        )
        tagger = st.text_input("Reviewer", value=memo.get("reviewer", ""))
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
            new_records.append(
                TagRecord(
                    tag_record_id=f"tag_{uuid4().hex[:10]}",
                    memo_id=memo_id,
                    section_id=section_id,
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


def quality_check_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Quality Check")
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
            ("Sections Confirmed", f"{metrics['sections_confirmed']} / {metrics['sections_total']}"),
            ("Saved Tags", metrics["tags_total"]),
            ("Evidence Items", metrics["evidence_total"]),
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
            if st.button("Return to Confirm Sections"):
                go_to_step("Confirm Sections")
        with col2:
            if st.button("Return to Tag Credit Review"):
                go_to_step("Tag Credit Review")
        return

    st.success("This memo is ready to approve for the training dataset.")
    with st.form(f"approve_{memo_id}"):
        reviewer = st.text_input("Reviewer", value=review.get("reviewer", load_memo_record(workspace, memo_id).get("reviewer", "")))
        adjudicator = st.text_input("Approver", value=review.get("adjudicator", ""))
        notes = st.text_area("Approval notes", value=review.get("adjudication_notes", ""), height=110)
        approved = st.form_submit_button(
            "Approve for Training Dataset",
            type="primary",
            help="Approve only when required sections, tags, and evidence are complete enough to be used as training data.",
        )
    if approved:
        review.update(
            {
                "memo_id": memo_id,
                "status": "Approved Gold",
                "reviewer": reviewer,
                "adjudicator": adjudicator,
                "adjudication_notes": notes,
                "approved_at": utc_now(),
            }
        )
        save_review(workspace, memo_id, review)
        append_audit(workspace, memo_id, "approved_for_training_dataset", review)
        st.session_state["selected_step"] = "Download Results"
        st.rerun()


def download_results_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Download Results")
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
        st.markdown('<div class="soft-panel"><b>Training File</b><br><span class="small-muted">Structured file for the model tuning pipeline.</span></div>', unsafe_allow_html=True)
        if st.button(
            "Prepare Training File",
            type="primary",
            help="Create the structured training files from approved memo records.",
        ):
            paths = export_jsonl(workspace, include_only_approved=True)
            prepared["section_training"] = str(paths["sections"])
            prepared["memo_training"] = str(paths["memos"])
        section_training_path = Path(prepared["section_training"]) if prepared.get("section_training") else None
        memo_training_path = Path(prepared["memo_training"]) if prepared.get("memo_training") else None
        if section_training_path and section_training_path.exists():
            st.download_button("Download Section Training File", data=section_training_path.read_bytes(), file_name=section_training_path.name)
        if memo_training_path and memo_training_path.exists():
            st.download_button("Download Memo Training File", data=memo_training_path.read_bytes(), file_name=memo_training_path.name)
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
