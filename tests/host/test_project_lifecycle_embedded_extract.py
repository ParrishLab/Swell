from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sdapp.host.app import SDAnalyzerApp
from sdapp.host.controllers.project_lifecycle_controller import HostProjectLifecycleController
from sdapp.shared.models import StackRef, UnifiedProjectState
from sdapp.shared.persistence import UnifiedProjectStore


class _ImmediateRoot:
    def after(self, _delay: int, callback) -> None:  # noqa: ANN001
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
            engine=SimpleNamespace(set_reader=lambda reader: None),
            mark_processed_cache=SimpleNamespace(clear=lambda: None),
            mark_popup=SimpleNamespace(winfo_exists=lambda: False),
        ),
        preview_scale=SimpleNamespace(configure=lambda **_kwargs: None, set=lambda _value: None),
        analysis_launch_controller=SimpleNamespace(prewarm_analysis_app_class_async=lambda: None),
        _show_warning=lambda title, text: warnings.append((str(title), str(text))),
        _set_status=lambda _text: None,
        _log_info=lambda _text: None,
        _log_warn=lambda _text: None,
        _log_error=lambda _text: None,
        _sync_event_projections=lambda: None,
        _update_preview=lambda _frame_idx: None,
        warmup_main_preview_async=lambda: None,
        current_project_path=None,
        reader=None,
        stack_info=None,
        _embedded_extract_dir=None,
        warnings=warnings,
        session_calls=session_calls,
        bind_calls=bind_calls,
    )


def _make_reader_factory(opened_dirs: list[str]):
    class _Reader:
        def open_stack(self, folder: str):
            opened_dirs.append(str(folder))
            return SimpleNamespace(
                input_dir=str(folder),
                frame_count=3,
                frame_height=16,
                frame_width=16,
                dtype="uint8",
            )

    return lambda *args, **kwargs: _Reader()


def _save_embedded_project(tmp_path: Path) -> tuple[Path, Path]:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for name in ("frame_001.png", "frame_002.png", "frame_003.png"):
        (frames_dir / name).write_bytes(b"fake-image-bytes")

    state = UnifiedProjectState(
        stack_ref=StackRef(
            input_dir=str(frames_dir), frame_count=3, frame_height=16, frame_width=16, dtype="uint8"
        ),
        events=[],
        active_event_id=None,
        metadata={"embed_source_images": True},
    )
    project_path = tmp_path / "project.sdproj"
    UnifiedProjectStore().save(project_path, state)
    return project_path, frames_dir


def test_open_project_extracts_embedded_when_source_folder_missing(tmp_path: Path) -> None:
    project_path, frames_dir = _save_embedded_project(tmp_path)
    # Simulate the original source folder being moved/deleted.
    for f in frames_dir.iterdir():
        f.unlink()
    frames_dir.rmdir()

    app = _build_app()
    controller = HostProjectLifecycleController(app)
    controller.prepare_context_switch = lambda: True
    controller.warmup_main_preview_async = lambda: None

    state = SimpleNamespace(
        project_path=str(project_path),
        stack_ref=SimpleNamespace(input_dir=str(frames_dir)),
    )
    app.browser_controller.open_session = lambda _path: state

    opened_dirs: list[str] = []
    with patch("sdapp.host.controllers.project_lifecycle_controller.threading.Thread", _ImmediateThread):
        with patch("sdapp.host.controllers.project_lifecycle_controller.messagebox.askyesno") as askyesno:
            with patch(
                "sdapp.host.controllers.project_lifecycle_controller.StackReader",
                side_effect=_make_reader_factory(opened_dirs),
            ):
                controller.open_project(str(project_path))

    # Rebind prompt must not fire; stack came from embedded extraction.
    assert askyesno.called is False
    assert len(opened_dirs) == 1
    extracted = opened_dirs[0]
    assert extracted != str(frames_dir)
    assert app._embedded_extract_dir == extracted
    # Extracted dir contains the embedded frames.
    assert {p.name for p in Path(extracted).iterdir() if p.is_file() and not p.name.startswith(".")} == {
        "frame_001.png",
        "frame_002.png",
        "frame_003.png",
    }
    assert app.session_calls["set_stack_ref"] == []
    assert app.warnings == []


