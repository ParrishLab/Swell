from __future__ import annotations

from types import SimpleNamespace

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


class _TooltipWindow:
    def __init__(self) -> None:
        self.visible = False
        self.geometry_value = ""
        self.lifted = False

    def geometry(self, value: str) -> None:
        self.geometry_value = value

    def deiconify(self) -> None:
        self.visible = True

    def lift(self) -> None:
        self.lifted = True

    def withdraw(self) -> None:
        self.visible = False


class _TooltipLabel:
    def __init__(self) -> None:
        self.text = "stale"

    def configure(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


def test_host_app_main_overlay_tooltip_hides_and_clears_blank_text() -> None:
    app = SwellHostApp.__new__(SwellHostApp)
    tip = _TooltipWindow()
    label = _TooltipLabel()
    app._main_overlay_tooltip = tip
    app._main_overlay_tooltip_label = label

    app._show_main_overlay_tooltip(SimpleNamespace(x_root=10, y_root=20), "   ")

    assert tip.visible is False
    assert label.text == ""


def test_host_app_main_overlay_tooltip_shows_stripped_text() -> None:
    app = SwellHostApp.__new__(SwellHostApp)
    tip = _TooltipWindow()
    label = _TooltipLabel()
    app._main_overlay_tooltip = tip
    app._main_overlay_tooltip_label = label

    app._show_main_overlay_tooltip(SimpleNamespace(x_root=10, y_root=20), "  Event 1  ")

    assert tip.visible is True
    assert tip.geometry_value == "+22+32"
    assert tip.lifted is True
    assert label.text == "Event 1"
