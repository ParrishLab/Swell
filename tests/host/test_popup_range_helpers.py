from __future__ import annotations

from types import SimpleNamespace

from swell.host.event_gui import SwellHostApp
from swell.host.mark_popup_controller import MarkPopupController


class _Canvas:
    def winfo_width(self):
        return 212


class _Scale:
    def __init__(self):
        self.configured = {}
        self.value = None

    def configure(self, **kwargs):
        self.configured.update(kwargs)

    def set(self, value):
        self.value = int(value)


def test_popup_range_idx_to_x_uses_imported_linear_helper() -> None:
    app = SwellHostApp.__new__(SwellHostApp)
    app.stack_info = type("StackInfo", (), {"frame_count": 200})()
    app._popup = type("PopupManager", (), {"mark_range_canvas": _Canvas()})()
    controller = MarkPopupController(app)

    x = controller.range_idx_to_x(50)

    assert isinstance(x, float)
    assert x > 6.0


def test_apply_popup_range_bounds_keeps_event_markers_visible() -> None:
    app = SwellHostApp.__new__(SwellHostApp)
    app.stack_info = type("StackInfo", (), {"frame_count": 300})()
    scale = _Scale()
    app._popup = SimpleNamespace(
        mark_scale=scale,
        mark_popup_current_idx=150,
        mark_processed_cache={},
    )
    controller = MarkPopupController(app)
    app._popup_get_normalized_mark_bounds_for_overlay = lambda: (120, 180)
    controller.update_window_info = lambda: None  # type: ignore[method-assign]
    controller.redraw_overlay = lambda: None  # type: ignore[method-assign]
    controller.redraw_range_selector = lambda: None  # type: ignore[method-assign]
    controller.update_preview = lambda _idx: None  # type: ignore[method-assign]

    controller.apply_range_bounds(140, 170)

    assert app._popup.mark_popup_local_start == 120
    assert app._popup.mark_popup_local_end == 180
    assert app._popup.mark_range_start_idx == 120
    assert app._popup.mark_range_end_idx == 180
    assert scale.configured["from_"] == 120
    assert scale.configured["to"] == 180
