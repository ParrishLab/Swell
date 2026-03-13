from __future__ import annotations

from sdapp.analysis.app import SDSegmentationApp


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
        lambda title, text: warned.append((str(title), str(text))),
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
        lambda title, text: info_calls.append((str(title), str(text))),
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
        lambda title, text: info_calls.append((str(title), str(text))),
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
        lambda title, text: info_calls.append((str(title), str(text))),
    )
    monkeypatch.setattr(
        "sdapp.analysis.app.messagebox.askyesno",
        lambda *_args, **_kwargs: ask_calls.append("ask") or True,
    )

    app.save_current_masks()

    assert save_calls == ["save"]
    assert ask_calls == []
    assert info_calls
