from pathlib import Path
from unittest.mock import patch

import numpy as np

from sdapp.analysis.core.analysis_controller import AnalysisController


def _make_controller(*, app_root: str, source_paths: list[str], last_scale_path: str = "", input_folder: str = ""):
    return AnalysisController(
        root=None,
        app_root=app_root,
        get_frames_raw=lambda: [np.zeros((8, 8), dtype=np.uint8)],
        get_masks_cache=lambda: {},
        get_paint_layers=lambda: {},
        get_points=lambda: {},
        get_frame_names=lambda: [],
        get_input_folder=lambda: input_folder,
        get_current_image_source_paths=lambda: list(source_paths),
        get_compose_final_mask_for_frame=lambda _idx: None,
        get_nonempty_final_mask_frames=lambda: set(),
        get_frames_per_sec=lambda: 1.0,
        get_scale_px_per_mm=lambda: None,
        set_scale_px_per_mm=lambda _v: None,
        get_scale_points=lambda: [],
        set_scale_points=lambda _v: None,
        get_last_scale_image_path=lambda: last_scale_path,
        set_last_scale_image_path=lambda _v: None,
        get_roi_mask=lambda: None,
        set_roi_mask=lambda _v: None,
        get_roi_points=lambda: [],
        set_roi_points=lambda _v: None,
        update_display=lambda: None,
        log_info=lambda *_args: None,
        log_success=lambda *_args: None,
    )


def test_start_scale_selection_uses_project_source_folder_for_initialdir(tmp_path):
    app_root = tmp_path / "app"
    app_root.mkdir()
    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    frame_path = stack_dir / "frame_001.tif"
    frame_path.write_bytes(b"not-an-image")

    controller = _make_controller(
        app_root=str(app_root),
        source_paths=[str(frame_path)],
    )

    captured: dict = {}

    def _fake_dialog(**kwargs):
        captured.update(kwargs)
        return ""

    with patch("sdapp.analysis.core.analysis_controller.filedialog.askopenfilename", side_effect=_fake_dialog):
        controller.start_scale_selection()

    assert Path(captured["initialdir"]).resolve() == stack_dir.resolve()


def test_start_scale_selection_keeps_last_scale_path_priority(tmp_path):
    app_root = tmp_path / "app"
    app_root.mkdir()
    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    frame_path = stack_dir / "frame_001.tif"
    frame_path.write_bytes(b"not-an-image")
    preferred_dir = tmp_path / "preferred"
    preferred_dir.mkdir()
    last_scale_file = preferred_dir / "scale_ref.png"
    last_scale_file.write_bytes(b"not-an-image")

    controller = _make_controller(
        app_root=str(app_root),
        source_paths=[str(frame_path)],
        last_scale_path=str(last_scale_file),
    )

    captured: dict = {}

    def _fake_dialog(**kwargs):
        captured.update(kwargs)
        return ""

    with patch("sdapp.analysis.core.analysis_controller.filedialog.askopenfilename", side_effect=_fake_dialog):
        controller.start_scale_selection()

    assert Path(captured["initialdir"]).resolve() == preferred_dir.resolve()
