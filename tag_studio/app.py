from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from tag_studio.defaults import DEFAULT_FACILITY_TYPES, DEFAULT_MEMO_TYPES, SCHEMA_VERSION
from tag_studio.exporters import export_excel, export_jsonl, export_memo_bundle
from tag_studio.extraction import extract_pdf, tesseract_available
from tag_studio.models import EvidenceRecord, SectionDefinition, TagDefinition, TagRecord, utc_now
from tag_studio.sectioning import propose_sections, required_section_gaps
from tag_studio.storage import (
    DEFAULT_WORKSPACE,
    append_audit,
    config_path,
    create_memo_workspace,
    ensure_workspace,
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
    write_json,
)


st.set_page_config(page_title="Tag Studio", page_icon="TS", layout="wide")


CSS = """
<style>
body { background: #f6f8fb; }
.block-container { padding-top: 1.4rem; }
[data-testid="stSidebar"] { background: #102033; }
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {
  color: #edf4ff !important;
}
.tag-title {
  padding: 1.1rem 1.3rem;
  border: 1px solid #dde5ef;
  border-radius: 10px;
  background: linear-gradient(135deg, #12324c, #255d76);
  color: white;
  margin-bottom: 1rem;
}
.tag-title h1 { margin: 0; font-size: 2rem; letter-spacing: 0; }
.tag-title p { margin: .35rem 0 0 0; color: #dcebf5; }
.metric-card {
  border: 1px solid #d8e1ea;
  border-radius: 8px;
  background: white;
  padding: .9rem;
  min-height: 92px;
}
.metric-card .label { color: #5b6b7f; font-size: .78rem; text-transform: uppercase; }
.metric-card .value { color: #172333; font-size: 1.2rem; font-weight: 700; margin-top: .35rem; }
.section-box {
  border: 1px solid #dbe4ed;
  border-radius: 8px;
  background: #ffffff;
  padding: 1rem;
}
.muted { color: #637083; }
.status-pill {
  display: inline-block;
  padding: .2rem .55rem;
  border-radius: 999px;
  background: #e8f1f8;
  color: #17324d;
  font-size: .82rem;
  font-weight: 650;
}
</style>
"""


def show_header() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="tag-title">
          <h1>Tag Studio</h1>
          <p>Local-first golden-copy tagging for credit memo PDFs.</p>
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
    workspace_text = st.sidebar.text_input("Workspace folder", value=str(DEFAULT_WORKSPACE))
    workspace = Path(workspace_text)
    ensure_workspace(workspace)
    st.sidebar.caption(f"Schema: {SCHEMA_VERSION}")
    return workspace


def choose_memo(workspace: Path) -> str | None:
    memo_ids = list_memo_ids(workspace)
    if not memo_ids:
        st.sidebar.info("No memos have been uploaded yet.")
        return None
    return st.sidebar.selectbox("Active memo", memo_ids)


def dashboard(workspace: Path, active_memo_id: str | None) -> None:
    memo_ids = list_memo_ids(workspace)
    approved = sum(1 for memo_id in memo_ids if load_review(workspace, memo_id).get("status") == "Approved Gold")
    tags = sum(len(load_tags(workspace, memo_id)) for memo_id in memo_ids)
    evidence = sum(len(load_evidence(workspace, memo_id)) for memo_id in memo_ids)
    cols = st.columns(4)
    cards = [
        ("Memos", len(memo_ids)),
        ("Approved Gold", approved),
        ("Tag Records", tags),
        ("Evidence Records", evidence),
    ]
    for col, (label, value) in zip(cols, cards):
        col.markdown(f'<div class="metric-card"><div class="label">{label}</div><div class="value">{value}</div></div>', unsafe_allow_html=True)

    if active_memo_id:
        memo = load_memo_record(workspace, active_memo_id)
        review = load_review(workspace, active_memo_id)
        st.markdown("#### Active Memo")
        st.write(
            {
                "memo_id": active_memo_id,
                "source_file": memo.get("source_file_name"),
                "memo_type": memo.get("memo_type"),
                "facility_type": memo.get("facility_type"),
                "review_status": review.get("status"),
                "extraction_method": memo.get("extraction_method"),
            }
        )
    else:
        st.info("Upload a memo to begin.")


