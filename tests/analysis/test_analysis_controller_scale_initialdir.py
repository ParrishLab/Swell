from pathlib import Path
from unittest.mock import patch

import numpy as np

from sdapp.analysis.core.analysis_controller import AnalysisController


def _make_controller(
    *,
    app_root: str,
    source_paths: list[str],
    last_scale_path: str = "",
    input_folder: str = "",
    scale_points: list[tuple[float, float]] | None = None,
):
    return AnalysisController(
        root=None,
        app_root=app_root,
        get_frame_count=lambda: 1,
        get_raw_frame=lambda _idx: np.zeros((8, 8), dtype=np.uint8),
        get_masks_cache=lambda: {},
        get_paint_layers=lambda: {},
        get_points=lambda: {},
        get_frame_names=lambda: [],
        get_import_source_hint=lambda: input_folder,
        get_current_image_source_paths=lambda: list(source_paths),
        get_compose_final_mask_for_frame=lambda _idx: None,
        get_nonempty_final_mask_frames=lambda: set(),
        get_frames_per_sec=lambda: 1.0,
        get_scale_px_per_mm=lambda: None,
        set_scale_px_per_mm=lambda _v: None,
        get_scale_points=lambda: list(scale_points or []),
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

    controller._load_image_u8_from_path = lambda _path: np.zeros((8, 8), dtype=np.uint8)

    with patch("sdapp.analysis.core.analysis_controller.filedialog.askopenfilename") as dialog_mock:
        with patch("sdapp.analysis.core.analysis_controller.open_scale_dialog", return_value=None):
            controller.start_scale_selection()

    dialog_mock.assert_not_called()


def test_capture_scale_selection_passes_existing_scale_points_to_dialog(tmp_path):
    app_root = tmp_path / "app"
    app_root.mkdir()
    image_path = tmp_path / "scale_ref.png"
    image_path.write_bytes(b"not-an-image")

    controller = _make_controller(
        app_root=str(app_root),
        source_paths=[],
        scale_points=[(10.0, 12.0), (30.0, 12.0)],
    )
    controller._load_image_u8_from_path = lambda _path: np.zeros((40, 50), dtype=np.uint8)

    with patch("sdapp.analysis.core.analysis_controller.filedialog.askopenfilename", return_value=str(image_path)):
        with patch("sdapp.analysis.core.analysis_controller.open_scale_dialog", return_value=None) as dialog_mock:
            controller._capture_scale_selection()

    assert dialog_mock.call_args.kwargs["initial_scale_points"] == [(10.0, 12.0), (30.0, 12.0)]


def test_capture_scale_selection_reuses_last_scale_image_path_when_available(tmp_path):
    app_root = tmp_path / "app"
    app_root.mkdir()
    image_path = tmp_path / "scale_ref.png"
    image_path.write_bytes(b"not-an-image")

    controller = _make_controller(
        app_root=str(app_root),
        source_paths=[],
        last_scale_path=str(image_path),
    )
    loaded_paths: list[str] = []
    controller._load_image_u8_from_path = lambda path: loaded_paths.append(str(path)) or np.zeros((40, 50), dtype=np.uint8)

    with patch("sdapp.analysis.core.analysis_controller.filedialog.askopenfilename") as dialog_mock:
        with patch("sdapp.analysis.core.analysis_controller.open_scale_dialog", return_value=None):
            controller._capture_scale_selection()

    dialog_mock.assert_not_called()
    assert loaded_paths == [str(image_path)]


def test_capture_roi_selection_uses_image_picker_with_project_source_initialdir(tmp_path):
    app_root = tmp_path / "app"
    app_root.mkdir()
    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    frame_path = stack_dir / "frame_001.tif"
    frame_path.write_bytes(b"not-an-image")
    roi_image_path = stack_dir / "roi_ref.png"
    roi_image_path.write_bytes(b"not-an-image")

    controller = _make_controller(
        app_root=str(app_root),
        source_paths=[str(frame_path)],
    )
    controller._load_image_u8_from_path = lambda _path: np.zeros((8, 8), dtype=np.uint8)

    captured: dict = {}

    def _fake_dialog(**kwargs):
        captured.update(kwargs)
        return str(roi_image_path)

    with patch("sdapp.analysis.core.analysis_controller.filedialog.askopenfilename", side_effect=_fake_dialog):
        with patch("sdapp.analysis.core.analysis_controller.open_roi_dialog", return_value=None):
            controller._capture_roi_selection()

    assert Path(captured["initialdir"]).resolve() == stack_dir.resolve()
    assert captured["title"] == "Select Image for ROI"
