from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sdapp.host.controllers.project_lifecycle_controller import HostProjectLifecycleController


def _app_stub():
    logs: list[str] = []
    return SimpleNamespace(
        _log_info=lambda message: logs.append(str(message)),
        root=object(),
        logs=logs,
    )


def test_new_project_cancel_keeps_current_project(monkeypatch) -> None:
    app = _app_stub()
    controller = HostProjectLifecycleController(app)
    calls = {"prepare": 0, "load": []}

    monkeypatch.setattr(controller, "prepare_context_switch", lambda: calls.__setitem__("prepare", calls["prepare"] + 1))
    monkeypatch.setattr(controller, "load_stack_from_folder", lambda folder: calls["load"].append(str(folder)))

    with patch("sdapp.host.controllers.project_lifecycle_controller.filedialog.askdirectory", return_value=""):
        controller.new_project()

    assert calls["prepare"] == 0
    assert calls["load"] == []
    assert any("New Project canceled" in entry for entry in app.logs)


def test_new_project_loads_selected_folder_when_context_switch_allowed(monkeypatch) -> None:
    app = _app_stub()
    controller = HostProjectLifecycleController(app)
    calls = {"prepare": 0, "load": []}

    def _prepare() -> bool:
        calls["prepare"] += 1
        return True

    monkeypatch.setattr(controller, "prepare_context_switch", _prepare)
    monkeypatch.setattr(controller, "load_stack_from_folder", lambda folder: calls["load"].append(str(folder)))

    with patch("sdapp.host.controllers.project_lifecycle_controller.filedialog.askdirectory", return_value="/tmp/input"):
        controller.new_project()

    assert calls["prepare"] == 1
    assert calls["load"] == ["/tmp/input"]


def test_new_project_aborts_if_context_switch_denied(monkeypatch) -> None:
    app = _app_stub()
    controller = HostProjectLifecycleController(app)
    calls = {"prepare": 0, "load": []}

    def _prepare() -> bool:
        calls["prepare"] += 1
        return False

    monkeypatch.setattr(controller, "prepare_context_switch", _prepare)
    monkeypatch.setattr(controller, "load_stack_from_folder", lambda folder: calls["load"].append(str(folder)))

    with patch("sdapp.host.controllers.project_lifecycle_controller.filedialog.askdirectory", return_value="/tmp/input"):
        controller.new_project()

    assert calls["prepare"] == 1
    assert calls["load"] == []


def test_new_project_dialog_is_parented_to_root(monkeypatch) -> None:
    app = _app_stub()
    controller = HostProjectLifecycleController(app)
    calls: dict[str, object] = {}

    monkeypatch.setattr(controller, "prepare_context_switch", lambda: False)

    def _fake_askdirectory(**kwargs):
        calls.update(kwargs)
        return "/tmp/input"

    with patch("sdapp.host.controllers.project_lifecycle_controller.filedialog.askdirectory", side_effect=_fake_askdirectory):
        controller.new_project()

    assert calls.get("parent") is app.root
    assert calls.get("mustexist") is True