def upload_extract_page(workspace: Path) -> None:
    st.subheader("Upload and Extract")
    st.caption("Local extraction is the default. Tesseract is only needed when the PDF has no embedded text.")

    with st.form("upload_form"):
        uploaded = st.file_uploader("Credit memo PDF", type=["pdf"])
        col1, col2, col3 = st.columns(3)
        with col1:
            memo_type = st.selectbox("Memo type", DEFAULT_MEMO_TYPES, index=1)
        with col2:
            facility_type = st.selectbox("Facility type", DEFAULT_FACILITY_TYPES, index=7)
        with col3:
            reviewer = st.text_input("Tagger / reviewer", value="")
        borrower = st.text_input("Borrower name or internal hash", value="")
        force_ocr = st.checkbox("Force local OCR", value=False)
        submitted = st.form_submit_button("Create memo workspace and extract")

    if not submitted:
        st.info("Upload a PDF to create a local memo workspace.")
        return
    if uploaded is None:
        st.error("Choose a PDF before extracting.")
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

    base = memo_dir(workspace, memo_id)
    with st.spinner("Rendering pages and extracting text locally..."):
        page_text, rendered_paths, method, warning = extract_pdf(base / "source" / "source.pdf", base / "pages", force_ocr=force_ocr)
        write_json(base / "extraction" / "page_text.json", [page.model_dump() for page in page_text])
        write_json(
            base / "extraction" / "extraction_summary.json",
            {
                "method": method,
                "warning": warning,
                "page_count": len(page_text),
                "rendered_pages": [str(path) for path in rendered_paths],
                "tesseract_available": tesseract_available(),
            },
        )
        memo_record = record.model_dump()
        memo_record["extraction_method"] = method
        save_memo_record(workspace, memo_id, memo_record)

        section_defs = load_section_defs(workspace)
        proposed = propose_sections(
            memo_id=memo_id,
            pages=[page.model_dump() for page in page_text],
            definitions=section_defs,
            extraction_method=method,
        )
        save_sections(workspace, memo_id, [section.model_dump() for section in proposed])

    if warning:
        st.warning(warning)
    st.success(f"Created {memo_id}. Go to Section Review to confirm mappings.")


def schema_page(workspace: Path) -> None:
    st.subheader("Configurable Sections and Tags")
    st.caption("Canonical sections make inconsistent memo headings train to the same normalized section IDs.")

    section_defs = load_section_defs(workspace)
    tag_defs = load_tag_defs(workspace)

    tab_sections, tab_tags = st.tabs(["Canonical Sections", "Tags"])
    with tab_sections:
        st.markdown("##### Edit Section Taxonomy")
        rows = []
        for definition in section_defs:
            rows.append(
                {
                    "section_id": definition.section_id,
                    "display_name": definition.display_name,
                    "description": definition.description,
                    "required": definition.required,
                    "aliases": "; ".join(definition.aliases),
                    "expected_tag_ids": "; ".join(definition.expected_tag_ids),
                    "display_order": definition.display_order,
                }
            )
        edited = st.data_editor(
            pd.DataFrame(rows),
            num_rows="dynamic",
            use_container_width=True,
            key="section_schema_editor",
        )
        if st.button("Save section schema", type="primary"):
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
            st.success("Section schema saved.")

    with tab_tags:
        st.markdown("##### Edit Tag Schema")
        rows = []
        for definition in tag_defs:
            rows.append(
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
            )
        edited = st.data_editor(
            pd.DataFrame(rows),
            num_rows="dynamic",
            use_container_width=True,
            key="tag_schema_editor",
        )
        if st.button("Save tag schema", type="primary"):
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
            st.success("Tag schema saved.")


