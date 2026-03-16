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
    app.log_info = lambda *_args, **_kwargs: None
    app.log_error = lambda *_args, **_kwargs: None
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


def test_apply_host_metrics_settings_prefills_values() -> None:
    app = _build_app()
    app.frames_per_sec_var = _DummyVar(1.0)
    app.scale_px_per_mm = None
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
            "roi_points": [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0]],
            "roi_mask": mask,
        }
    )

    assert float(app.frames_per_sec_var.get()) == 2.5
    assert float(app.scale_px_per_mm) == 9.0
    assert len(app.roi_points) == 4
    assert np.array_equal(np.asarray(app.roi_mask, dtype=bool), mask)


def test_emit_host_metrics_update_sends_event_local_payload() -> None:
    app = _build_app()
    app._host_mode = True
    app._suppress_metrics_emit = False
    app.frames_per_sec_var = _DummyVar(3.0)
    app.scale_px_per_mm = 7.0
    app.roi_points = [[2.0, 2.0], [4.0, 2.0], [4.0, 4.0]]
    app.roi_mask = np.ones((3, 3), dtype=bool)
    emitted: list[dict] = []
    app._host_metrics_updater = lambda payload: emitted.append(dict(payload)) or {"ok": True}

    result = app._emit_host_metrics_update("test_emit")

    assert isinstance(result, dict) and result.get("ok") is True
    assert len(emitted) == 1
    assert emitted[0]["event_id"] == "event_0001"
    assert float(emitted[0]["metrics_settings"]["frames_per_sec"]) == 3.0
    assert float(emitted[0]["metrics_settings"]["scale_px_per_mm"]) == 7.0
