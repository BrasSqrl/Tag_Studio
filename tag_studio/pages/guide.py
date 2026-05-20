from __future__ import annotations

import base64
import re

import streamlit as st

from tag_studio.app_config import USER_GUIDE_PATH


def _inline_user_guide_assets(html: str) -> str:
    assets_dir = USER_GUIDE_PATH.parent

    def replace_src(match: re.Match[str]) -> str:
        quote = match.group(1)
        src = match.group(2)
        asset_path = (assets_dir / src).resolve()
        try:
            asset_path.relative_to(assets_dir.resolve())
        except ValueError:
            return match.group(0)
        if not asset_path.exists():
            return match.group(0)
        mime = "image/png" if asset_path.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
        return f'src={quote}data:{mime};base64,{encoded}{quote}'

    return re.sub(r'src=(["\'])(assets/[^"\']+)\1', replace_src, html)


def user_guide_page() -> None:
    st.subheader("User Guide")
    st.caption("Step-by-step guidance for credit reviewers using Tag Studio.")
    if not USER_GUIDE_PATH.exists():
        st.warning("The user guide has not been created yet.")
        return
    html = USER_GUIDE_PATH.read_text(encoding="utf-8")
    download_html = _inline_user_guide_assets(html)
    st.download_button(
        "Download User Guide",
        data=download_html.encode("utf-8"),
        file_name=USER_GUIDE_PATH.name,
        mime="text/html",
        help="Download the standalone guide so it can be opened outside Tag Studio.",
    )
    st.iframe(USER_GUIDE_PATH, height=920)
