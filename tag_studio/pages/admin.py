from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from tag_studio.defaults import SCHEMA_VERSION
from tag_studio.document_intelligence import dependency_status
from tag_studio.exporters import export_excel, export_jsonl, export_memo_bundle
from tag_studio.extraction import tesseract_available
from tag_studio.models import SectionDefinition, TagDefinition
from tag_studio.schema_workbook import create_tag_setup_workbook, import_tag_setup_workbook
from tag_studio.services import (
    load_outcome_taxonomy,
    load_scoring_rubric,
    load_section_defs,
    load_tag_defs,
    save_outcome_taxonomy,
    save_scoring_rubric_defs,
    save_section_defs,
    save_tag_defs,
    schema_usage_warnings,
)
from tag_studio.storage import config_path, list_memo_ids, slugify, storage_status


def schema_page(workspace: Path) -> None:
    st.subheader("Tag Setup")
    st.caption("Admin tool for standard sections and tag fields.")

    section_defs = load_section_defs(workspace)
    tag_defs = load_tag_defs(workspace)
    outcome_taxonomy = load_outcome_taxonomy(workspace)
    scoring_rubric = load_scoring_rubric(workspace)
    import_message = st.session_state.pop("tag_setup_import_message", "")
    import_warning_messages = st.session_state.pop("tag_setup_import_warnings", [])
    if import_message:
        st.success(import_message)
    for warning in import_warning_messages:
        st.warning(warning)

    st.markdown("##### Excel Template Update")
    st.caption("Download the current setup, edit it in Excel, then upload it back to update sections, tags, outcome event types, and scoring rules in bulk.")
    template_state_key = "tag_setup_template_bytes"
    if st.button(
        "Prepare Tag Setup Template",
        help="Create the editable workbook from the current standard memo sections and credit tags.",
    ):
        st.session_state[template_state_key] = create_tag_setup_workbook(section_defs, tag_defs, outcome_taxonomy, scoring_rubric)
    if template_state_key in st.session_state:
        st.download_button(
            "Download Tag Setup Template",
            data=st.session_state[template_state_key],
            file_name="tag_studio_tag_setup_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Download the current standard memo sections and credit tags as an editable Excel workbook.",
        )
    uploaded_setup = st.file_uploader(
        "Upload edited tag setup workbook",
        type=["xlsx"],
        key="tag_setup_workbook_upload",
        help="Upload the edited template. Keep the sheet names and header rows unchanged.",
    )
    update_col1, update_col2, update_col3, update_col4, update_col5 = st.columns([1, 1, 1, 1, 1.2])
    with update_col1:
        update_sections = st.checkbox("Update Standard Memo Sections", value=True)
    with update_col2:
        update_tags = st.checkbox("Update Credit Tags", value=True)
    with update_col3:
        update_outcomes = st.checkbox("Update Outcome Event Types", value=True)
    with update_col4:
        update_scoring = st.checkbox("Update Scoring Rules", value=True)
    with update_col5:
        apply_setup = st.button(
            "Apply Uploaded Tag Setup",
            type="primary",
            disabled=uploaded_setup is None,
            help="Replace the selected setup areas with values from the uploaded workbook.",
        )

    if apply_setup:
        if not update_sections and not update_tags and not update_outcomes and not update_scoring:
            st.error("Choose at least one setup area to update.")
        elif uploaded_setup is None:
            st.error("Upload an edited tag setup workbook first.")
        else:
            try:
                imported = import_tag_setup_workbook(
                    uploaded_setup.getvalue(),
                    section_defs,
                    tag_defs,
                    update_sections=update_sections,
                    update_tags=update_tags,
                    update_outcomes=update_outcomes,
                    update_scoring=update_scoring,
                )
                import_warnings = schema_usage_warnings(workspace, section_defs, tag_defs, imported.sections, imported.tags)
                if imported.sections is not None:
                    save_section_defs(workspace, imported.sections)
                    section_defs = imported.sections
                if imported.tags is not None:
                    save_tag_defs(workspace, imported.tags)
                    tag_defs = imported.tags
                if imported.outcomes is not None:
                    save_outcome_taxonomy(workspace, imported.outcomes)
                    outcome_taxonomy = imported.outcomes
                if imported.scoring is not None:
                    save_scoring_rubric_defs(workspace, imported.scoring)
                    scoring_rubric = imported.scoring
                st.session_state.pop(template_state_key, None)
                st.session_state["tag_setup_import_message"] = (
                    f"Tag setup updated. Sections: {len(section_defs)}. Credit tags: {len(tag_defs)}. "
                    f"Outcome event types: {len(outcome_taxonomy)}. Scoring rules: {len(scoring_rubric)}."
                )
                st.session_state["tag_setup_import_warnings"] = [*imported.warnings, *import_warnings]
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - convert workbook errors to admin-facing guidance.
                st.error(f"Tag setup workbook could not be applied: {exc}")

    tab_sections, tab_tags, tab_outcomes, tab_scoring = st.tabs(
        ["Standard Memo Sections", "Credit Tags", "Outcome Event Types", "Scoring Rules"]
    )
    with tab_sections:
        rows = [
            {
                "section_id": definition.section_id,
                "display_name": definition.display_name,
                "description": definition.description,
                "required": definition.required,
                "memo_types": "; ".join(definition.memo_types),
                "facility_types": "; ".join(definition.facility_types),
                "aliases": "; ".join(definition.aliases),
                "expected_tag_ids": "; ".join(definition.expected_tag_ids),
                "evidence_required": definition.evidence_required,
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
                        memo_types=[item.strip() for item in str(row.get("memo_types", "")).split(";") if item.strip()],
                        facility_types=[item.strip() for item in str(row.get("facility_types", "")).split(";") if item.strip()],
                        aliases=[item.strip() for item in str(row.get("aliases", "")).split(";") if item.strip()],
                        expected_tag_ids=[slugify(item.strip()) for item in str(row.get("expected_tag_ids", "")).split(";") if item.strip()],
                        evidence_required=bool(row.get("evidence_required")),
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
                "scoring_use": definition.scoring_use,
                "export_use": definition.export_use,
                "help_text": definition.help_text,
                "material": definition.material,
                "allowed_scopes": "; ".join(definition.allowed_scopes),
                "default_scope": definition.default_scope,
                "facility_required": definition.facility_required,
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
                        material=bool(row.get("material")),
                        allowed_scopes=[item.strip() for item in str(row.get("allowed_scopes", "section")).split(";") if item.strip()] or ["section"],  # type: ignore[arg-type]
                        default_scope=str(row.get("default_scope") or "section"),  # type: ignore[arg-type]
                        facility_required=bool(row.get("facility_required")),
                        scoring_use=str(row.get("scoring_use") or ""),
                        export_use=export_use,  # type: ignore[arg-type]
                        help_text=str(row.get("help_text") or ""),
                    )
                )
            save_tag_defs(workspace, new_tags)
            st.success("Credit tags saved.")

    with tab_outcomes:
        edited = st.data_editor(pd.DataFrame(outcome_taxonomy), num_rows="dynamic", width="stretch", key="outcome_taxonomy_editor")
        if st.button("Save Outcome Event Types", type="primary"):
            records = []
            for row in edited.fillna("").to_dict("records"):
                event_type = str(row.get("event_type") or row.get("label") or "").strip()
                if not event_type:
                    continue
                records.append({"event_type": event_type, "severity_rank": int(row.get("severity_rank") or 0)})
            save_outcome_taxonomy(workspace, records)
            st.success("Outcome event types saved.")

    with tab_scoring:
        edited = st.data_editor(pd.DataFrame(scoring_rubric), num_rows="dynamic", width="stretch", key="scoring_rubric_editor")
        if st.button("Save Scoring Rules", type="primary"):
            records = []
            for row in edited.fillna("").to_dict("records"):
                if not row.get("score_name") or not row.get("component_tag_id"):
                    continue
                records.append(
                    {
                        "score_name": str(row.get("score_name")),
                        "component_tag_id": str(row.get("component_tag_id")),
                        "weight": float(row.get("weight") or 0),
                        "directionality": str(row.get("directionality") or "higher_is_better"),
                        "min_value": float(row.get("min_value") or 0),
                        "max_value": float(row.get("max_value") or 100),
                        "required_evidence": bool(row.get("required_evidence")),
                        "memo_types": [item.strip() for item in str(row.get("memo_types", "")).split(";") if item.strip()],
                        "facility_types": [item.strip() for item in str(row.get("facility_types", "")).split(";") if item.strip()],
                        "active": bool(row.get("active", True)),
                        "version": str(row.get("version") or SCHEMA_VERSION),
                    }
                )
            save_scoring_rubric_defs(workspace, records)
            st.success("Scoring rules saved.")


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
