from __future__ import annotations

import sys
from html import escape
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from tag_studio.defaults import DEFAULT_FACILITY_TYPES, DEFAULT_MEMO_TYPES, SCHEMA_VERSION
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
from tag_studio.extraction import tesseract_available
from tag_studio.models import EvidenceRecord, SectionDefinition, TagDefinition, TagRecord, utc_now
from tag_studio.sectioning import propose_section_candidates, propose_sections, required_section_gaps
from tag_studio.storage import (
    DEFAULT_WORKSPACE,
    append_audit,
    config_path,
    create_memo_workspace,
    ensure_workspace,
    hydrate_memo_from_remote,
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
    storage_readiness,
    storage_status,
    write_json,
)


st.set_page_config(page_title="Tag Studio", page_icon="TS", layout="wide")


WIZARD_STEPS = [
    "Add Memo",
    "Review Text Quality",
    "Confirm Sections",
    "Tag Credit Review",
    "Quality Check",
    "Download Results",
]

STATUS_LABELS = {
    "Draft": "In Progress",
    "Ready for Review": "Ready for Review",
    "Changes Requested": "Changes Needed",
    "Approved Gold": "Approved for Training Dataset",
    "Exported": "Downloaded",
}

TAG_CATEGORY_ORDER = [
    "Completeness",
    "Repayment",
    "Financial Analysis",
    "Structure",
    "Collateral",
    "Policy",
    "Risk Assessment",
    "Structure Enhancement",
    "Review Context",
    "Business Risk",
    "Mitigants",
    "Risk Rating",
    "Scoring",
    "Outcome",
]


CSS = """
<style>
body { background: #f6f8fb; }
.block-container { padding-top: 1.4rem; max-width: 1380px; }
[data-testid="stSidebar"] { background: #102033; }
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {
  color: #edf4ff !important;
}
.tag-title {
  padding: 1.1rem 1.3rem;
  border: 1px solid #d7e2ec;
  border-radius: 10px;
  background: linear-gradient(135deg, #12324c, #2f6975);
  color: white;
  margin-bottom: 1rem;
}
.tag-title h1 { margin: 0; font-size: 2rem; letter-spacing: 0; }
.tag-title p { margin: .35rem 0 0 0; color: #dcebf5; }
.progress-wrap {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: .65rem;
  margin: .8rem 0 1.1rem 0;
}
.step-card {
  border: 1px solid #d8e2ec;
  border-radius: 8px;
  background: #ffffff;
  padding: .75rem .85rem;
  min-height: 76px;
}
.step-card.complete { border-color: #7bb38b; background: #f2faf4; }
.step-card.active { border-color: #2f6975; box-shadow: 0 0 0 2px rgba(47,105,117,.14); }
.step-card.needs { border-color: #e1a640; background: #fff8e8; }
.step-num { color: #617083; font-size: .76rem; text-transform: uppercase; }
.step-name { color: #172333; font-weight: 720; margin-top: .18rem; }
.step-state { color: #546376; font-size: .82rem; margin-top: .24rem; }
.metric-card {
  border: 1px solid #d8e1ea;
  border-radius: 8px;
  background: white;
  padding: .85rem;
  min-height: 84px;
}
.metric-card .label { color: #5b6b7f; font-size: .78rem; text-transform: uppercase; }
.metric-card .value { color: #172333; font-size: 1.15rem; font-weight: 700; margin-top: .35rem; }
.review-card {
  border: 1px solid #dbe4ed;
  border-radius: 8px;
  background: #ffffff;
  padding: 1rem;
  margin-bottom: .75rem;
}
.soft-panel {
  border: 1px solid #dbe4ed;
  border-radius: 8px;
  background: #fbfdff;
  padding: .9rem;
}
.status-pill {
  display: inline-block;
  padding: .22rem .58rem;
  border-radius: 999px;
  background: #e8f1f8;
  color: #17324d;
  font-size: .82rem;
  font-weight: 650;
}
.status-ready { background: #e7f7ed; color: #176b3a; }
.status-review { background: #fff3cf; color: #7a4c00; }
.status-hard { background: #ffe4e4; color: #9b1c1c; }
.status-blue { background: #e8f1ff; color: #1c4f8f; }
.quality-card {
  border: 1px solid #dbe4ed;
  border-radius: 8px;
  background: #ffffff;
  padding: .75rem;
  min-height: 122px;
  margin-bottom: .5rem;
}
.quality-card.active { border-color: #2f6975; box-shadow: 0 0 0 2px rgba(47,105,117,.12); }
.page-thumb {
  border: 1px solid #d8e2ec;
  border-radius: 8px;
  background: #ffffff;
  padding: .45rem;
}
.section-suggestion {
  border-left: 4px solid #3b82f6;
  background: #f5f9ff;
  padding: .55rem .75rem;
  border-radius: 6px;
  margin: .35rem 0 .6rem 0;
}
.small-muted { color: #637083; font-size: .88rem; }
</style>
"""


