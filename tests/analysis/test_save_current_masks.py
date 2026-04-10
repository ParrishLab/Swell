from __future__ import annotations

import numpy as np

from sdapp.analysis.app import SDSegmentationApp


class _DummyVar:
    def __init__(self, value=1.0) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def _build_app() -> SDSegmentationApp:
    app = SDSegmentationApp.__new__(SDSegmentationApp)
    app.current_project_path = None
    app.active_event_id = "event_0001"
    app.project_dirty = False
    app._host_mode = True
    app._host_project_path_provider = None
    app._saved_project_masks_by_event = {}
    app._scale_is_local_override = False
    app._roi_is_local_override = False
    app.log_info = lambda *_args, **_kwargs: None
    app.log_warn = lambda *_args, **_kwargs: None
    app.log_error = lambda *_args, **_kwargs: None
    app._emit_host_sync = lambda *_args, **_kwargs: {"ok": True}
    app.save_project = lambda: None
    app.save_project_as = lambda: None
    app._collect_nonempty_final_mask_frames = lambda: set()
    app.event_records = {}
    return app


def test_save_current_masks_warns_when_no_masks(monkeypatch):
    app = _build_app()
    warned: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showwarning",
        lambda title, text, **_kwargs: warned.append((str(title), str(text))),
    )

    app.save_current_masks()

    assert warned == [("No Masks", "Please generate masks first.")]


def test_save_current_masks_declines_overwrite_when_saved_masks_exist(monkeypatch):
    app = _build_app()
    app._host_mode = True
    app.current_project_path = "/tmp/test.sdproj"
    app._collect_nonempty_final_mask_frames = lambda: {3}
    app._saved_project_masks_by_event = {"event_0001": True}
    save_calls: list[str] = []
    app.save_project = lambda: save_calls.append("save")
    monkeypatch.setattr("sdapp.analysis.app.messagebox.askyesno", lambda *_args, **_kwargs: False)

    app.save_current_masks()

    assert save_calls == []


def test_save_current_masks_prompts_save_as_when_no_project(monkeypatch):
    app = _build_app()
    app._collect_nonempty_final_mask_frames = lambda: {2}
    save_as_calls: list[str] = []
    info_calls: list[tuple[str, str]] = []
    app.save_project_as = lambda: save_as_calls.append("save_as")
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showinfo",
        lambda title, text, **_kwargs: info_calls.append((str(title), str(text))),
    )
    monkeypatch.setattr("sdapp.analysis.app.messagebox.askyesno", lambda *_args, **_kwargs: True)

    app.save_current_masks()

    assert save_as_calls == ["save_as"]
    assert info_calls == []


def test_save_current_masks_uses_host_project_path_provider_without_save_as(monkeypatch):
    app = _build_app()
    app._host_mode = True
    app._collect_nonempty_final_mask_frames = lambda: {1, 2}
    app._host_project_path_provider = lambda: "/tmp/from_host.sdproj"
    save_calls: list[str] = []
    save_as_calls: list[str] = []
    info_calls: list[tuple[str, str]] = []
    app.save_project = lambda: save_calls.append("save")
    app.save_project_as = lambda: save_as_calls.append("save_as")
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showinfo",
        lambda title, text, **_kwargs: info_calls.append((str(title), str(text))),
    )
    monkeypatch.setattr("sdapp.analysis.app.messagebox.askyesno", lambda *_args, **_kwargs: True)

    app.save_current_masks()

    assert app.current_project_path.endswith("from_host.sdproj")
    assert save_calls == ["save"]
    assert save_as_calls == []
    assert info_calls


def test_save_current_masks_emits_host_analysis_sync_before_save(monkeypatch):
    app = _build_app()
    app._host_mode = True
    app.current_project_path = "/tmp/test.sdproj"
    app._collect_nonempty_final_mask_frames = lambda: {1, 2}
    calls: list[str] = []
    app._emit_host_sync = lambda reason="": calls.append(f"sync:{reason}") or {"ok": True}
    app.save_project = lambda: calls.append("save")
    monkeypatch.setattr("sdapp.analysis.app.messagebox.askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("sdapp.analysis.app.messagebox.showinfo", lambda *_args, **_kwargs: None)

    app.save_current_masks()

    assert calls == ["sync:save_current_masks", "save"]


def test_save_current_masks_handles_invalid_host_project_path_provider(monkeypatch):
    app = _build_app()
    app._host_mode = True
    app._collect_nonempty_final_mask_frames = lambda: {1}
    app._host_project_path_provider = lambda: "bad\0path.sdproj"
    save_as_calls: list[str] = []
    app.save_project_as = lambda: save_as_calls.append("save_as")
    monkeypatch.setattr("sdapp.analysis.app.messagebox.showinfo", lambda *_args, **_kwargs: None)

    app.save_current_masks()

    assert save_as_calls == ["save_as"]
    assert app.current_project_path is None


def test_save_current_masks_saves_to_existing_project_without_overwrite_prompt(monkeypatch):
    app = _build_app()
    app.current_project_path = "/tmp/test.sdproj"
    app._collect_nonempty_final_mask_frames = lambda: {1, 2}
    save_calls: list[str] = []
    ask_calls: list[str] = []
    info_calls: list[tuple[str, str]] = []
    app.save_project = lambda: save_calls.append("save")
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showinfo",
        lambda title, text, **_kwargs: info_calls.append((str(title), str(text))),
    )
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.askyesno",
        lambda *_args, **_kwargs: ask_calls.append("ask") or True,
    )

    app.save_current_masks()

    assert save_calls == ["save"]
    assert ask_calls == []
    assert info_calls


