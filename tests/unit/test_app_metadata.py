from __future__ import annotations

from sdapp.shared.app_metadata import detect_app_version, format_window_title


def test_detect_app_version_reads_project_version() -> None:
    assert detect_app_version() == "0.1.3"


def test_format_window_title_appends_version() -> None:
    assert format_window_title("IOS SD Event Marker", "9.8.7") == "IOS SD Event Marker v9.8.7"
