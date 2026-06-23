from __future__ import annotations

import tomllib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from swell.shared.app_metadata import detect_app_version, format_window_title


def test_detect_app_version_reads_project_version() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert detect_app_version() == str(pyproject["project"]["version"])


def test_format_window_title_appends_version() -> None:
    assert format_window_title("Swell Event Marker", "9.8.7") == "Swell Event Marker v9.8.7"
