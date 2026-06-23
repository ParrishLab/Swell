from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from swell.analysis.core import project_workflow


def _capture_save_as_kwargs(app) -> dict:
    captured: dict[str, object] = {}

    def _fake_dialog(**kwargs):
        captured.update(kwargs)
        return ""

    with patch("swell.analysis.core.project_workflow.filedialog.asksaveasfilename", side_effect=_fake_dialog):
        project_workflow.save_project_as(app)
    return captured


def test_analysis_save_as_defaults_to_input_folder_name_without_extension() -> None:
    app = SimpleNamespace(
        current_project_path=None,
        _current_image_source_paths=["/tmp/input_folder/frame_001.tif"],
        app_root="/tmp/app",
        root=object(),
    )

    kwargs = _capture_save_as_kwargs(app)

    assert kwargs.get("initialfile") == "input_folder"
    assert kwargs.get("defaultextension") == ".swell"
    assert kwargs.get("initialdir") == str(Path("/tmp/app").resolve())


@pytest.mark.parametrize(
    ("current_path", "expected"),
    [
        ("/tmp/event_1.swell", "event_1"),
        ("/tmp/event_1.SWELL", "event_1"),
        ("/tmp/event_1.txt", "event_1.txt"),
    ],
)
def test_analysis_save_as_initialfile_normalizes_project_suffix_only(current_path: str, expected: str) -> None:
    app = SimpleNamespace(
        current_project_path=current_path,
        _current_image_source_paths=["/tmp/input_folder/frame_001.tif"],
        app_root="/tmp/app",
        root=object(),
    )

    kwargs = _capture_save_as_kwargs(app)

    assert kwargs.get("initialfile") == expected
    assert kwargs.get("defaultextension") == ".swell"
