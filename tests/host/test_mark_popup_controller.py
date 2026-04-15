from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sdapp.host.host_models import EventMeta
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


def test_begin_popup_session_for_mark_new_uses_current_frame_normalization() -> None:
    recompute_calls: list[dict[str, object]] = []
    app = SimpleNamespace(
        _mark_popup_local_start=12,
        _mark_popup_local_end=18,
        _mark_popup_current_idx=15,
        _apply_popup_range_bounds=lambda _start, _end: None,
        _recompute_popup_pipeline_for_bounds=lambda start, end, **kwargs: recompute_calls.append(
            {"start": int(start), "end": int(end), **dict(kwargs)}
        ),
        _log_warn=lambda _message: None,
    )
    controller = MarkPopupController(app)

    controller._begin_popup_session(12, 18, normalize_to_current_frame=True)

    assert len(recompute_calls) == 1
    call = recompute_calls[0]
    assert call["start"] == 12
    assert call["end"] == 18
    assert call["normalization_range_start"] == 15
    assert call["normalization_range_end"] == 15


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


def test_resolve_initial_baseline_state_prefers_existing_event_flags_for_edit() -> None:
    controller = MarkPopupController(SimpleNamespace(baseline_pre_frames=30))

    baseline_count, baseline_end = controller._resolve_initial_baseline_state(
        mode="edit",
        event=SimpleNamespace(flags={"baseline_pre_frames": 9}),
        start_default=42,
    )

    assert baseline_count == 9
    assert baseline_end == 41


def test_confirm_new_event_persists_baseline_scope_flags() -> None:
    created: list[dict[str, object]] = []
    app = SimpleNamespace(
        stack_info=SimpleNamespace(frame_count=100),
        _mark_popup_mode="new",
        _mark_popup_event_id=None,
        _mark_start_var=SimpleNamespace(get=lambda: "12"),
        _mark_end_var=SimpleNamespace(get=lambda: "18"),
        _mark_popup_current_idx=12,
        _parse_frame_index=lambda value, _default, _name: int(value),
        _normalize_bounds=lambda start, end: (int(start), int(end), False, False),
        _duration_sec=lambda _duration_frames: None,
        _popup_parse_baseline_controls=lambda: (5, 11),
        browser_controller=SimpleNamespace(
            create_event=lambda **kwargs: created.append(dict(kwargs)) or EventMeta("event_0001", "event_0001", start_idx=12, end_idx=18, flags=dict(kwargs.get("flags", {})))
        ),
        _sync_event_projections=lambda: None,
        tree=SimpleNamespace(selection_set=lambda _event_id: None),
        _set_active_event_id=lambda _event_id: None,
        _set_status=lambda _message: None,
        _log_info=lambda _message: None,
        preview_scale=SimpleNamespace(set=lambda _value: None),
        _update_preview=lambda _idx: None,
    )
    controller = MarkPopupController(app)
    controller.cancel = lambda: None  # type: ignore[method-assign]

    controller.confirm()

    assert len(created) == 1
    flags = dict(created[0]["flags"])
    assert int(flags["baseline_pre_frames"]) == 5
    assert int(flags["analysis_scope_start_idx"]) == 7
    assert int(flags["analysis_scope_end_idx"]) == 18
    assert int(flags["analysis_local_event_start_idx"]) == 5
    assert int(flags["analysis_local_event_end_idx"]) == 11