def test_save_current_masks_shows_error_when_save_project_raises_non_runtime_error(monkeypatch):
    app = _build_app()
    app.current_project_path = "/tmp/test.sdproj"
    app._collect_nonempty_final_mask_frames = lambda: {1}
    errors: list[tuple[str, str]] = []

    def _raise_os_error():
        raise OSError("disk write failed")

    app.save_project = _raise_os_error
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showerror",
        lambda title, text, **_kwargs: errors.append((str(title), str(text))),
    )

    app.save_current_masks()

    assert errors == [("Save Current Masks", "disk write failed")]


def test_save_current_masks_uses_committed_payload_when_live_mask_set_empty(monkeypatch):
    app = _build_app()
    app.current_project_path = "/tmp/test.sdproj"
    app._collect_nonempty_final_mask_frames = lambda: set()
    app.seg_state = type("S", (), {"invalidate_final_mask_frames": lambda self: None})()
    app.analysis_workspace = type(
        "W",
        (),
        {
            "export_active_event_analysis_payload": staticmethod(
                lambda: {"masks_committed": {1: np.array([[True]], dtype=bool)}, "masks_draft": None}
            )
        },
    )()
    save_calls: list[str] = []
    warned: list[tuple[str, str]] = []
    app.save_project = lambda: save_calls.append("save")
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showwarning",
        lambda title, text, **_kwargs: warned.append((str(title), str(text))),
    )
    monkeypatch.setattr("sdapp.analysis.app.messagebox.askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("sdapp.analysis.app.messagebox.showinfo", lambda *_args, **_kwargs: None)

    app.save_current_masks()

    assert warned == []
    assert save_calls == ["save"]


def test_save_current_masks_uses_draft_payload_when_live_mask_set_empty(monkeypatch):
    app = _build_app()
    app.current_project_path = "/tmp/test.sdproj"
    app._collect_nonempty_final_mask_frames = lambda: set()
    app.seg_state = type("S", (), {"invalidate_final_mask_frames": lambda self: None})()
    app.analysis_workspace = type(
        "W",
        (),
        {
            "export_active_event_analysis_payload": staticmethod(
                lambda: {"masks_committed": {}, "masks_draft": {2: np.array([[True]], dtype=bool)}}
            )
        },
    )()
    save_calls: list[str] = []
    warned: list[tuple[str, str]] = []
    app.save_project = lambda: save_calls.append("save")
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showwarning",
        lambda title, text, **_kwargs: warned.append((str(title), str(text))),
    )
    monkeypatch.setattr("sdapp.analysis.app.messagebox.askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("sdapp.analysis.app.messagebox.showinfo", lambda *_args, **_kwargs: None)

    app.save_current_masks()

    assert warned == []
    assert save_calls == ["save"]


def test_save_current_masks_uses_seg_state_masks_when_collect_returns_empty(monkeypatch):
    app = _build_app()
    app.current_project_path = "/tmp/test.sdproj"
    app._collect_nonempty_final_mask_frames = lambda: set()
    app.seg_state = type(
        "S",
        (),
        {
            "invalidate_final_mask_frames": lambda self: None,
            "masks_cache": {4: np.array([[True]], dtype=bool)},
            "paint_layers": {},
        },
    )()
    app.analysis_workspace = type("W", (), {"export_active_event_analysis_payload": staticmethod(lambda: None)})()
    save_calls: list[str] = []
    warned: list[tuple[str, str]] = []
    app.save_project = lambda: save_calls.append("save")
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.showwarning",
        lambda title, text, **_kwargs: warned.append((str(title), str(text))),
    )
    monkeypatch.setattr("sdapp.analysis.app.messagebox.askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("sdapp.analysis.app.messagebox.showinfo", lambda *_args, **_kwargs: None)

    app.save_current_masks()

    assert warned == []
    assert save_calls == ["save"]


def test_apply_host_metrics_settings_prefills_values() -> None:
    app = _build_app()
    app.frames_per_sec_var = _DummyVar(1.0)
    app.scale_px_per_mm = None
    app.scale_points = []
    app.roi_points = []
    app.roi_mask = None
    app._suppress_metrics_emit = False
    app._ui_alive = lambda: False

    mask = np.zeros((4, 5), dtype=bool)
    mask[1:3, 2:4] = True
    app._apply_host_metrics_settings(
        {
            "frames_per_sec": 2.5,
            "scale_px_per_mm": 9.0,
            "scale_points": [[10.0, 12.0], [30.0, 12.0]],
            "scale_axis_lock": False,
            "roi_points": [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0]],
            "roi_mask": mask,
        }
    )

    assert float(app.frames_per_sec_var.get()) == 2.5
    assert float(app.scale_px_per_mm) == 9.0
    assert app.scale_points == [[10.0, 12.0], [30.0, 12.0]]
    assert app.scale_axis_lock is False
    assert len(app.roi_points) == 4
    assert np.array_equal(np.asarray(app.roi_mask, dtype=bool), mask)
    assert app._scale_is_local_override is False
    assert app._roi_is_local_override is False


