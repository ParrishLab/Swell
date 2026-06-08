from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sdapp.host.controllers.project_lifecycle_controller import HostProjectLifecycleController


class _ImmediateRoot:
    def __init__(self) -> None:
        self.after_calls: list[int] = []

    def after(self, _delay: int, callback) -> None:  # noqa: ANN001
        self.after_calls.append(int(_delay))
        callback()


class _ImmediateThread:
    def __init__(self, *, target, daemon: bool) -> None:  # noqa: ANN001
        self._target = target
        self.daemon = daemon

    def start(self) -> None:
        self._target()


def _build_app():
    warnings: list[tuple[str, str]] = []
    session_calls = {"set_project_path": [], "set_stack_ref": []}
    bind_calls: list[object] = []
    popup_readers: list[object] = []

    session = SimpleNamespace(
        set_project_path=lambda value: session_calls["set_project_path"].append(value),
        set_stack_ref=lambda value: session_calls["set_stack_ref"].append(value),
    )
    browser_controller = SimpleNamespace(
        session=session,
        open_session=lambda _path: None,
        bind_frame_source=lambda reader: bind_calls.append(reader),
        selected_event=lambda: None,
    )
    return SimpleNamespace(
        root=_ImmediateRoot(),
        browser_controller=browser_controller,
        _popup=SimpleNamespace(
            engine=SimpleNamespace(set_reader=lambda reader: popup_readers.append(reader)),
            mark_processed_cache=SimpleNamespace(clear=lambda: None),
            mark_popup=SimpleNamespace(winfo_exists=lambda: False),
        ),
        preview_scale=SimpleNamespace(configure=lambda **_kwargs: None, set=lambda _value: None),
        analysis_launch_controller=SimpleNamespace(prewarm_analysis_app_class_async=lambda: None),
        _show_warning=lambda title, text: warnings.append((str(title), str(text))),
        _set_status=lambda _text: None,
        _log_info=lambda _text: None,
        _log_error=lambda _text: None,
        _sync_event_projections=lambda: None,
        _update_preview=lambda _frame_idx: None,
        warmup_main_preview_async=lambda: None,
        current_project_path=None,
        reader=None,
        stack_info=None,
        warnings=warnings,
        session_calls=session_calls,
        bind_calls=bind_calls,
        popup_readers=popup_readers,
    )


def test_open_project_rebinds_missing_stack_folder_when_user_selects_replacement(tmp_path: Path) -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    controller.prepare_context_switch = lambda: True
    controller.warmup_main_preview_async = lambda: None

    missing_dir = tmp_path / "missing"
    replacement_dir = tmp_path / "replacement"
    replacement_dir.mkdir()
    project_path = tmp_path / "project.sdproj"
    state = SimpleNamespace(
        project_path=str(project_path),
        stack_ref=SimpleNamespace(input_dir=str(missing_dir)),
    )
    stack_info = SimpleNamespace(
        input_dir=str(replacement_dir),
        frame_count=12,
        frame_height=8,
        frame_width=9,
        dtype="uint8",
    )
    opened_dirs: list[str] = []

    class _Reader:
        def open_stack(self, folder: str):
            opened_dirs.append(str(folder))
            return stack_info

    app.browser_controller.open_session = lambda _path: state

    with patch("sdapp.host.controllers.project_lifecycle_controller.threading.Thread", _ImmediateThread):
        with patch("sdapp.host.controllers.project_lifecycle_controller.messagebox.askyesno", return_value=True):
            with patch(
                "sdapp.host.controllers.project_lifecycle_controller.filedialog.askdirectory",
                return_value=str(replacement_dir),
            ):
                with patch("sdapp.host.controllers.project_lifecycle_controller.StackReader", return_value=_Reader()):
                    controller.open_project(str(project_path))

    assert opened_dirs == [str(replacement_dir)]
    assert app.current_project_path == str(project_path)
    assert app.session_calls["set_project_path"] == [str(project_path)]
    assert len(app.session_calls["set_stack_ref"]) == 1
    repaired_ref = app.session_calls["set_stack_ref"][0]
    assert str(repaired_ref.input_dir) == str(replacement_dir)
    assert app.bind_calls
    assert app.popup_readers == app.bind_calls
    assert app.warnings == []


