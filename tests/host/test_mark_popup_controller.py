from __future__ import annotations

from types import SimpleNamespace

from sdapp.host.mark_popup_controller import MarkPopupController


def test_resolve_initial_popup_state_uses_center_window_for_edit_range() -> None:
    controller = MarkPopupController(SimpleNamespace())

    center_idx, start_default, end_default, range_start, range_end = controller._resolve_initial_popup_state(
        mode="edit",
        event=SimpleNamespace(start_idx=42, end_idx=57),
        frame_count=200,
        current_frame_idx=80,
    )

    assert center_idx == 49
    assert start_default == 42
    assert end_default == 57
    assert range_start == 0
    assert range_end == 149


def test_begin_popup_session_applies_bounds_and_starts_processing() -> None:
    calls: list[tuple[str, int, int]] = []
    warnings: list[str] = []
    app = SimpleNamespace(
        _mark_popup_local_start=12,
        _mark_popup_local_end=18,
        _apply_popup_range_bounds=lambda start, end: calls.append(("apply", int(start), int(end))),
        _recompute_popup_pipeline_for_bounds=lambda start, end, **_kwargs: calls.append(("recompute", int(start), int(end))),
        _log_warn=lambda message: warnings.append(str(message)),
    )
    controller = MarkPopupController(app)

    controller._begin_popup_session(12, 18)

    assert calls == [("apply", 12, 18), ("recompute", 12, 18)]
    assert warnings == []


def test_edit_popup_baseline_end_should_track_event_start_not_center() -> None:
    event = SimpleNamespace(start_idx=642, end_idx=702)
    controller = MarkPopupController(SimpleNamespace())

    center_idx, start_default, end_default, range_start, range_end = controller._resolve_initial_popup_state(
        mode="edit",
        event=event,
        frame_count=3049,
        current_frame_idx=678,
    )

    assert center_idx == 672
    assert start_default == 642
    assert end_default == 702
    assert range_start == 572
    assert range_end == 772
    assert max(0, start_default - 1) == 641