def test_apply_host_metrics_settings_tracks_local_override_provenance() -> None:
    app = _build_app()
    app.frames_per_sec_var = _DummyVar(1.0)
    app.scale_px_per_mm = None
    app.scale_points = []
    app.roi_points = []
    app.roi_mask = None
    app._suppress_metrics_emit = False
    app._ui_alive = lambda: False

    local_mask = np.zeros((4, 5), dtype=bool)
    local_mask[0:2, 1:3] = True
    app._apply_host_metrics_settings(
        {
            "frames_per_sec": 2.5,
            "scale_px_per_mm": 9.0,
            "scale_points": [[10.0, 12.0], [30.0, 12.0]],
            "roi_points": [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0]],
            "roi_mask": local_mask,
        },
        {
            "scale_px_per_mm": 9.0,
            "scale_points": [[10.0, 12.0], [30.0, 12.0]],
            "roi_points": [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0]],
            "roi_mask": local_mask,
        },
    )

    assert app._scale_is_local_override is True
    assert app._roi_is_local_override is True


def test_emit_host_metrics_update_sends_event_local_payload() -> None:
    app = _build_app()
    app._host_mode = True
    app._suppress_metrics_emit = False
    app.frames_per_sec_var = _DummyVar(3.0)
    app.scale_px_per_mm = 7.0
    app.scale_points = [[10.0, 12.0], [30.0, 12.0]]
    app.roi_points = [[2.0, 2.0], [4.0, 2.0], [4.0, 4.0]]
    app.roi_mask = np.ones((3, 3), dtype=bool)
    app._scale_is_local_override = True
    app._roi_is_local_override = True
    emitted: list[dict] = []
    app._host_metrics_updater = lambda payload: emitted.append(dict(payload)) or {"ok": True}

    result = app._emit_host_metrics_update("test_emit")

    assert isinstance(result, dict) and result.get("ok") is True
    assert len(emitted) == 1
    assert emitted[0]["event_id"] == "event_0001"
    assert float(emitted[0]["metrics_settings"]["frames_per_sec"]) == 3.0
    assert float(emitted[0]["metrics_settings"]["scale_px_per_mm"]) == 7.0
    assert emitted[0]["metrics_settings"]["scale_points"] == [[10.0, 12.0], [30.0, 12.0]]


def test_emit_host_global_metrics_update_sends_payload_without_event_id() -> None:
    app = _build_app()
    app._host_mode = True
    app._suppress_metrics_emit = False
    emitted: list[dict] = []
    app._host_global_metrics_updater = lambda payload: emitted.append(dict(payload)) or {"ok": True}

    result = app._emit_host_global_metrics_update(
        "global_scale",
        {"scale_px_per_mm": 7.0, "scale_points": [[10.0, 12.0], [30.0, 12.0]], "roi_points": [[1.0, 1.0], [2.0, 2.0]]},
    )

    assert isinstance(result, dict) and result.get("ok") is True
    assert len(emitted) == 1
    assert "event_id" not in emitted[0]
    assert emitted[0]["reason"] == "global_scale"
    assert float(emitted[0]["metrics_settings"]["scale_px_per_mm"]) == 7.0
    assert emitted[0]["metrics_settings"]["scale_points"] == [[10.0, 12.0], [30.0, 12.0]]


def test_emit_host_global_metrics_update_handles_rejection() -> None:
    app = _build_app()
    app._host_mode = True
    app._suppress_metrics_emit = False
    app._host_global_metrics_updater = lambda payload: {"ok": False, "code": "PAYLOAD_INVALID", "message": "bad payload"}

    result = app._emit_host_global_metrics_update("global_roi", {"roi_points": [[1.0, 1.0], [2.0, 2.0], [3.0, 1.0]]})

    assert isinstance(result, dict)
    assert result["ok"] is False


def test_autosave_project_after_metrics_commit_saves_host_project() -> None:
    app = _build_app()
    app.current_project_path = "/tmp/test.sdproj"
    save_calls: list[str] = []
    app.save_project = lambda: save_calls.append("save")

    result = app._autosave_project_after_metrics_commit("local_scale")

    assert result["ok"] is True
    assert save_calls == ["save"]


def test_autosave_project_after_metrics_commit_reports_incomplete_save() -> None:
    app = _build_app()
    app.current_project_path = None
    app.save_project = lambda: None

    result = app._autosave_project_after_metrics_commit("global_roi")

    assert result["ok"] is False
    assert result["code"] == "SAVE_INCOMPLETE"