def section_review_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Section Review")
    if not memo_id:
        st.info("Upload or select a memo first.")
        return

    memo = load_memo_record(workspace, memo_id)
    section_defs = load_section_defs(workspace)
    sections = load_sections(workspace, memo_id)
    section_names = {section.section_id: section.display_name for section in section_defs}

    gaps = required_section_gaps(sections, section_defs, memo.get("memo_type", ""), memo.get("facility_type", ""))
    if gaps:
        st.warning("Missing required canonical sections: " + ", ".join(gap.display_name for gap in gaps))
    else:
        st.success("All required canonical sections are represented.")

    rows = []
    for section in sections:
        rows.append(
            {
                "section_id": section.get("section_id"),
                "original_header": section.get("original_header"),
                "canonical_section_id": section.get("canonical_section_id"),
                "page_start": section.get("page_start"),
                "page_end": section.get("page_end"),
                "reviewer_confirmed": section.get("reviewer_confirmed", False),
                "text": section.get("text", ""),
            }
        )

    edited = st.data_editor(
        pd.DataFrame(rows),
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "canonical_section_id": st.column_config.SelectboxColumn(
                "canonical_section_id",
                options=list(section_names.keys()),
                required=True,
            ),
            "text": st.column_config.TextColumn("text", width="large"),
        },
        key=f"section_review_{memo_id}",
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("Save section mapping", type="primary"):
            saved = []
            for idx, row in enumerate(edited.fillna("").to_dict("records"), start=1):
                canonical_id = str(row.get("canonical_section_id") or "")
                saved.append(
                    {
                        "section_id": str(row.get("section_id") or f"section_{idx:03}"),
                        "memo_id": memo_id,
                        "canonical_section_id": canonical_id,
                        "canonical_section_name": section_names.get(canonical_id, canonical_id),
                        "original_header": str(row.get("original_header") or ""),
                        "page_start": int(row.get("page_start") or 1),
                        "page_end": int(row.get("page_end") or row.get("page_start") or 1),
                        "text": str(row.get("text") or ""),
                        "extraction_method": memo.get("extraction_method", "manual_correction"),
                        "reviewer_confirmed": bool(row.get("reviewer_confirmed")),
                        "missing_required": False,
                    }
                )
            save_sections(workspace, memo_id, saved)
            st.success("Section mapping saved.")
    with col2:
        st.caption("Tip: map nonstandard memo headers to the canonical section ID. The original header is preserved for lineage.")


def _render_tag_input(definition: TagDefinition, key: str):
    if definition.data_type == "enum":
        options = [""] + definition.allowed_values
        return st.selectbox(definition.label, options, key=key, help=definition.help_text)
    if definition.data_type == "multi_select":
        return st.multiselect(definition.label, definition.allowed_values, key=key, help=definition.help_text)
    if definition.data_type == "number":
        return st.number_input(definition.label, min_value=0.0, max_value=100.0, step=1.0, key=key, help=definition.help_text)
    if definition.data_type == "boolean":
        return st.checkbox(definition.label, key=key, help=definition.help_text)
    if definition.data_type == "long_text":
        return st.text_area(definition.label, key=key, help=definition.help_text, height=100)
    return st.text_input(definition.label, key=key, help=definition.help_text)


