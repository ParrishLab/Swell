from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from swell.analysis.controllers.host_mode_controller import AnalysisHostModeController
from swell.analysis.core.frame_source import EagerFrameSource
from swell.shared.frame_source import EventScopedFrameSource, PreparedFrameSource
from swell.shared.frame_source.launch_preparation import build_launch_preparation_cache_key


def _build_scoped_source() -> EventScopedFrameSource:
    frames = [np.full((8, 8), fill_value=idx, dtype=np.float32) for idx in range(10)]
    source = EagerFrameSource(
        raw_frames=frames,
        subtracted_frames=frames,
        visual_frames=[np.asarray(frame, dtype=np.uint8) for frame in frames],
        frame_names=[f"f{idx}.tif" for idx in range(10)],
        source_paths=["/tmp/stack"] * 10,
    )
    return EventScopedFrameSource(source, 2, 6)


def _build_host_context(*, baseline_pre_frames: int = 2, smoothing: bool = True) -> dict:
    return {
        "event": {
            "event_id": "event_0042",
            "start_idx": 3,
            "end_idx": 6,
            "flags": {
                "analysis_scope_start_idx": 2,
                "analysis_scope_end_idx": 6,
                "analysis_local_event_start_idx": 1,
                "analysis_local_event_end_idx": 4,
                "baseline_pre_frames": baseline_pre_frames,
                "analysis_processing": {
                    "horizontal_bar_denoise": False,
                    "smoothing": smoothing,
                    "baseline_subtraction": True,
                    "global_normalization": True,
                    "stabilization": False,
                },
            },
        }
    }


def _build_host_context_with_stabilization(*, stabilization: bool) -> dict:
    context = _build_host_context()
    context["event"]["flags"]["analysis_processing"]["stabilization"] = bool(stabilization)
    return context


def _build_app(host_context: dict, launch_preparation: dict | None) -> tuple[SimpleNamespace, list[int], list[list[int]]]:
    scheduled: list[int] = []
    prewarm_windows: list[list[int]] = []
    workspace_bound: list[object] = []
    workspace = SimpleNamespace(
        _host_context=host_context,
        bind_frame_source=lambda frame_source: workspace_bound.append(frame_source),
    )
    app = SimpleNamespace(
        _host_mode=True,
        _host_processing_options={
            "apply_horizontal_bar_denoise": False,
            "apply_smoothing": True,
            "apply_baseline_subtraction": True,
            "apply_global_normalization": True,
            "apply_stabilization": False,
        },
        _host_launch_preparation=launch_preparation,
        _host_buffer_cache_key=None,
        _schedule_analysis_prewarm=lambda idx: scheduled.append(int(idx)),
        analysis_workspace=workspace,
        app_context=None,
        frame_names=[],
        _current_image_source_paths=[],
        log_debug=lambda *_args: None,
        log_info=lambda *_args: None,
    )
    return app, scheduled, prewarm_windows


def test_prepare_host_mode_buffers_reuses_compatible_launch_preparation() -> None:
    scoped_source = _build_scoped_source()
    prepared_source = PreparedFrameSource(scoped_source, baseline_frames=2)
    prepared_source.prepare()
    prewarm_calls: list[list[int]] = []
    prepared_source.prewarm = lambda indices, generation=None: prewarm_calls.append(list(indices))  # type: ignore[method-assign]
    launch_preparation = {
        "cache_key": build_launch_preparation_cache_key(
            event_id="event_0042",
            scope_start=2,
            scope_end=6,
            baseline_pre_frames=2,
            apply_horizontal_bar_denoise=False,
            apply_smoothing=True,
            apply_baseline_subtraction=True,
            apply_global_normalization=True,
            apply_stabilization=False,
        ),
        "prepared_source": prepared_source,
        "stats": prepared_source.stats(),
        "preview_frame_u8": prepared_source.get_visual_frame(1),
    }
    app, scheduled, _prewarm_windows = _build_app(_build_host_context(), launch_preparation)
    controller = AnalysisHostModeController(app)

    ready = controller.prepare_host_mode_buffers(scoped_source)

    assert ready is True
    assert app.frame_source is prepared_source
    assert scheduled == [1]
    assert prewarm_calls == [[0, 1, 2, 3]]


