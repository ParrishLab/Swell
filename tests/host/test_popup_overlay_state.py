from __future__ import annotations

from types import SimpleNamespace

from swell.host.preview_controller import HostPreviewController
from swell.shared.ui.theme import APP_COLORS


def test_popup_overlay_draws_baseline_before_event_span() -> None:
    recorded = {}
    controller = HostPreviewController.__new__(HostPreviewController)
    controller.app = SimpleNamespace(
        _popup=SimpleNamespace(
            mark_overlay=object(),
            mark_scale=object(),
            mark_popup_current_idx=50,
        ),
        stack_info=SimpleNamespace(frame_count=200),
        _get_popup_controller=lambda: SimpleNamespace(
            processing_controller=SimpleNamespace(parse_baseline_controls=lambda: (5, 22))
        ),
    )
    controller.popup_overlay_bounds = lambda: (0, 149)
    controller.popup_get_normalized_mark_bounds_for_overlay = lambda: (42, 57)

    def _draw(_canvas, _scale, start_idx, end_idx, spans, markers):
        recorded["start_idx"] = start_idx
        recorded["end_idx"] = end_idx
        recorded["spans"] = list(spans)
        recorded["markers"] = list(markers)

    controller.draw_overlay_bar = _draw

    controller.redraw_popup_overlay()

    assert recorded["start_idx"] == 0
    assert recorded["end_idx"] == 149
    assert recorded["spans"] == [(18, 22, APP_COLORS["accent_soft"]), (42, 57, APP_COLORS["cyan"])]
    assert recorded["markers"][0] == (50, APP_COLORS["white"])
    assert recorded["markers"][1:] == [
        (18, APP_COLORS["info"]),
        (42, APP_COLORS["success"]),
        (57, APP_COLORS["danger"]),
    ]
