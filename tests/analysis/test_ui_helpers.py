import unittest
from unittest.mock import patch

from sdapp.analysis.ui.theme import apply_theme
from sdapp.analysis.ui.widgets import build_preview_overlay


class _FakeStyle:
    def __init__(self, _root):
        self.theme_calls = []
        self.config_calls = []
        self.map_calls = []

    def theme_use(self, name):
        self.theme_calls.append(name)

    def configure(self, style_name, **kwargs):
        self.config_calls.append((style_name, kwargs))

    def map(self, style_name, **kwargs):
        self.map_calls.append((style_name, kwargs))


class _FakeFrame:
    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.place_args = None
        self.pack_prop = None

    def pack_propagate(self, flag):
        self.pack_prop = flag

    def place(self, **kwargs):
        self.place_args = kwargs


class _FakeCanvas:
    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.packed = False

    def pack(self, **kwargs):
        self.packed = True


class _FakeLabel:
    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.bindings = []
        self.place_args = None

    def place(self, **kwargs):
        self.place_args = kwargs

    def bind(self, event, handler):
        self.bindings.append((event, handler))


class UiHelpersTests(unittest.TestCase):
    def test_apply_theme_configures_style(self):
        fake = _FakeStyle(None)
        with patch("sdapp.analysis.ui.theme.ttk.Style", return_value=fake):
            apply_theme(root=None)
        configured = {name for name, _ in fake.config_calls}
        self.assertIn("TFrame", configured)
        self.assertIn("Preview.TFrame", configured)
        self.assertTrue(fake.map_calls)

    def test_build_preview_overlay_binds_drag_handlers(self):
        with patch("sdapp.analysis.ui.widgets.ttk.Frame", _FakeFrame), patch("sdapp.analysis.ui.widgets.tk.Canvas", _FakeCanvas), patch(
            "sdapp.analysis.ui.widgets.tk.Label", _FakeLabel
        ):
            start = lambda _e: None
            drag = lambda _e: None
            stop = lambda _e: None
            frame, canvas, grip = build_preview_overlay(parent=object(), on_start=start, on_drag=drag, on_stop=stop)
        self.assertIsInstance(frame, _FakeFrame)
        self.assertIsInstance(canvas, _FakeCanvas)
        self.assertIsInstance(grip, _FakeLabel)
        events = [event for event, _ in grip.bindings]
        self.assertEqual(events, ["<Button-1>", "<B1-Motion>", "<ButtonRelease-1>"])


if __name__ == "__main__":
    unittest.main()
