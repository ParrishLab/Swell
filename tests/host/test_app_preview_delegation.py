from __future__ import annotations

from swell.host.app import SwellHostApp


class _PreviewStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def update_preview(self, frame_idx: int) -> None:
        self.calls.append(("update_preview", int(frame_idx)))

    def redraw_main_overlay(self) -> None:
        self.calls.append(("redraw_main_overlay", None))


def test_host_app_delegates_preview_methods_to_preview_controller() -> None:
    app = SwellHostApp.__new__(SwellHostApp)
    preview = _PreviewStub()
    app._get_preview_controller = lambda: preview

    app._update_preview(7)
    app._redraw_main_overlay()

    assert preview.calls == [("update_preview", 7), ("redraw_main_overlay", None)]
