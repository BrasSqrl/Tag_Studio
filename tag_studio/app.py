from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from tag_studio.app_config import WIZARD_STEPS
from tag_studio.pages.admin import admin_tools_page
from tag_studio.pages.guide import user_guide_page
from tag_studio.pages.reviewer import (
    add_memo_page,
    confirm_sections_page,
    download_results_page,
    quality_check_page,
    review_text_quality_page,
    set_up_facilities_page,
    tag_credit_review_page,
    tag_outcomes_page,
)
from tag_studio.services import MemoReadService, WorkflowService
from tag_studio.storage import (
    DEFAULT_WORKSPACE,
    ensure_workspace,
    hydrate_memo_from_remote,
    list_memo_ids,
    storage_readiness,
)
from tag_studio.ui_components import show_header, show_progress, show_step_navigation

st.set_page_config(page_title="Tag Studio", page_icon="TS", layout="wide")


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


def choose_memo(workspace: Path) -> str | None:
    memo_ids = list_memo_ids(workspace)
    if not memo_ids:
        st.sidebar.info("No memos have been added yet.")
        return None

    read_service = MemoReadService(workspace)
    labels = read_service.display_labels(memo_ids)
    active = st.session_state.get("active_memo_id")
    index = memo_ids.index(active) if active in memo_ids else 0
    selected = st.sidebar.selectbox(
        "Current Memo",
        memo_ids,
        index=index,
        format_func=lambda memo_id: labels.get(memo_id, memo_id),
    )
    st.session_state["active_memo_id"] = selected
    hydrate_memo_from_remote(workspace, selected)
    return selected


def route_reviewer_page(workspace: Path, active_memo_id: str | None, selected_step: str) -> None:
    if selected_step == "Add Memo":
        add_memo_page(workspace)
    elif selected_step == "Review Text Quality":
        review_text_quality_page(workspace, active_memo_id)
    elif selected_step == "Review Memo Sections":
        confirm_sections_page(workspace, active_memo_id)
    elif selected_step == "Set Up Facilities":
        set_up_facilities_page(workspace, active_memo_id)
    elif selected_step == "Tag Credit Review":
        tag_credit_review_page(workspace, active_memo_id)
    elif selected_step == "Tag Outcomes":
        tag_outcomes_page(workspace, active_memo_id)
    elif selected_step == "Quality Check":
        quality_check_page(workspace, active_memo_id)
    elif selected_step == "Download Results":
        download_results_page(workspace, active_memo_id)


def main() -> None:
    show_header()
    workspace = get_workspace()
    active_memo_id = choose_memo(workspace)
    statuses = WorkflowService(workspace).step_summary(active_memo_id)

    pending_step = st.session_state.pop("_pending_review_step", None)
    if pending_step in WIZARD_STEPS:
        st.session_state["selected_step"] = pending_step

    default_step = st.session_state.get("selected_step", "Add Memo")
    if default_step not in WIZARD_STEPS:
        default_step = "Add Memo"
        st.session_state["selected_step"] = default_step

    admin_mode = st.sidebar.checkbox("Admin Tools", value=False)
    guide_mode = st.sidebar.checkbox("User Guide", value=False, help="Open the credit reviewer guide for this app.")
    if guide_mode:
        user_guide_page()
        return

    if admin_mode:
        admin_tools_page(workspace, active_memo_id)
        return

    selected_step = st.sidebar.radio(
        "Review Steps",
        WIZARD_STEPS,
        index=WIZARD_STEPS.index(default_step),
        key=f"review_step_radio_{WIZARD_STEPS.index(default_step)}",
    )
    st.session_state["selected_step"] = selected_step
    show_progress(selected_step, statuses)
    show_step_navigation(selected_step)
    route_reviewer_page(workspace, active_memo_id, selected_step)


def _running_this_file_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:  # pragma: no cover - Streamlit import guard.
        return False
    return get_script_run_ctx() is not None and Path(sys.argv[0]).resolve() == Path(__file__).resolve()


if __name__ == "__main__" or _running_this_file_under_streamlit():
    main()
