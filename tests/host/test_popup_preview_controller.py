from __future__ import annotations

from types import SimpleNamespace

from swell.host.popup_preview_controller import PopupPreviewController


class _Scale:
    def __init__(self) -> None:
        self.value = None

    def set(self, value: int) -> None:
        self.value = int(value)


class _Var:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: object) -> None:
        self.value = str(value)


class _Popup:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []
        self.cancelled: list[object] = []

    def winfo_exists(self) -> bool:
        return True

    def after(self, delay_ms: int, callback):
        self.after_calls.append((int(delay_ms), callback))
        return f"after-{len(self.after_calls)}"

    def after_cancel(self, token) -> None:
        self.cancelled.append(token)


def test_step_clamps_to_overlay_bounds_and_updates_preview() -> None:
    updates: list[int] = []
    scale = _Scale()
    app = SimpleNamespace(
        stack_info=SimpleNamespace(frame_count=100),
        _popup=SimpleNamespace(mark_scale=scale, mark_popup_current_idx=9),
        _popup_overlay_bounds=lambda: (0, 10),
        _get_preview_controller=lambda: SimpleNamespace(popup_update_preview=lambda idx: updates.append(int(idx))),
    )
    controller = PopupPreviewController(app)

    controller.step(5)

    assert scale.value == 10
    assert updates == [10]


def test_set_start_current_aligns_end_and_schedules_recompute() -> None:
    recompute_calls: list[dict[str, object]] = []
    overlays: list[bool] = []
    app = SimpleNamespace(
        _popup=SimpleNamespace(
            mark_popup_current_idx=12,
            mark_start_var=_Var("5"),
            mark_end_var=_Var("8"),
        ),
        _get_preview_controller=lambda: SimpleNamespace(redraw_popup_overlay=lambda: overlays.append(True)),
    )
    processing = SimpleNamespace(schedule_recompute=lambda **kwargs: recompute_calls.append(dict(kwargs)))
    controller = PopupPreviewController(app, processing_controller=processing)

    controller.set_start_current()

    assert app._popup.mark_start_var.get() == "13"
    assert app._popup.mark_end_var.get() == "13"
    assert overlays == [True]
    assert recompute_calls == [{"align_baseline_to_start": True}]


def test_contrast_change_snaps_near_default_and_updates_preview() -> None:
    updates: list[int] = []
    app = SimpleNamespace(
        _popup=SimpleNamespace(
            mark_popup_current_idx=4,
            mark_contrast_var=_Var("1.02"),
            mark_contrast_label_var=_Var(""),
        ),
        _get_preview_controller=lambda: SimpleNamespace(popup_update_preview=lambda idx: updates.append(int(idx))),
    )
    controller = PopupPreviewController(app)

    controller.on_contrast_change("1.02")

    assert app._popup.mark_contrast_var.get() == "1.0"
    assert app._popup.mark_contrast_label_var.get() == "Contrast: 1.00x"
    assert updates == [4]