def show_header() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="tag-title">
          <h1>Tag Studio</h1>
          <p>Credit memo tagging workbench for review-ready training data.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_section_defs(workspace: Path) -> list[SectionDefinition]:
    return [SectionDefinition(**row) for row in read_json(config_path(workspace, "section_schema.json"), [])]


def save_section_defs(workspace: Path, sections: list[SectionDefinition]) -> None:
    write_json(config_path(workspace, "section_schema.json"), [section.model_dump() for section in sections])


def load_tag_defs(workspace: Path) -> list[TagDefinition]:
    return [TagDefinition(**row) for row in read_json(config_path(workspace, "tag_schema.json"), [])]


def save_tag_defs(workspace: Path, tags: list[TagDefinition]) -> None:
    write_json(config_path(workspace, "tag_schema.json"), [tag.model_dump() for tag in tags])


def get_workspace() -> Path:
    workspace = DEFAULT_WORKSPACE
    ready, message = storage_readiness()
    if not ready:
        st.error("Tag Studio storage is not ready.")
        st.write(message)
        st.info("Ask a Shakudo administrator to check the storage environment settings, then restart Tag Studio.")
        st.stop()
    ensure_workspace(workspace)
    return workspace


def memo_display_name(workspace: Path, memo_id: str) -> str:
    memo = load_memo_record(workspace, memo_id)
    review = load_review(workspace, memo_id)
    borrower = memo.get("borrower_name_or_hash") or Path(memo.get("source_file_name", memo_id)).stem
    status = STATUS_LABELS.get(review.get("status", "Draft"), review.get("status", "Draft"))
    return f"{borrower} - {memo.get('memo_type', 'Memo')} - {status}"


def choose_memo(workspace: Path) -> str | None:
    memo_ids = list_memo_ids(workspace)
    if not memo_ids:
        st.sidebar.info("No memos have been added yet.")
        return None

    active = st.session_state.get("active_memo_id")
    index = memo_ids.index(active) if active in memo_ids else 0
    selected = st.sidebar.selectbox(
        "Current Memo",
        memo_ids,
        index=index,
        format_func=lambda memo_id: memo_display_name(workspace, memo_id),
    )
    st.session_state["active_memo_id"] = selected
    hydrate_memo_from_remote(workspace, selected)
    return selected


def section_defs_by_id(workspace: Path) -> dict[str, SectionDefinition]:
    return {section.section_id: section for section in load_section_defs(workspace)}


def step_summary(workspace: Path, memo_id: str | None) -> dict[str, str]:
    if not memo_id:
        return {
            "Add Memo": "Needs Review",
            "Review Text Quality": "Not Started",
            "Confirm Sections": "Not Started",
            "Tag Credit Review": "Not Started",
            "Quality Check": "Not Started",
            "Download Results": "Not Started",
        }

    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    tags = load_tags(workspace, memo_id)
    review = load_review(workspace, memo_id)
    section_defs = load_section_defs(workspace)
    gaps = required_section_gaps(sections, section_defs, memo.get("memo_type", ""), memo.get("facility_type", ""))

    quality_complete = text_quality_complete(workspace, memo_id)
    sections_complete = bool(sections) and not gaps and all(section.get("reviewer_confirmed") for section in sections)
    tags_complete = bool(tags) and any(tag.get("evidence_ids") for tag in tags)
    approved = review.get("status") == "Approved Gold"
    exported = review.get("status") == "Exported"

    return {
        "Add Memo": "Complete",
        "Review Text Quality": "Complete" if quality_complete else "Needs Review",
        "Confirm Sections": "Complete" if sections_complete else ("Needs Review" if quality_complete else "Not Started"),
        "Tag Credit Review": "Complete" if tags_complete else ("Needs Review" if sections_complete else "Not Started"),
        "Quality Check": "Complete" if approved else ("Needs Review" if tags_complete else "Not Started"),
        "Download Results": "Complete" if exported else ("Needs Review" if approved else "Not Started"),
    }


