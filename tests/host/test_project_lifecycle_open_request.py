from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from swell.host.controllers.project_lifecycle_controller import HostProjectLifecycleController


def _build_app_stub():
    warnings: list[tuple[str, str]] = []
    return SimpleNamespace(
        _show_warning=lambda title, text: warnings.append((str(title), str(text))),
        warnings=warnings,
    )


def test_open_project_request_rejects_empty_path() -> None:
    app = _build_app_stub()
    controller = HostProjectLifecycleController(app)
    ok = controller.open_project_request("")
    assert ok is False
    assert app.warnings
    assert app.warnings[-1][0] == "Open Swell Project"


def test_open_project_request_rejects_non_swell_extension(tmp_path: Path) -> None:
    app = _build_app_stub()
    controller = HostProjectLifecycleController(app)
    path = tmp_path / "bad.txt"
    path.write_text("x", encoding="utf-8")
    ok = controller.open_project_request(str(path))
    assert ok is False
    assert "Expected .swell" in app.warnings[-1][1]


def test_open_project_request_rejects_missing_file(tmp_path: Path) -> None:
    app = _build_app_stub()
    controller = HostProjectLifecycleController(app)
    missing = tmp_path / "missing.swell"
    ok = controller.open_project_request(str(missing))
    assert ok is False
    assert "not found" in app.warnings[-1][1]


def test_open_project_request_calls_open_project_for_valid_path(tmp_path: Path, monkeypatch) -> None:
    app = _build_app_stub()
    controller = HostProjectLifecycleController(app)
    target = tmp_path / "valid.swell"
    target.write_text("placeholder", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(controller, "open_project", lambda path: opened.append(str(path)))

    ok = controller.open_project_request(str(target))

    assert ok is True
    assert opened == [str(target.resolve())]
    assert app.warnings == []


def test_open_project_request_accepts_uppercase_extension_for_existing_projects(tmp_path: Path, monkeypatch) -> None:
    app = _build_app_stub()
    controller = HostProjectLifecycleController(app)
    target = tmp_path / "legacy.SWELL"
    target.write_text("placeholder", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(controller, "open_project", lambda path: opened.append(str(path)))

    ok = controller.open_project_request(str(target))

    assert ok is True
    assert opened == [str(target.resolve())]


def test_open_project_request_handles_path_resolution_errors(monkeypatch) -> None:
    app = _build_app_stub()
    controller = HostProjectLifecycleController(app)

    def _raise_resolve(self, *args, **kwargs):  # noqa: ANN001, ARG001
        raise OSError("invalid path")

    monkeypatch.setattr(Path, "resolve", _raise_resolve)
    ok = controller.open_project_request("bad.swell")

    assert ok is False
    assert app.warnings
    assert "Unable to resolve project path" in app.warnings[-1][1]
