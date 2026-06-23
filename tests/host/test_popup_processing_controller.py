from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from swell.host.popup_processing_controller import PopupProcessingController


class _Var:
    def __init__(self, value: str):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: object) -> None:
        self.value = str(value)


class _Popup:
    def __init__(self) -> None:
        self.exists = True
        self.after_calls: list[tuple[int, object]] = []
        self.cancelled: list[object] = []

    def winfo_exists(self) -> bool:
        return self.exists

    def after(self, delay_ms: int, callback):
        self.after_calls.append((delay_ms, callback))
        return f"after-{len(self.after_calls)}"

    def after_cancel(self, token) -> None:
        self.cancelled.append(token)


class _PromotingDict(dict):
    def promote(self, key):
        return self[key]


def test_parse_baseline_controls_clamps_end_to_frame_range() -> None:
    app = SimpleNamespace(
        stack_info=SimpleNamespace(frame_count=20),
        _popup=SimpleNamespace(
            mark_baseline_count_var=_Var("5"),
            mark_baseline_end_var=_Var("99"),
        ),
    )
    controller = PopupProcessingController(app, SimpleNamespace())

    assert controller.parse_baseline_controls() == (5, 19)


def test_schedule_recompute_replaces_pending_after_and_tracks_show_errors() -> None:
    popup = _Popup()
    owner = SimpleNamespace(redraw_overlay=lambda: None)
    app = SimpleNamespace(
        stack_info=SimpleNamespace(frame_count=30),
        _popup=SimpleNamespace(
            mark_popup=popup,
            mark_recompute_after_id="old-token",
            mark_recompute_show_errors=False,
            mark_start_var=_Var("10"),
            mark_baseline_count_var=_Var("5"),
            mark_baseline_end_var=_Var("9"),
        ),
    )
    controller = PopupProcessingController(app, owner)

    controller.schedule_recompute(show_errors=True, delay_ms=50)

    assert popup.cancelled == ["old-token"]
    assert popup.after_calls[0][0] == 1000
    assert app._popup.mark_recompute_after_id == "after-1"
    assert app._popup.mark_recompute_show_errors is True


def test_get_processed_frame_uses_raw_normalization_before_baseline_and_cache_after() -> None:
    raw = np.full((2, 2), 7, dtype=np.uint8)
    normalized = np.full((2, 2), 11, dtype=np.uint8)
    processed = np.full((2, 2), 23, dtype=np.uint8)
    engine_calls: list[int] = []
    app = SimpleNamespace(
        reader=SimpleNamespace(read_frame=lambda frame_idx, use_cache=True: raw),
        _normalize_frame_percentile=lambda frame: normalized,
        _popup=SimpleNamespace(
            mark_baseline_frame=None,
            mark_processed_cache=_PromotingDict(),
            mark_norm_p1=1.0,
            mark_norm_p99=99.0,
            engine=SimpleNamespace(
                get_processed_frame=lambda frame_idx, _baseline, _p1, _p99: engine_calls.append(frame_idx) or processed
            ),
        ),
    )
    controller = PopupProcessingController(app, SimpleNamespace())

    assert controller.get_processed_frame(4) is normalized

    app._popup.mark_baseline_frame = np.zeros((2, 2), dtype=np.float32)
    first = controller.get_processed_frame(4)
    second = controller.get_processed_frame(4)

    assert first is processed
    assert second is processed
    assert engine_calls == [4]
