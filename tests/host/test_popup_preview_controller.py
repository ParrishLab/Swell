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


class _Label:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height


def _resize_app(label: _Label, popup: _Popup, rendered_size, updates: list[int]) -> SimpleNamespace:
    return SimpleNamespace(
        _popup=SimpleNamespace(
            mark_popup=popup,
            mark_preview_label=label,
            mark_popup_current_idx=7,
            mark_preview_rendered_size=rendered_size,
            mark_preview_resize_after_id=None,
        ),
        _get_preview_controller=lambda: SimpleNamespace(popup_update_preview=lambda idx: updates.append(int(idx))),
    )


def test_preview_resize_schedules_rerender_when_label_size_changed() -> None:
    popup = _Popup()
    updates: list[int] = []
    app = _resize_app(_Label(900, 420), popup, (900, 700), updates)
    controller = PopupPreviewController(app)

    controller.on_preview_resize()

    assert [delay for delay, _cb in popup.after_calls] == [120]
    assert updates == []

    popup.after_calls[0][1]()

    assert updates == [7]
    assert app._popup.mark_preview_resize_after_id is None


def test_preview_resize_ignored_when_label_size_matches_render() -> None:
    popup = _Popup()
    updates: list[int] = []
    app = _resize_app(_Label(900, 420), popup, (900, 420), updates)
    controller = PopupPreviewController(app)

    controller.on_preview_resize()

    assert popup.after_calls == []
    assert updates == []


def test_preview_resize_cancels_previous_pending_rerender() -> None:
    popup = _Popup()
    updates: list[int] = []
    app = _resize_app(_Label(900, 420), popup, (900, 700), updates)
    controller = PopupPreviewController(app)

    controller.on_preview_resize()
    controller.on_preview_resize()

    assert popup.cancelled == ["after-1"]
    assert app._popup.mark_preview_resize_after_id == "after-2"
