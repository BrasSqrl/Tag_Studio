from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_launchers_use_root_streamlit_entrypoint() -> None:
    launcher = ROOT / "tag_studio_launcher.py"
    start_bat = (ROOT / "Start Tag Studio.bat").read_text(encoding="utf-8")
    shakudo_run = (ROOT / "shakudo" / "run.sh").read_text(encoding="utf-8")

    assert launcher.exists()
    assert "streamlit run tag_studio_launcher.py" in start_bat
    assert "streamlit run tag_studio_launcher.py" in shakudo_run
    assert "streamlit run tag_studio\\app.py" not in start_bat
    assert "streamlit run tag_studio/app.py" not in shakudo_run
    assert "--server.headless true" in start_bat
