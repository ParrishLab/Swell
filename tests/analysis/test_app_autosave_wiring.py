from pathlib import Path

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core.project_autosave import AutosaveSnapshot, ProjectAutosaveManager


def test_app_creates_project_autosave_manager(tmp_path):
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.app_root = str(tmp_path)
    app.root = None
    app._current_image_source_paths = []
    app._project_embed_images = False
    app._has_loaded_stack = lambda: True
    app._build_project_payload = lambda: ({}, {"images": []}, {"roi_points": []}, {})
    app.get_input_source_hint = lambda: ""
    app.project_store = type("_Store", (), {"save": lambda *args, **kwargs: None})()
    app._on_autosave_error = lambda *_args: None

    manager = app._create_project_autosave_manager()
    try:
        assert isinstance(manager, ProjectAutosaveManager)
        assert manager.autosave_dir == tmp_path / "autosaves"
    finally:
        manager.stop()


def test_mark_project_dirty_schedules_autosave_when_stack_loaded():
    calls = []
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.project_dirty = False
    app._has_loaded_stack = lambda: True
    app.autosave_manager = type("_Mgr", (), {"schedule": lambda _self, reason: calls.append(reason)})()
    app._on_autosave_error = lambda *_args: None

    SwellAnalysisApp._mark_project_dirty(app, "paint")

    assert app.project_dirty is True
    assert calls == ["paint"]


def test_autosave_snapshot_writer_uses_project_store_save(tmp_path):
    saves = []

    class Store:
        def save(self, *args, **kwargs):
            saves.append((args, kwargs))

    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.project_store = Store()
    snapshot = AutosaveSnapshot(
        project_state={"state": True},
        images_manifest={"images": []},
        roi_data={"roi_points": []},
        event_payloads={"event_001": {"masks": []}},
        embed_images=False,
    )
    target = Path(tmp_path) / "autosave_1.swell"

    SwellAnalysisApp._write_autosave_snapshot(app, snapshot, target)

    assert len(saves) == 1
    args, kwargs = saves[0]
    assert args[:5] == (
        target,
        snapshot.project_state,
        snapshot.images_manifest,
        snapshot.roi_data,
        snapshot.event_payloads,
    )
    assert kwargs == {"embed_images": False}
