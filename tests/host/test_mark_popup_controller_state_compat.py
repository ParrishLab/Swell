from __future__ import annotations

from types import SimpleNamespace

from swell.host.mark_popup_controller import MarkPopupController


def test_on_destroy_resets_popup_pending_state_on_popup_manager() -> None:
    canceled: list[str] = []
    gc_calls: list[dict] = []
    popup_ref = SimpleNamespace(winfo_exists=lambda: False, after_cancel=lambda token: canceled.append(str(token)))
    popup_state = SimpleNamespace(
        mark_popup=popup_ref,
        engine=SimpleNamespace(cancel_active=lambda: canceled.append("engine")),
        popup_active_job_id=7,
        mark_recompute_after_id="recompute-token",
        pending_popup_after_id="preview-token",
        pending_popup_frame_idx=19,
        mark_popup_mode="new",
        mark_popup_event_id="sd_event_001",
        mark_popup_anchor_idx=4,
        mark_popup_image=object(),
        mark_popup_mini_image=object(),
        mark_start_var=object(),
        mark_end_var=object(),
        mark_baseline_count_var=object(),
        mark_baseline_end_var=object(),
        mark_contrast_var=object(),
        mark_contrast_label_var=object(),
        mark_frame_info_var=object(),
        mark_window_info_var=object(),
        mark_loading_var=object(),
        mark_loading_label=object(),
        mark_loading_bar=object(),
        mark_scale=object(),
        mark_preview_label=object(),
        mark_overlay=object(),
        mark_range_canvas=object(),
        mark_range_active_handle="start",
        mark_range_start_idx=2,
        mark_range_end_idx=6,
        mark_last_full_refresh_note="note",
        mark_recompute_show_errors=True,
        mark_main_view_shell=object(),
        mark_mini_frame=object(),
        mark_mini_canvas=object(),
        mark_mini_grip=object(),
        mark_resize_start_x=1,
        mark_resize_start_y=2,
        mark_resize_start_w=3,
        mark_resize_start_h=4,
        mark_baseline_frame=object(),
        mark_norm_p1=0.2,
        mark_norm_p99=0.8,
        mark_processed_cache=SimpleNamespace(clear=lambda: canceled.append("mark-cache")),
    )
    app = SimpleNamespace(
        _popup=popup_state,
        _normalized_frame_u8_cache=SimpleNamespace(clear=lambda: canceled.append("norm-cache")),
        _gc_runtime_caches=lambda **kwargs: gc_calls.append(dict(kwargs)),
    )
    controller = MarkPopupController(app)

    controller.on_destroy()

    assert popup_state.popup_active_job_id == 0
    assert popup_state.pending_popup_after_id is None
    assert popup_state.pending_popup_frame_idx is None
    assert popup_state.mark_recompute_after_id is None
    assert "engine" in canceled
    assert "recompute-token" in canceled
    assert "preview-token" in canceled
    assert gc_calls and gc_calls[-1] == {"aggressive": False, "run_python_gc": True}