def test_open_project_warns_when_missing_stack_folder_is_not_rebound(tmp_path: Path) -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    controller.prepare_context_switch = lambda: True
    controller.warmup_main_preview_async = lambda: None

    missing_dir = tmp_path / "missing"
    project_path = tmp_path / "project.sdproj"
    state = SimpleNamespace(
        project_path=str(project_path),
        stack_ref=SimpleNamespace(input_dir=str(missing_dir)),
    )
    app.browser_controller.open_session = lambda _path: state

    with patch("sdapp.host.controllers.project_lifecycle_controller.threading.Thread", _ImmediateThread):
        with patch("sdapp.host.controllers.project_lifecycle_controller.messagebox.askyesno", return_value=False):
            with patch("sdapp.host.controllers.project_lifecycle_controller.StackReader") as reader_cls:
                controller.open_project(str(project_path))

    assert reader_cls.called is False
    assert app.session_calls["set_project_path"] == [str(project_path)]
    assert app.session_calls["set_stack_ref"] == []
    assert len(app.warnings) == 1
    assert "missing and was not rebound" in app.warnings[0][1]


def test_active_stack_rebinds_when_loaded_folder_moves(tmp_path: Path) -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    missing_dir = tmp_path / "old_stack"
    replacement_dir = tmp_path / "replacement"
    replacement_dir.mkdir()
    stack_info = SimpleNamespace(
        input_dir=str(replacement_dir),
        frame_count=5,
        frame_height=8,
        frame_width=9,
        dtype="uint8",
    )
    opened_dirs: list[str] = []

    class _Reader:
        def open_stack(self, folder: str):
            opened_dirs.append(str(folder))
            return stack_info

    app.reader = SimpleNamespace(missing_source_paths=lambda limit=1: [missing_dir])
    app.stack_info = SimpleNamespace(input_dir=str(missing_dir), frame_count=5)
    app.input_var = SimpleNamespace(set=lambda value: setattr(app, "input_value", value))
    app._main_render_cache = {}
    app._normalized_frame_u8_cache = {}
    app._analysis_preview_cache = {}

    with patch("sdapp.host.controllers.project_lifecycle_controller.messagebox.askyesno", return_value=True):
        with patch(
            "sdapp.host.controllers.project_lifecycle_controller.filedialog.askdirectory",
            return_value=str(replacement_dir),
        ):
            with patch("sdapp.host.controllers.project_lifecycle_controller.StackReader", return_value=_Reader()):
                ok = controller.ensure_active_stack_available()

    assert ok is True
    assert opened_dirs == [str(replacement_dir)]
    assert app.stack_info is stack_info
    assert app.reader is not None
    assert app.session_calls["set_stack_ref"]
    assert str(app.session_calls["set_stack_ref"][-1].input_dir) == str(replacement_dir)
    assert app.input_value == str(replacement_dir)


def test_active_stack_missing_without_rebind_warns_and_keeps_existing_state(tmp_path: Path) -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    missing_dir = tmp_path / "old_stack"
    stale_reader = SimpleNamespace(missing_source_paths=lambda limit=1: [missing_dir])
    app.reader = stale_reader
    app.stack_info = SimpleNamespace(input_dir=str(missing_dir), frame_count=5)

    with patch("sdapp.host.controllers.project_lifecycle_controller.messagebox.askyesno", return_value=False):
        ok = controller.ensure_active_stack_available(title="Open Analysis")

    assert ok is False
    assert app.reader is stale_reader
    assert app.session_calls["set_stack_ref"] == []
    assert app.warnings
    assert "missing and was not rebound" in app.warnings[-1][1]


def test_run_on_ui_thread_posts_callback_when_called_off_main_thread() -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    worker_thread = object()

    with patch("sdapp.host.controllers.project_lifecycle_controller.threading.current_thread", return_value=worker_thread):
        with patch("sdapp.host.controllers.project_lifecycle_controller.threading.main_thread", return_value=object()):
            result = controller._run_on_ui_thread(lambda: "ok")

    assert result == "ok"
    assert app.root.after_calls == [0]


def test_run_on_ui_thread_times_out_if_callback_never_runs() -> None:
    class _Root:
        def after(self, _delay: int, _callback) -> None:  # noqa: ANN001
            return None

    app = _build_app()
    app.root = _Root()
    controller = HostProjectLifecycleController(app)
    worker_thread = object()

    with patch("sdapp.host.controllers.project_lifecycle_controller.threading.current_thread", return_value=worker_thread):
        with patch("sdapp.host.controllers.project_lifecycle_controller.threading.main_thread", return_value=object()):
            with patch("sdapp.host.controllers.project_lifecycle_controller.threading.Event") as event_cls:
                event_cls.return_value.wait.return_value = False
                try:
                    controller._run_on_ui_thread(lambda: "never")
                except RuntimeError as exc:
                    assert "Timed out waiting for the UI thread" in str(exc)
                else:
                    raise AssertionError("expected timeout")