def show_progress(current_step: str, statuses: dict[str, str]) -> None:
    cards = []
    for idx, step in enumerate(WIZARD_STEPS, start=1):
        status = statuses.get(step, "Not Started")
        cls = "step-card"
        if status == "Complete":
            cls += " complete"
        elif status == "Needs Review":
            cls += " needs"
        if step == current_step:
            cls += " active"
        cards.append(
            f'<div class="{cls}">'
            f'<div class="step-num">Step {idx}</div>'
            f'<div class="step-name">{step}</div>'
            f'<div class="step-state">{status}</div>'
            "</div>"
        )
    st.markdown(f'<div class="progress-wrap">{"".join(cards)}</div>', unsafe_allow_html=True)


def go_to_step(step: str) -> None:
    st.session_state["selected_step"] = step
    st.rerun()


def blocked_step(message: str, next_step: str) -> None:
    st.info(message)
    if st.button(f"Go to {next_step}", type="primary"):
        go_to_step(next_step)


def extraction_message(method: str, warning: str | None, page_count: int) -> None:
    if warning:
        st.warning("Some pages may need review. Check extracted text before confirming memo sections.")
    elif method == "manual_correction":
        st.warning("Could not read scanned text. Install OCR support or correct the text manually.")
    else:
        st.success(f"Text read successfully from {page_count} page(s).")


def status_class(status: str) -> str:
    if status == "Ready":
        return "status-ready"
    if status == "Hard to Read":
        return "status-hard"
    if status in {"Possible Handwriting", "Table Heavy"}:
        return "status-blue"
    return "status-review"


def badge(label: str, status: str) -> str:
    return f'<span class="status-pill {status_class(status)}">{label}</span>'


def text_quality_complete(workspace: Path, memo_id: str) -> bool:
    page_quality = load_page_quality(workspace, memo_id)
    return bool(page_quality) and all(record.get("reviewer_confirmed") or record.get("status") == "Ready" for record in page_quality)


def candidate_for_section(section: dict, candidates: list[dict]) -> dict | None:
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


def add_memo_page(workspace: Path) -> None:
    st.subheader("Add Memo")

    memo_ids = list_memo_ids(workspace)
    if memo_ids:
        st.markdown("##### Current Memo")
        active = st.session_state.get("active_memo_id") or memo_ids[0]
        active = st.selectbox(
            "Choose a memo to work on",
            memo_ids,
            index=memo_ids.index(active) if active in memo_ids else 0,
            format_func=lambda memo_id: memo_display_name(workspace, memo_id),
        )
        st.session_state["active_memo_id"] = active

    st.markdown("##### Add a New Credit Memo")
    deps = dependency_status()
    if not deps.get("tesseract"):
        st.warning(
            "Scanned memo setup is incomplete. Digital PDFs can still be read, but scanned PDFs need the Tesseract OCR engine "
            "before Tag Studio can reliably read page images."
        )
    with st.form("add_memo_form"):
        uploaded = st.file_uploader("Credit memo PDF", type=["pdf"])
        borrower = st.text_input("Borrower name or internal borrower ID")
        col1, col2 = st.columns(2)
        with col1:
            memo_type = st.selectbox("Memo type", DEFAULT_MEMO_TYPES, index=1)
        with col2:
            facility_type = st.selectbox("Facility type", DEFAULT_FACILITY_TYPES, index=7)
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
        ("OCR Warnings", len([warning for warning in warnings if not warning.get("resolved")]))
    ]
    for col, (label, value) in zip(cols, metrics):
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
                f'<b>Page {page_number}</b><br>{badge(status, status)}'
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
            "Correct this text if the page image shows OCR mistakes.",
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
            if st.button("Save Page Review", type="primary"):
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
            if st.button("Mark Page Reviewed"):
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
    saved_sections: list[dict] = []
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
                )
            with col2:
                status = st.radio(
                    "Section status",
                    ["Confirmed", "Needs more review", "Missing from memo"],
                    index=2 if section.get("missing_required") else (0 if section.get("reviewer_confirmed") else 1),
                    horizontal=True,
                    key=f"confirm_status_{memo_id}_{section.get('section_id')}_{idx}",
                )
            remember = st.checkbox(
                "Remember this heading next time",
                value=False,
                key=f"remember_alias_{memo_id}_{section.get('section_id')}_{idx}",
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


def tags_for_section(workspace: Path, section: dict) -> list[TagDefinition]:
    tag_defs = load_tag_defs(workspace)
    section_defs = section_defs_by_id(workspace)
    expected_ids = set(section_defs.get(section.get("canonical_section_id"), SectionDefinition(section_id="unknown", display_name="Unknown")).expected_tag_ids)
    relevant = [tag for tag in tag_defs if tag.tag_id in expected_ids]
    return relevant or tag_defs


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
        )
        citation_confidence = st.selectbox("Citation confidence", ["High", "Medium", "Low"], index=1, key=f"citation_confidence_{memo_id}_{section_id}")
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

        confidence = st.selectbox("Overall confidence for this section", ["High", "Medium", "Low"], index=1)
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