def test_prepare_host_mode_buffers_rebuilds_when_processing_flags_change() -> None:
    scoped_source = _build_scoped_source()
    prepared_source = PreparedFrameSource(scoped_source, baseline_frames=2)
    prepared_source.prepare()
    candidate_prewarm_calls: list[list[int]] = []
    prepared_source.prewarm = lambda indices, generation=None: candidate_prewarm_calls.append(list(indices))  # type: ignore[method-assign]
    launch_preparation = {
        "cache_key": build_launch_preparation_cache_key(
            event_id="event_0042",
            scope_start=2,
            scope_end=6,
            baseline_pre_frames=2,
            apply_horizontal_bar_denoise=False,
            apply_smoothing=False,
            apply_baseline_subtraction=True,
            apply_global_normalization=True,
            apply_stabilization=False,
        ),
        "prepared_source": prepared_source,
        "stats": prepared_source.stats(),
    }
    app, scheduled, _prewarm_windows = _build_app(_build_host_context(), launch_preparation)
    controller = AnalysisHostModeController(app)

    ready = controller.prepare_host_mode_buffers(scoped_source)

    assert ready is True
    assert app.frame_source is not prepared_source
    assert isinstance(app.frame_source, PreparedFrameSource)
    assert scheduled == [1]
    assert candidate_prewarm_calls == []


def test_prepare_host_mode_buffers_rebuilds_when_baseline_count_changes() -> None:
    scoped_source = _build_scoped_source()
    prepared_source = PreparedFrameSource(scoped_source, baseline_frames=2)
    prepared_source.prepare()
    candidate_prewarm_calls: list[list[int]] = []
    prepared_source.prewarm = lambda indices, generation=None: candidate_prewarm_calls.append(list(indices))  # type: ignore[method-assign]
    launch_preparation = {
        "cache_key": build_launch_preparation_cache_key(
            event_id="event_0042",
            scope_start=2,
            scope_end=6,
            baseline_pre_frames=2,
            apply_horizontal_bar_denoise=False,
            apply_smoothing=True,
            apply_baseline_subtraction=True,
            apply_global_normalization=True,
            apply_stabilization=False,
        ),
        "prepared_source": prepared_source,
        "stats": prepared_source.stats(),
    }
    app, scheduled, _prewarm_windows = _build_app(_build_host_context(baseline_pre_frames=3), launch_preparation)
    controller = AnalysisHostModeController(app)

    ready = controller.prepare_host_mode_buffers(scoped_source)

    assert ready is True
    assert app.frame_source is not prepared_source
    assert isinstance(app.frame_source, PreparedFrameSource)
    assert scheduled == [1]
    assert candidate_prewarm_calls == []


def test_prepare_host_mode_buffers_rebuilds_when_stabilization_flag_changes() -> None:
    scoped_source = _build_scoped_source()
    prepared_source = PreparedFrameSource(scoped_source, baseline_frames=2, apply_stabilization=False)
    prepared_source.prepare()
    candidate_prewarm_calls: list[list[int]] = []
    prepared_source.prewarm = lambda indices, generation=None: candidate_prewarm_calls.append(list(indices))  # type: ignore[method-assign]
    launch_preparation = {
        "cache_key": build_launch_preparation_cache_key(
            event_id="event_0042",
            scope_start=2,
            scope_end=6,
            baseline_pre_frames=2,
            apply_horizontal_bar_denoise=False,
            apply_smoothing=True,
            apply_baseline_subtraction=True,
            apply_global_normalization=True,
            apply_stabilization=False,
        ),
        "prepared_source": prepared_source,
        "stats": prepared_source.stats(),
    }
    app, scheduled, _prewarm_windows = _build_app(_build_host_context_with_stabilization(stabilization=True), launch_preparation)
    app._host_processing_options["apply_stabilization"] = True
    controller = AnalysisHostModeController(app)

    ready = controller.prepare_host_mode_buffers(scoped_source)

    assert ready is True
    assert app.frame_source is not prepared_source
    assert isinstance(app.frame_source, PreparedFrameSource)
    assert scheduled == [1]
    assert candidate_prewarm_calls == []
