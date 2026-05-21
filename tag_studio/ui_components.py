from __future__ import annotations

import streamlit as st

from .app_config import WIZARD_STEPS

CSS = """
<style>
body { background: #f6f8fb; }
.block-container { padding-top: 1.4rem; max-width: 1380px; }
[data-testid="stSidebar"] { background: #102033; }
[data-testid="stSidebarNav"] { display: none !important; }
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
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
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


def show_step_navigation(current_step: str) -> None:
    current_index = WIZARD_STEPS.index(current_step)
    prev_step = WIZARD_STEPS[current_index - 1] if current_index > 0 else None
    next_step = WIZARD_STEPS[current_index + 1] if current_index < len(WIZARD_STEPS) - 1 else None
    spacer, back_col, next_col = st.columns([6, 1, 1])
    with spacer:
        st.empty()
    with back_col:
        if prev_step and st.button("Back", key=f"wizard_back_{current_step}", use_container_width=True):
            go_to_step(prev_step)
        elif not prev_step:
            st.button("Back", key=f"wizard_back_disabled_{current_step}", disabled=True, use_container_width=True)
    with next_col:
        if next_step and st.button("Next", key=f"wizard_next_{current_step}", type="primary", use_container_width=True):
            go_to_step(next_step)
        elif not next_step:
            st.button("Next", key=f"wizard_next_disabled_{current_step}", disabled=True, use_container_width=True)


def go_to_step(step: str) -> None:
    st.session_state["_pending_review_step"] = step
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
        st.warning("Could not read scanned text. Add local scanned-PDF reading support or correct the text manually.")
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
