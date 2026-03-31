from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sdapp.host.controllers.project_lifecycle_controller import HostProjectLifecycleController


def _build_app_stub(current_project_path: str | None):
    warnings: list[tuple[str, str]] = []
    return SimpleNamespace(
        stack_info=SimpleNamespace(input_dir="/tmp/input_folder"),
        current_project_path=current_project_path,
        output_var=SimpleNamespace(get=lambda: "/tmp/output"),
        root=object(),
        _show_warning=lambda title, text: warnings.append((str(title), str(text))),
        warnings=warnings,
    )


def _capture_save_as_kwargs(controller: HostProjectLifecycleController) -> dict:
    captured: dict[str, object] = {}

    def _fake_dialog(**kwargs):
        captured.update(kwargs)
        return ""

    with patch("sdapp.host.controllers.project_lifecycle_controller.filedialog.asksaveasfilename", side_effect=_fake_dialog):
        controller.save_project_as()
    return captured


def test_save_as_defaults_to_input_folder_name_without_extension() -> None:
    app = _build_app_stub(current_project_path=None)
    controller = HostProjectLifecycleController(app)

    kwargs = _capture_save_as_kwargs(controller)

    assert kwargs.get("initialfile") == "input_folder"
    assert kwargs.get("defaultextension") == ".sdproj"
    assert kwargs.get("initialdir") == "/tmp/output"


@pytest.mark.parametrize(
    ("current_path", "expected"),
    [
        ("/tmp/my_project.sdproj", "my_project"),
        ("/tmp/my_project.SDPROJ", "my_project"),
        ("/tmp/my_project.txt", "my_project.txt"),
    ],
)
def test_save_as_initialfile_normalizes_project_suffix_only(current_path: str, expected: str) -> None:
    app = _build_app_stub(current_project_path=current_path)
    controller = HostProjectLifecycleController(app)

    kwargs = _capture_save_as_kwargs(controller)

    assert kwargs.get("initialfile") == expected
    assert kwargs.get("defaultextension") == ".sdproj"
