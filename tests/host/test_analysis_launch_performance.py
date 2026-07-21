from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

import numpy as np

from swell.analysis.core.frame_source import EagerFrameSource
from swell.host.controllers.analysis_launch_controller import AnalysisLaunchController
from swell.shared.frame_source import PreparedFrameSource
from swell.shared.frame_source.launch_preparation import build_launch_preparation_cache_key


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
        _get_project_controller=lambda: SimpleNamespace(ensure_active_stack_available=lambda **kwargs: True),
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
        local_event_start_idx=2,
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


def test_launch_preview_uses_only_available_pre_event_baseline_frames() -> None:
    frames = [
        np.zeros((8, 8), dtype=np.float32),
        np.zeros((8, 8), dtype=np.float32),
        np.full((8, 8), 100.0, dtype=np.float32),
        np.full((8, 8), 100.0, dtype=np.float32),
    ]
    source = EagerFrameSource(
        raw_frames=frames,
        subtracted_frames=frames,
        visual_frames=[np.asarray(frame, dtype=np.uint8) for frame in frames],
        frame_names=[f"f{idx}.tif" for idx in range(4)],
        source_paths=["/tmp/stack"] * 4,
    )
    controller = AnalysisLaunchController(_build_app(source))

    payload = controller._prepare_analysis_launch_preview(
        event_id="event_early",
        event_start=2,
        event_end=3,
        baseline_pre_frames=30,
        apply_horizontal_bar_denoise=False,
        apply_smoothing=False,
        apply_baseline_subtraction=True,
        apply_global_normalization=False,
        apply_stabilization=False,
    )

    preparation = payload["launch_preparation"]
    assert preparation["effective_baseline_frames"] == 2
    assert preparation["stats"].baseline_frames == 2
    assert float(np.max(np.abs(preparation["stats"].baseline))) == 0.0


def test_launch_cache_key_distinguishes_event_start_with_same_clamped_scope() -> None:
    controller = AnalysisLaunchController(_build_app(_build_frame_source()))

    key_a = controller._launch_preparation_cache_key(
        event_id="event_0042",
        event_start=1,
        event_end=5,
        baseline_pre_frames=30,
        apply_horizontal_bar_denoise=False,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        apply_stabilization=False,
    )
    key_b = controller._launch_preparation_cache_key(
        event_id="event_0042",
        event_start=2,
        event_end=5,
        baseline_pre_frames=30,
        apply_horizontal_bar_denoise=False,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        apply_stabilization=False,
    )

    assert key_a != key_b


def test_persist_analysis_settings_returns_post_remap_context() -> None:
    state = {
        "context": {
            "event": {"event_id": "event_0042", "flags": {"analysis_scope_start_idx": 2}},
            "analysis_state": {"masks_committed": np.zeros((4, 8, 8), dtype=np.uint8)},
        }
    }

    def _update_event(*_args, **_kwargs):
        state["context"] = {
            "event": {"event_id": "event_0042", "flags": {"analysis_scope_start_idx": 0}},
            "analysis_state": {"masks_committed": np.zeros((6, 8, 8), dtype=np.uint8)},
        }

    browser = SimpleNamespace(
        update_event=_update_event,
        host_context_for_event=lambda _event_id: dict(state["context"]),
    )
    app = SimpleNamespace(browser_controller=browser, stack_info=SimpleNamespace(frame_count=6))
    controller = AnalysisLaunchController(app)
    model_setup = SimpleNamespace(build_host_model_context=lambda: {"checkpoint": "model"})

    context = controller._persist_analysis_settings_and_refresh_context(
        "event_0042",
        {"analysis_scope_start_idx": 0},
        model_setup,
    )

    assert np.asarray(context["analysis_state"]["masks_committed"]).shape[0] == 6
    assert context["event"]["flags"]["analysis_scope_start_idx"] == 0
    assert context["model_context"] == {"checkpoint": "model"}


def test_stabilization_geometry_detection_includes_prompts_and_draft_masks() -> None:
    assert AnalysisLaunchController._analysis_payload_has_geometry(
        {"prompts": {"frames": {"0": {"points": [{"x": 1, "y": 2, "label": 1}]}}}}
    )
    assert AnalysisLaunchController._analysis_payload_has_geometry(
        {"masks_draft": np.ones((1, 4, 4), dtype=np.uint8)}
    )
    assert not AnalysisLaunchController._analysis_payload_has_geometry(
        {"masks_committed": np.zeros((1, 4, 4), dtype=np.uint8)}
    )
    assert AnalysisLaunchController._analysis_payload_has_geometry(
        {"metrics_settings": {"roi_points": [[1, 1], [2, 1], [2, 2]]}}
    )
    assert AnalysisLaunchController._analysis_payload_has_geometry(
        {"analysis_state": {}, "metrics_settings": {"roi_mask": np.ones((4, 4), dtype=bool)}}
    )


def test_stabilization_cleanup_removes_local_and_global_roi_geometry() -> None:
    replaced: list[tuple[str, dict | None]] = []
    global_updates: list[dict] = []
    browser = SimpleNamespace(
        session=SimpleNamespace(
            replace_analysis_sidecar=lambda event_id, payload: replaced.append((str(event_id), payload))
        ),
        get_global_metrics_defaults=lambda: {
            "frames_per_sec": 2.0,
            "roi_points": [[1, 1], [2, 1], [2, 2]],
            "roi_mask": np.ones((4, 4), dtype=bool),
        },
        set_global_metrics_defaults=lambda payload: global_updates.append(dict(payload)),
    )
    controller = AnalysisLaunchController(SimpleNamespace(browser_controller=browser))

    controller._clear_incompatible_analysis_geometry(
        "event_1",
        {
            "masks_committed": np.ones((1, 4, 4), dtype=bool),
            "metrics_settings": {
                "frames_per_sec": 3.0,
                "roi_polygons": [[[1, 1], [2, 1], [2, 2]]],
            },
        },
    )

    assert replaced == [("event_1", {"metrics_settings": {"frames_per_sec": 3.0}})]
    assert global_updates == [{"frames_per_sec": 2.0}]


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


def test_focus_existing_analysis_window_status_uses_event_label() -> None:
    statuses: list[str] = []
    app = SimpleNamespace(
        browser_controller=SimpleNamespace(
            get_event=lambda event_id: SimpleNamespace(event_id=str(event_id), label="Visible Event"),
            event_display_name=lambda _event_id: "Visible Event",
        ),
        _get_project_controller=lambda: SimpleNamespace(ensure_active_stack_available=lambda **kwargs: True),
        analysis_window_manager=SimpleNamespace(focus_event_window=lambda _scope, _event_id: True),
        reader=object(),
        stack_info=SimpleNamespace(frame_count=3),
        root=object(),
        _active_event_id=lambda: "event_0042",
        _get_model_setup_controller=lambda: SimpleNamespace(is_analysis_allowed=lambda: (True, "")),
        _set_status=lambda message: statuses.append(str(message)),
        _show_warning=lambda *_args, **_kwargs: None,
    )
    controller = AnalysisLaunchController(app)

    controller.analyze_selected_event()

    assert statuses == ["Focused analysis workspace for Visible Event."]