def tagging_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Tagging Workspace")
    if not memo_id:
        st.info("Upload or select a memo first.")
        return

    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    if not sections:
        st.info("No sections exist yet. Run extraction and section review first.")
        return

    tag_defs = load_tag_defs(workspace)
    tags = load_tags(workspace, memo_id)
    evidence = load_evidence(workspace, memo_id)

    section_labels = {
        section["section_id"]: f"{section.get('canonical_section_name')} | {section.get('original_header')} | p.{section.get('page_start')}-{section.get('page_end')}"
        for section in sections
    }
    section_id = st.selectbox("Section to tag", list(section_labels.keys()), format_func=lambda value: section_labels[value])
    section = next(item for item in sections if item["section_id"] == section_id)

    expected_ids = set()
    section_defs = load_section_defs(workspace)
    for definition in section_defs:
        if definition.section_id == section.get("canonical_section_id"):
            expected_ids.update(definition.expected_tag_ids)
    relevant_tags = [tag for tag in tag_defs if tag.tag_id in expected_ids] or tag_defs

    left, center, right = st.columns([1.1, 1.35, 1])
    with left:
        st.markdown("##### PDF Page")
        page_path = memo_dir(workspace, memo_id) / "pages" / f"page_{int(section.get('page_start', 1)):03}.png"
        if page_path.exists():
            st.image(str(page_path), use_container_width=True)
        else:
            st.info("Page image is not available.")
        st.caption(f"Source hash: {memo.get('source_hash', '')[:16]}...")

    with center:
        st.markdown("##### Extracted Section Text")
        st.text_area(
            "Select/copy evidence from this text, then paste it into the evidence box.",
            section.get("text", ""),
            height=520,
            key=f"section_text_{memo_id}_{section_id}",
        )

    with right:
        st.markdown("##### Evidence")
        raw_lines = [line.strip() for line in str(section.get("text", "")).splitlines() if line.strip()]
        selected_line_indices = st.multiselect(
            "Select evidence lines",
            list(range(len(raw_lines))),
            format_func=lambda idx: f"L{idx + 1}: {raw_lines[idx][:110]}",
            key=f"evidence_lines_{memo_id}_{section_id}",
        )
        selected_line_text = "\n".join(raw_lines[idx] for idx in selected_line_indices)
        if selected_line_text:
            st.text_area("Selected evidence preview", selected_line_text, height=90, disabled=True)
        manual_evidence_text = st.text_area(
            "Manual evidence correction",
            height=90,
            key=f"evidence_text_{memo_id}_{section_id}",
            help="Optional. Use this if OCR needs correction or the evidence is not captured cleanly by line selection.",
        )
        evidence_role = st.selectbox(
            "Evidence role",
            ["supporting_fact", "missing_marker", "contradiction", "score_support", "policy_exception", "outcome_support"],
            key=f"evidence_role_{memo_id}_{section_id}",
        )
        citation_confidence = st.selectbox("Citation confidence", ["High", "Medium", "Low"], index=1, key=f"citation_confidence_{memo_id}_{section_id}")
        if st.button("Add evidence", key=f"add_evidence_{memo_id}_{section_id}"):
            evidence_text = manual_evidence_text.strip() or selected_line_text.strip()
            if not evidence_text:
                st.error("Evidence text is required.")
            else:
                record = EvidenceRecord(
                    evidence_id=f"ev_{uuid4().hex[:10]}",
                    memo_id=memo_id,
                    section_id=section_id,
                    page_number=int(section.get("page_start", 1)),
                    selected_text=evidence_text.strip(),
                    source_location=f"p.{section.get('page_start')} / {section.get('original_header')}",
                    evidence_role=evidence_role,
                    citation_confidence=citation_confidence,  # type: ignore[arg-type]
                    source_document_hash=memo.get("source_hash", ""),
                )
                evidence.append(record.model_dump())
                save_evidence(workspace, memo_id, evidence)
                st.success("Evidence added.")

        section_evidence = [item for item in evidence if item.get("section_id") == section_id]
        evidence_options = {item["evidence_id"]: f"{item['evidence_id']} | {item.get('selected_text', '')[:70]}" for item in section_evidence}
        selected_evidence = st.multiselect("Attach evidence to new tags", list(evidence_options.keys()), format_func=lambda value: evidence_options[value])

    st.markdown("##### Tags")
    with st.form(f"tag_form_{memo_id}_{section_id}"):
        cols = st.columns(2)
        values = {}
        for idx, definition in enumerate(relevant_tags):
            with cols[idx % 2]:
                values[definition.tag_id] = _render_tag_input(definition, key=f"input_{memo_id}_{section_id}_{definition.tag_id}")
        confidence = st.selectbox("Tagger confidence for this batch", ["High", "Medium", "Low"], index=1)
        tagger = st.text_input("Tagger", value=memo.get("reviewer", ""))
        save_batch = st.form_submit_button("Save tag batch", type="primary")

    if save_batch:
        existing = [tag for tag in tags if not (tag.get("section_id") == section_id and tag.get("tag_id") in values)]
        new_records = []
        for definition in relevant_tags:
            value = values.get(definition.tag_id)
            empty = value in (None, "", []) or (definition.data_type == "number" and value == 0.0 and not definition.required)
            if empty:
                continue
            if definition.evidence_required and not selected_evidence:
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
        st.success(f"Saved {len(new_records)} tag records.")

    existing_section_tags = [tag for tag in load_tags(workspace, memo_id) if tag.get("section_id") == section_id]
    if existing_section_tags:
        st.markdown("##### Existing Tags for Section")
        st.dataframe(pd.DataFrame(existing_section_tags), use_container_width=True)


def validate_ready(workspace: Path, memo_id: str) -> list[str]:
    errors: list[str] = []
    memo = load_memo_record(workspace, memo_id)
    sections = load_sections(workspace, memo_id)
    section_defs = load_section_defs(workspace)
    tags = load_tags(workspace, memo_id)
    evidence = load_evidence(workspace, memo_id)

    gaps = required_section_gaps(sections, section_defs, memo.get("memo_type", ""), memo.get("facility_type", ""))
    if gaps:
        errors.append("Missing required sections: " + ", ".join(gap.display_name for gap in gaps))
    if any(not section.get("reviewer_confirmed") for section in sections):
        errors.append("All sections must be reviewer-confirmed.")
    if not tags:
        errors.append("At least one tag record is required.")
    evidence_ids = {item.get("evidence_id") for item in evidence}
    for tag in tags:
        if tag.get("evidence_ids"):
            missing = [item for item in tag["evidence_ids"] if item not in evidence_ids]
            if missing:
                errors.append(f"Tag {tag.get('tag_id')} references missing evidence: {', '.join(missing)}")
    return errors


