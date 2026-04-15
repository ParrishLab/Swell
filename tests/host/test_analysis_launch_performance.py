from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

import numpy as np

from sdapp.analysis.core.frame_source import EagerFrameSource
from sdapp.host.controllers.analysis_launch_controller import AnalysisLaunchController
from sdapp.shared.frame_source import PreparedFrameSource
from sdapp.shared.frame_source.launch_preparation import build_launch_preparation_cache_key


def _build_frame_source(frame_count: int = 8) -> EagerFrameSource:
    frames = [np.full((8, 8), fill_value=idx, dtype=np.float32) for idx in range(frame_count)]
    return EagerFrameSource(
        raw_frames=frames,
        subtracted_frames=frames,
        visual_frames=[np.asarray(frame, dtype=np.uint8) for frame in frames],
        frame_names=[f"f{idx}.tif" for idx in range(frame_count)],
        source_paths=["/tmp/stack"] * frame_count,
    )


def _build_app(frame_source: EagerFrameSource) -> SimpleNamespace:
    return SimpleNamespace(
        browser_controller=SimpleNamespace(get_frame_source=lambda: frame_source),
        root=object(),
        _analysis_preview_cache=OrderedDict(),
        _log_info=lambda *_args: None,
        _log_debug=lambda *_args: None,
    )


def test_prepare_analysis_launch_preview_builds_reusable_prepared_source() -> None:
    frame_source = _build_frame_source()
    controller = AnalysisLaunchController(_build_app(frame_source))

    payload = controller._prepare_analysis_launch_preview(
        event_id="event_0042",
        event_start=3,
        event_end=5,
        baseline_pre_frames=2,
        apply_horizontal_bar_denoise=False,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        apply_stabilization=False,
    )

    launch_preparation = payload["launch_preparation"]
    assert isinstance(launch_preparation["prepared_source"], PreparedFrameSource)
    assert launch_preparation["local_frame_idx"] == 2
    assert launch_preparation["baseline_pre_frames"] == 2
    assert launch_preparation["processing"] == {
        "horizontal_bar_denoise": False,
        "smoothing": True,
        "baseline_subtraction": True,
        "global_normalization": True,
        "stabilization": False,
    }
    assert launch_preparation["cache_key"] == build_launch_preparation_cache_key(
        event_id="event_0042",
        scope_start=1,
        scope_end=5,
        baseline_pre_frames=2,
        apply_horizontal_bar_denoise=False,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        apply_stabilization=False,
    )
    np.testing.assert_array_equal(payload["frame_u8"], launch_preparation["preview_frame_u8"])
    np.testing.assert_array_equal(
        launch_preparation["prepared_source"].get_visual_frame(launch_preparation["local_frame_idx"]),
        payload["frame_u8"],
    )


def test_analysis_launch_preview_cache_stores_full_launch_preparation_and_evicts_lru() -> None:
    frame_source = _build_frame_source()
    app = _build_app(frame_source)
    controller = AnalysisLaunchController(app)

    initial_payload = controller._prepare_analysis_launch_preview(
        event_id="event_0000",
        event_start=2,
        event_end=4,
        baseline_pre_frames=2,
        apply_horizontal_bar_denoise=False,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        apply_stabilization=False,
    )
    initial_key = initial_payload["launch_preparation"]["cache_key"]
    controller._cache_preview_entry(initial_key, initial_payload)

    cached = controller._preview_cache()[initial_key]
    assert cached["launch_preparation"]["prepared_source"] is initial_payload["launch_preparation"]["prepared_source"]

    for idx in range(1, 18):
        payload = controller._prepare_analysis_launch_preview(
            event_id=f"event_{idx:04d}",
            event_start=2,
            event_end=4,
            baseline_pre_frames=2,
            apply_horizontal_bar_denoise=False,
            apply_smoothing=True,
            apply_baseline_subtraction=True,
            apply_global_normalization=True,
            apply_stabilization=False,
        )
        controller._cache_preview_entry(payload["launch_preparation"]["cache_key"], payload)

    cache = controller._preview_cache()
    assert len(cache) == 16
    assert initial_key not in cache


def test_default_baseline_pre_frames_for_event_prefers_event_flags() -> None:
    frame_source = _build_frame_source()
    app = _build_app(frame_source)
    app.baseline_pre_frames = 30
    app.browser_controller.get_event = lambda event_id: SimpleNamespace(event_id=str(event_id), flags={"baseline_pre_frames": 7})
    controller = AnalysisLaunchController(app)

    assert controller._default_baseline_pre_frames_for_event("event_0042") == 7


def test_default_baseline_pre_frames_for_event_falls_back_to_app_default() -> None:
    frame_source = _build_frame_source()
    app = _build_app(frame_source)
    app.baseline_pre_frames = 11
    app.browser_controller.get_event = lambda _event_id: SimpleNamespace(flags={})
    controller = AnalysisLaunchController(app)

    assert controller._default_baseline_pre_frames_for_event("event_0042") == 11


def test_default_processing_options_for_event_prefers_event_flags() -> None:
    frame_source = _build_frame_source()
    app = _build_app(frame_source)
    app.browser_controller.get_event = lambda _event_id: SimpleNamespace(
        flags={
            "analysis_processing": {
                "horizontal_bar_denoise": True,
                "smoothing": False,
                "baseline_subtraction": False,
                "global_normalization": False,
                "stabilization": True,
            }
        }
    )
    controller = AnalysisLaunchController(app)

    assert controller._default_processing_options_for_event("event_0042") == {
        "horizontal_bar_denoise": True,
        "smoothing": False,
        "baseline_subtraction": False,
        "global_normalization": False,
        "stabilization": True,
    }


def test_default_processing_options_for_event_falls_back_to_defaults() -> None:
    frame_source = _build_frame_source()
    app = _build_app(frame_source)
    app.browser_controller.get_event = lambda _event_id: SimpleNamespace(flags={})
    controller = AnalysisLaunchController(app)

    assert controller._default_processing_options_for_event("event_0042") == {
        "horizontal_bar_denoise": False,
        "smoothing": True,
        "baseline_subtraction": True,
        "global_normalization": True,
        "stabilization": False,
    }


def test_event_display_name_prefers_event_label() -> None:
    frame_source = _build_frame_source()
    app = _build_app(frame_source)
    app.browser_controller.get_event = lambda event_id: SimpleNamespace(event_id=str(event_id), label="Halo(Light Off) 1")
    controller = AnalysisLaunchController(app)

    assert controller._event_display_name("event_0042") == "Halo(Light Off) 1"