def quality_findings(workspace: Path, memo_id: str) -> tuple[list[str], dict[str, int]]:
    findings: list[str] = []
    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    section_defs = load_section_defs(workspace)
    tags = load_tags(workspace, memo_id)
    evidence = load_evidence(workspace, memo_id)
    page_quality = load_page_quality(workspace, memo_id)
    warnings = load_extraction_warnings(workspace, memo_id)

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
        findings.append(f"{len(unreviewed_warnings)} OCR warning(s) still need review.")

    gaps = required_section_gaps(sections, section_defs, memo.get("memo_type", ""), memo.get("facility_type", ""))
    if gaps:
        findings.append("Missing required sections: " + ", ".join(gap.display_name for gap in gaps))

    unconfirmed = [section for section in sections if not section.get("reviewer_confirmed")]
    if unconfirmed:
        findings.append(f"{len(unconfirmed)} section(s) still need confirmation.")

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
    }
    return findings, metrics


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
        approved = st.form_submit_button("Approve for Training Dataset", type="primary")
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
        if st.button("Prepare Review Workbook", type="primary"):
            prepared["review_workbook"] = str(export_excel(workspace, include_only_approved=True))
        review_path = Path(prepared["review_workbook"]) if prepared.get("review_workbook") else None
        if review_path and review_path.exists():
            st.download_button("Download Review Workbook", data=review_path.read_bytes(), file_name=review_path.name)
    with col2:
        st.markdown('<div class="soft-panel"><b>Training File</b><br><span class="small-muted">Structured file for the model tuning pipeline.</span></div>', unsafe_allow_html=True)
        if st.button("Prepare Training File", type="primary"):
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
        if st.button("Prepare Audit Package"):
            prepared["audit_package"] = str(export_memo_bundle(workspace, memo_id))
        audit_path = Path(prepared["audit_package"]) if prepared.get("audit_package") else None
        if audit_path and audit_path.exists():
            st.download_button("Download Audit Package", data=audit_path.read_bytes(), file_name=audit_path.name)


def schema_page(workspace: Path) -> None:
    st.subheader("Tag Setup")
    st.caption("Admin tool for standard sections and tag fields.")

    section_defs = load_section_defs(workspace)
    tag_defs = load_tag_defs(workspace)

    tab_sections, tab_tags = st.tabs(["Standard Memo Sections", "Credit Tags"])
    with tab_sections:
        rows = [
            {
                "section_id": definition.section_id,
                "display_name": definition.display_name,
                "description": definition.description,
                "required": definition.required,
                "aliases": "; ".join(definition.aliases),
                "expected_tag_ids": "; ".join(definition.expected_tag_ids),
                "display_order": definition.display_order,
            }
            for definition in section_defs
        ]
        edited = st.data_editor(pd.DataFrame(rows), num_rows="dynamic", width="stretch", key="section_schema_editor")
        if st.button("Save Standard Sections", type="primary"):
            new_sections = []
            for row in edited.fillna("").to_dict("records"):
                if not row.get("section_id"):
                    continue
                new_sections.append(
                    SectionDefinition(
                        section_id=slugify(str(row["section_id"])),
                        display_name=str(row.get("display_name") or row["section_id"]),
                        description=str(row.get("description") or ""),
                        required=bool(row.get("required")),
                        aliases=[item.strip() for item in str(row.get("aliases", "")).split(";") if item.strip()],
                        expected_tag_ids=[slugify(item.strip()) for item in str(row.get("expected_tag_ids", "")).split(";") if item.strip()],
                        display_order=int(row.get("display_order") or 100),
                    )
                )
            save_section_defs(workspace, new_sections)
            st.success("Standard sections saved.")

    with tab_tags:
        rows = [
            {
                "tag_id": definition.tag_id,
                "label": definition.label,
                "category": definition.category,
                "data_type": definition.data_type,
                "allowed_values": "; ".join(definition.allowed_values),
                "required": definition.required,
                "evidence_required": definition.evidence_required,
                "export_use": definition.export_use,
                "help_text": definition.help_text,
            }
            for definition in tag_defs
        ]
        edited = st.data_editor(pd.DataFrame(rows), num_rows="dynamic", width="stretch", key="tag_schema_editor")
        if st.button("Save Credit Tags", type="primary"):
            new_tags = []
            for row in edited.fillna("").to_dict("records"):
                if not row.get("tag_id"):
                    continue
                data_type = str(row.get("data_type") or "text")
                if data_type not in {"text", "long_text", "enum", "multi_select", "number", "boolean"}:
                    data_type = "text"
                export_use = str(row.get("export_use") or "both")
                if export_use not in {"section", "memo", "both", "none"}:
                    export_use = "both"
                new_tags.append(
                    TagDefinition(
                        tag_id=slugify(str(row["tag_id"])),
                        label=str(row.get("label") or row["tag_id"]),
                        category=str(row.get("category") or "General"),
                        data_type=data_type,  # type: ignore[arg-type]
                        allowed_values=[item.strip() for item in str(row.get("allowed_values", "")).split(";") if item.strip()],
                        required=bool(row.get("required")),
                        evidence_required=bool(row.get("evidence_required")),
                        export_use=export_use,  # type: ignore[arg-type]
                        help_text=str(row.get("help_text") or ""),
                    )
                )
            save_tag_defs(workspace, new_tags)
            st.success("Credit tags saved.")


