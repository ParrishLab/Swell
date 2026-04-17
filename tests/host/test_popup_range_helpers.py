from __future__ import annotations

from sdapp.host.sd_gui import SDAnalyzerApp


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
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.stack_info = type("StackInfo", (), {"frame_count": 200})()
    app._popup = type("PopupManager", (), {"mark_range_canvas": _Canvas()})()

    x = app._popup_range_idx_to_x(50)

    assert isinstance(x, float)
    assert x > 6.0


def test_apply_popup_range_bounds_keeps_event_markers_visible() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.stack_info = type("StackInfo", (), {"frame_count": 300})()
    scale = _Scale()
    from types import SimpleNamespace
    app._popup = SimpleNamespace(
        mark_scale=scale,
        mark_popup_current_idx=150,
        mark_processed_cache={},
    )
    app._popup_get_normalized_mark_bounds_for_overlay = lambda: (120, 180)
    app._popup_update_window_info = lambda: None
    app._redraw_popup_overlay = lambda: None
    app._redraw_popup_range_selector = lambda: None
    app._popup_update_preview = lambda _idx: None

    app._apply_popup_range_bounds(140, 170)

    assert app._popup.mark_popup_local_start == 120
    assert app._popup.mark_popup_local_end == 180
    assert app._popup.mark_range_start_idx == 120
    assert app._popup.mark_range_end_idx == 180
    assert scale.configured["from_"] == 120
    assert scale.configured["to"] == 180