def test_confirm_edit_event_updates_baseline_scope_flags_and_preserves_existing_flags() -> None:
    updated: list[dict[str, object]] = []
    existing = EventMeta(
        "event_0002",
        "event_0002",
        start_idx=20,
        end_idx=28,
        flags={"keep": True, "baseline_pre_frames": 2},
    )
    app = SimpleNamespace(
        stack_info=SimpleNamespace(frame_count=100),
        _mark_popup_mode="edit",
        _mark_popup_event_id="event_0002",
        _mark_start_var=SimpleNamespace(get=lambda: "22"),
        _mark_end_var=SimpleNamespace(get=lambda: "27"),
        _mark_popup_current_idx=22,
        _parse_frame_index=lambda value, _default, _name: int(value),
        _normalize_bounds=lambda start, end: (int(start), int(end), False, False),
        _duration_sec=lambda _duration_frames: None,
        _popup_parse_baseline_controls=lambda: (4, 21),
        _get_event_by_id=lambda _event_id: existing,
        browser_controller=SimpleNamespace(
            update_event=lambda event_id, **kwargs: updated.append({"event_id": event_id, **kwargs}) or EventMeta(event_id, existing.label, start_idx=22, end_idx=27, flags=dict(kwargs.get("flags", {})))
        ),
        _sync_event_projections=lambda: None,
        tree=SimpleNamespace(selection_set=lambda _event_id: None),
        _set_active_event_id=lambda _event_id: None,
        _set_status=lambda _message: None,
        _log_info=lambda _message: None,
        preview_scale=SimpleNamespace(set=lambda _value: None),
        _update_preview=lambda _idx: None,
    )
    controller = MarkPopupController(app)
    controller.cancel = lambda: None  # type: ignore[method-assign]

    controller.confirm()

    assert len(updated) == 1
    flags = dict(updated[0]["flags"])
    assert flags["keep"] is True
    assert int(flags["baseline_pre_frames"]) == 4
    assert int(flags["analysis_scope_start_idx"]) == 18
    assert int(flags["analysis_scope_end_idx"]) == 27
    assert int(flags["analysis_local_event_start_idx"]) == 4
    assert int(flags["analysis_local_event_end_idx"]) == 9


def test_delete_selected_events_requires_confirmation() -> None:
    deleted_ids: list[list[str]] = []
    infos: list[str] = []
    app = SimpleNamespace(
        root=object(),
        tree=SimpleNamespace(selection=lambda: ["event_0001", "event_0002"]),
        browser_controller=SimpleNamespace(
            get_event=lambda event_id: SimpleNamespace(label=f"Label for {event_id}"),
            delete_events=lambda ids: deleted_ids.append(list(ids)) or len(ids),
        ),
        _sync_event_projections=lambda: None,
        _active_event_id=lambda: None,
        _set_active_event_id=lambda _event_id: None,
        _set_status=lambda _message: None,
        _log_info=lambda message: infos.append(str(message)),
        _log_warn=lambda _message: None,
    )
    controller = MarkPopupController(app)

    with patch("sdapp.host.mark_popup_controller.messagebox.askyesno", return_value=False):
        controller.delete_selected_events()

    assert deleted_ids == []
    assert infos[-1] == "Delete canceled."


def test_delete_selected_events_deletes_after_confirmation() -> None:
    deleted_ids: list[list[str]] = []
    synced: list[bool] = []
    active: list[object] = []
    status: list[str] = []
    infos: list[str] = []
    app = SimpleNamespace(
        root=object(),
        tree=SimpleNamespace(selection=lambda: ["event_0001"]),
        browser_controller=SimpleNamespace(
            get_event=lambda _event_id: SimpleNamespace(label="Halo(Light Off) 1"),
            delete_events=lambda ids: deleted_ids.append(list(ids)) or len(ids),
        ),
        _sync_event_projections=lambda: synced.append(True),
        _active_event_id=lambda: "event_0001",
        _set_active_event_id=lambda event_id: active.append(event_id),
        _set_status=lambda message: status.append(str(message)),
        _log_info=lambda message: infos.append(str(message)),
        _log_warn=lambda _message: None,
    )
    controller = MarkPopupController(app)

    with patch("sdapp.host.mark_popup_controller.messagebox.askyesno", return_value=True):
        controller.delete_selected_events()

    assert deleted_ids == [["event_0001"]]
    assert synced == [True]
    assert active == [None]
    assert status[-1] == "Deleted 1 event(s)."
    assert infos[-1] == "Deleted 1 event(s)."
