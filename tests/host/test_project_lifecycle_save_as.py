from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from swell.host.controllers.project_lifecycle_controller import HostProjectLifecycleController


class _OutputVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = str(value)


def _build_app_stub(current_project_path: str | None):
    warnings: list[tuple[str, str]] = []
    return SimpleNamespace(
        stack_info=SimpleNamespace(input_dir="/tmp/input_folder"),
        current_project_path=current_project_path,
        output_var=_OutputVar("/tmp/output"),
        root=object(),
        _show_warning=lambda title, text: warnings.append((str(title), str(text))),
        warnings=warnings,
    )


def _capture_save_as_kwargs(controller: HostProjectLifecycleController) -> dict:
    captured: dict[str, object] = {}

    def _fake_dialog(**kwargs):
        captured.update(kwargs)
        return ""

    with patch("swell.host.controllers.project_lifecycle_controller.filedialog.asksaveasfilename", side_effect=_fake_dialog):
        controller.save_project_as()
    return captured


def test_save_as_defaults_to_input_folder_name_without_extension() -> None:
    app = _build_app_stub(current_project_path=None)
    controller = HostProjectLifecycleController(app)

    kwargs = _capture_save_as_kwargs(controller)

    assert kwargs.get("initialfile") == "input_folder"
    assert kwargs.get("defaultextension") == ".swell"
    assert kwargs.get("initialdir") == "/tmp/output"


@pytest.mark.parametrize(
    ("current_path", "expected"),
    [
        ("/tmp/my_project.swell", "my_project"),
        ("/tmp/my_project.SWELL", "my_project"),
        ("/tmp/my_project.txt", "my_project.txt"),
    ],
)
def test_save_as_initialfile_normalizes_project_suffix_only(current_path: str, expected: str) -> None:
    app = _build_app_stub(current_project_path=current_path)
    controller = HostProjectLifecycleController(app)

    kwargs = _capture_save_as_kwargs(controller)

    assert kwargs.get("initialfile") == expected
    assert kwargs.get("defaultextension") == ".swell"


def test_save_project_rejects_missing_current_project_path(tmp_path: Path) -> None:
    calls: list[str] = []
    app = _build_app_stub(current_project_path=str(tmp_path / "renamed_elsewhere.swell"))
    app.save_host_session = lambda path=None: calls.append(str(path))
    app._set_status = lambda _text: None
    app.browser_controller = SimpleNamespace(session=SimpleNamespace(set_project_path=lambda _path: None))
    controller = HostProjectLifecycleController(app)

    controller.save_project()

    assert calls == []
    assert app.warnings
    assert "no longer exists" in app.warnings[-1][1]


def test_save_as_defaults_exports_to_saved_project_folder(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "saved-projects"
    project_dir.mkdir()
    project_path = project_dir / "experiment.swell"
    app = _build_app_stub(current_project_path=None)
    app._set_status = lambda _text: None
    app._log_info = lambda _text: None
    app.browser_controller = SimpleNamespace(session=SimpleNamespace(set_project_path=lambda _path: None))
    app.save_host_session = lambda path: SimpleNamespace(project_path=str(path))
    controller = HostProjectLifecycleController(app)

    class _ImmediateRunner:
        @staticmethod
        def start(task, *, on_success, on_error) -> None:
            try:
                on_success(task())
            except Exception as exc:  # pragma: no cover - assertion output is clearer through on_error
                on_error(exc)

    monkeypatch.setattr(controller, "_task_runner", lambda: _ImmediateRunner())
    monkeypatch.setattr(
        "swell.host.controllers.project_lifecycle_controller.filedialog.asksaveasfilename",
        lambda **_kwargs: str(project_path),
    )

    controller.save_project_as()

    assert app.output_var.get() == str(project_dir.resolve())


def test_same_project_save_does_not_replace_custom_export_folder(tmp_path: Path) -> None:
    project_path = tmp_path / "experiment.swell"
    custom_export_dir = tmp_path / "custom-exports"
    app = _build_app_stub(current_project_path=str(project_path))
    app.output_var.set(str(custom_export_dir))
    controller = HostProjectLifecycleController(app)

    controller._set_export_default_from_project_path(
        project_path,
        previous_project_path=project_path,
    )

    assert app.output_var.get() == str(custom_export_dir)