def test_open_project_prefers_on_disk_folder_over_embedded(tmp_path: Path) -> None:
    project_path, frames_dir = _save_embedded_project(tmp_path)
    # Source folder still exists -> no extraction.

    app = _build_app()
    controller = HostProjectLifecycleController(app)
    controller.prepare_context_switch = lambda: True
    controller.warmup_main_preview_async = lambda: None

    state = SimpleNamespace(
        project_path=str(project_path),
        stack_ref=SimpleNamespace(input_dir=str(frames_dir)),
    )
    app.browser_controller.open_session = lambda _path: state

    opened_dirs: list[str] = []
    with patch("sdapp.host.controllers.project_lifecycle_controller.threading.Thread", _ImmediateThread):
        with patch(
            "sdapp.host.controllers.project_lifecycle_controller.StackReader",
            side_effect=_make_reader_factory(opened_dirs),
        ):
            controller.open_project(str(project_path))

    assert opened_dirs == [str(frames_dir)]
    assert app._embedded_extract_dir is None
    assert app.warnings == []


def test_cleanup_removes_tracked_extract_dir(tmp_path: Path) -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    extract_dir = tmp_path / "sdproj_embedded_xyz"
    extract_dir.mkdir()
    (extract_dir / "frame_001.png").write_bytes(b"x")
    app._embedded_extract_dir = str(extract_dir)

    controller._cleanup_embedded_extract_dir()

    assert not extract_dir.exists()
    assert app._embedded_extract_dir is None


def test_prepare_context_switch_keeps_current_extract_dir_until_replacement_commits(tmp_path: Path) -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    extract_dir = tmp_path / "sdproj_embedded_live"
    extract_dir.mkdir()
    (extract_dir / "frame_001.png").write_bytes(b"x")
    app._embedded_extract_dir = str(extract_dir)
    controller.close_analysis_windows_with_prompt = lambda: {"ok": True}

    assert controller.prepare_context_switch() is True

    assert extract_dir.exists()
    assert app._embedded_extract_dir == str(extract_dir)


def test_close_with_save_keeps_extract_dir_until_save_completes(tmp_path: Path) -> None:
    app = _build_app()
    controller = HostProjectLifecycleController(app)
    extract_dir = tmp_path / "sdproj_embedded_live"
    extract_dir.mkdir()
    (extract_dir / "frame_001.png").write_bytes(b"x")
    app._embedded_extract_dir = str(extract_dir)
    saved: list[bool] = []
    destroyed: list[bool] = []
    app._instance_bridge = None
    app.root = SimpleNamespace(destroy=lambda: destroyed.append(True))
    app.save_host_session = lambda: saved.append(extract_dir.exists())
    controller.close_analysis_windows_with_prompt = lambda: {"ok": True}
    dirty_states = iter([True, False])
    controller._host_session_is_dirty = lambda: next(dirty_states)
    controller._prompt_three_way_action = lambda **_kwargs: True
    controller._confirm_save_embedding_cost = lambda: True

    result = controller.request_host_close()

    assert result == {"ok": True}
    assert saved == [True]
    assert not extract_dir.exists()
    assert app._embedded_extract_dir is None
    assert destroyed == [True]


def test_save_host_session_blocks_ref_only_save_from_embedded_fallback(tmp_path: Path) -> None:
    extract_dir = tmp_path / "sdproj_embedded_live"
    extract_dir.mkdir()
    missing_source = tmp_path / "missing_source"
    save_calls: list[object] = []
    state = UnifiedProjectState(
        stack_ref=StackRef(
            input_dir=str(missing_source), frame_count=1, frame_height=16, frame_width=16, dtype="uint8"
        ),
        events=[],
        active_event_id=None,
        metadata={"embed_source_images": False},
    )
    session = SimpleNamespace(state=lambda: state)
    app = SimpleNamespace(
        _embedded_extract_dir=str(extract_dir),
        browser_controller=SimpleNamespace(
            session=session,
            save_session=lambda *args, **kwargs: save_calls.append((args, kwargs)),
        ),
    )
    app._active_embedded_extract_dir = lambda: SDAnalyzerApp._active_embedded_extract_dir(app)
    app._session_embed_images_enabled = lambda: SDAnalyzerApp._session_embed_images_enabled(app)
    app._embedded_images_source_dir = lambda: SDAnalyzerApp._embedded_images_source_dir(app)
    app._validate_host_session_save_allowed = lambda: SDAnalyzerApp._validate_host_session_save_allowed(app)

    with pytest.raises(RuntimeError, match="embedded fallback images"):
        SDAnalyzerApp.save_host_session(app, str(tmp_path / "out.sdproj"))

    assert save_calls == []