def review_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Review and Adjudication")
    if not memo_id:
        st.info("Upload or select a memo first.")
        return

    review = load_review(workspace, memo_id)
    errors = validate_ready(workspace, memo_id)
    if errors:
        st.warning("Validation issues must be resolved before approval.")
        for error in errors:
            st.write(f"- {error}")
    else:
        st.success("Memo passes readiness validation.")

    with st.form(f"review_form_{memo_id}"):
        status_options = ["Draft", "Ready for Review", "Changes Requested", "Approved Gold", "Exported"]
        current = review.get("status", "Draft")
        status = st.selectbox("Review status", status_options, index=status_options.index(current) if current in status_options else 0)
        reviewer = st.text_input("Reviewer", value=review.get("reviewer", ""))
        adjudicator = st.text_input("Adjudicator", value=review.get("adjudicator", ""))
        notes = st.text_area("Adjudication notes", value=review.get("adjudication_notes", ""), height=120)
        submitted = st.form_submit_button("Save review status", type="primary")

    if submitted:
        if status in {"Ready for Review", "Approved Gold"} and errors:
            st.error("Resolve validation issues before setting Ready for Review or Approved Gold.")
            return
        review.update(
            {
                "memo_id": memo_id,
                "status": status,
                "reviewer": reviewer,
                "adjudicator": adjudicator,
                "adjudication_notes": notes,
                "approved_at": utc_now() if status == "Approved Gold" else review.get("approved_at"),
            }
        )
        save_review(workspace, memo_id, review)
        append_audit(workspace, memo_id, "adjudication_saved", review)
        st.success("Review status saved.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### Tags")
        st.dataframe(pd.DataFrame(load_tags(workspace, memo_id)), use_container_width=True)
    with col2:
        st.markdown("##### Evidence")
        st.dataframe(pd.DataFrame(load_evidence(workspace, memo_id)), use_container_width=True)


def export_page(workspace: Path, memo_id: str | None) -> None:
    st.subheader("Export Center")
    include_only_approved = st.checkbox("Only export Approved Gold records", value=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Export Excel", type="primary"):
            path = export_excel(workspace, include_only_approved=include_only_approved)
            st.success(f"Excel export created: {path}")
            st.download_button("Download Excel", data=path.read_bytes(), file_name=path.name)
    with col2:
        if st.button("Export JSONL", type="primary"):
            paths = export_jsonl(workspace, include_only_approved=include_only_approved)
            st.success("JSONL exports created.")
            for label, path in paths.items():
                st.download_button(f"Download {label}", data=path.read_bytes(), file_name=path.name)
    with col3:
        if memo_id and st.button("Export active memo bundle"):
            path = export_memo_bundle(workspace, memo_id)
            st.success(f"Memo bundle created: {path}")
            st.download_button("Download memo bundle", data=path.read_bytes(), file_name=path.name)

    st.markdown("##### Current Exportable Memos")
    rows = []
    for candidate in list_memo_ids(workspace):
        rows.append(
            {
                "memo_id": candidate,
                "status": load_review(workspace, candidate).get("status"),
                "tags": len(load_tags(workspace, candidate)),
                "evidence": len(load_evidence(workspace, candidate)),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


def diagnostics_page(workspace: Path) -> None:
    st.subheader("Diagnostics")
    st.write(
        {
            "workspace": str(workspace.resolve()),
            "tesseract_available": tesseract_available(),
            "memo_count": len(list_memo_ids(workspace)),
            "section_schema": str(config_path(workspace, "section_schema.json")),
            "tag_schema": str(config_path(workspace, "tag_schema.json")),
        }
    )
    st.caption("If scanned PDFs do not extract text, install the Tesseract OCR engine and make sure it is on PATH.")


def main() -> None:
    show_header()
    workspace = get_workspace()
    active_memo_id = choose_memo(workspace)

    page = st.sidebar.radio(
        "Workflow",
        [
            "Dashboard",
            "Upload and Extract",
            "Configure Schema",
            "Section Review",
            "Tagging Workspace",
            "Review and Adjudication",
            "Export Center",
            "Diagnostics",
        ],
    )

    if page == "Dashboard":
        dashboard(workspace, active_memo_id)
    elif page == "Upload and Extract":
        upload_extract_page(workspace)
    elif page == "Configure Schema":
        schema_page(workspace)
    elif page == "Section Review":
        section_review_page(workspace, active_memo_id)
    elif page == "Tagging Workspace":
        tagging_page(workspace, active_memo_id)
    elif page == "Review and Adjudication":
        review_page(workspace, active_memo_id)
    elif page == "Export Center":
        export_page(workspace, active_memo_id)
    elif page == "Diagnostics":
        diagnostics_page(workspace)


if __name__ == "__main__":
    main()