def diagnostics_page(workspace: Path) -> None:
    st.subheader("Technical Diagnostics")
    st.write(
        {
            "storage": storage_status(workspace),
            "workspace": str(workspace.resolve()),
            "schema_version": SCHEMA_VERSION,
            "tesseract_available": tesseract_available(),
            "document_intelligence_dependencies": dependency_status(),
            "memo_count": len(list_memo_ids(workspace)),
            "section_schema": str(config_path(workspace, "section_schema.json")),
            "tag_schema": str(config_path(workspace, "tag_schema.json")),
        }
    )


def advanced_export_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Advanced Export")
    include_only_approved = st.checkbox("Only export approved records", value=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Create Review Workbook"):
            path = export_excel(workspace, include_only_approved=include_only_approved)
            st.download_button("Download Review Workbook", data=path.read_bytes(), file_name=path.name)
    with col2:
        if st.button("Create Training Files"):
            paths = export_jsonl(workspace, include_only_approved=include_only_approved)
            for label, path in paths.items():
                st.download_button(f"Download {label}", data=path.read_bytes(), file_name=path.name)
    with col3:
        if memo_id and st.button("Create Active Memo Audit Package"):
            path = export_memo_bundle(workspace, memo_id)
            st.download_button("Download Audit Package", data=path.read_bytes(), file_name=path.name)


def admin_tools_page(workspace: Path, memo_id: str | None) -> None:
    tool = st.sidebar.selectbox("Admin Tool", ["Tag Setup", "Technical Diagnostics", "Advanced Export"])
    if tool == "Tag Setup":
        schema_page(workspace)
    elif tool == "Technical Diagnostics":
        diagnostics_page(workspace)
    else:
        advanced_export_page(workspace, memo_id)


def main() -> None:
    show_header()
    workspace = get_workspace()
    active_memo_id = choose_memo(workspace)
    statuses = step_summary(workspace, active_memo_id)

    default_step = st.session_state.get("selected_step", "Add Memo")
    if default_step not in WIZARD_STEPS:
        default_step = "Add Memo"

    admin_mode = st.sidebar.checkbox("Admin Tools", value=False)
    if admin_mode:
        admin_tools_page(workspace, active_memo_id)
        return

    selected_step = st.sidebar.radio("Review Steps", WIZARD_STEPS, index=WIZARD_STEPS.index(default_step))
    st.session_state["selected_step"] = selected_step
    show_progress(selected_step, statuses)

    if selected_step == "Add Memo":
        add_memo_page(workspace)
    elif selected_step == "Review Text Quality":
        review_text_quality_page(workspace, active_memo_id)
    elif selected_step == "Confirm Sections":
        confirm_sections_page(workspace, active_memo_id)
    elif selected_step == "Tag Credit Review":
        tag_credit_review_page(workspace, active_memo_id)
    elif selected_step == "Quality Check":
        quality_check_page(workspace, active_memo_id)
    elif selected_step == "Download Results":
        download_results_page(workspace, active_memo_id)


if __name__ == "__main__":
    main()
