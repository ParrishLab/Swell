import unittest
from unittest.mock import patch

from sdapp.analysis.ui.theme import apply_theme
from sdapp.analysis.ui.widgets import build_preview_overlay


class _FakeStyle:
    def __init__(self, _root=None):
        self.theme_calls = []
        self.config_calls = []
        self.map_calls = []
        self.layout_calls = []
        self.registered = []
        self.fail_scrollbar_once = False

    def theme_use(self, name):
        self.theme_calls.append(name)

    def configure(self, style_name, **kwargs):
        if self.fail_scrollbar_once and style_name == "TScrollbar":
            self.fail_scrollbar_once = False
            raise RuntimeError("duplicate style builder")
        self.config_calls.append((style_name, kwargs))

    def map(self, style_name, **kwargs):
        self.map_calls.append((style_name, kwargs))

    def layout(self, style_name, layout):
        self.layout_calls.append((style_name, layout))

    def _register_ttkstyle(self, style_name):
        self.registered.append(style_name)


class _FakeFrame:
    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.place_args = None
        self.grid_prop = None

    def grid_propagate(self, flag):
        self.grid_prop = flag

    def columnconfigure(self, *_args, **_kwargs):
        return None

    def rowconfigure(self, *_args, **_kwargs):
        return None

    def place(self, **kwargs):
        self.place_args = kwargs


class _FakeCanvas:
    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.grid_args = None

    def grid(self, **kwargs):
        self.grid_args = kwargs


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
        with patch("sdapp.shared.ui.theme.Style", return_value=fake):
            apply_theme(root=None)
        configured = {name for name, _ in fake.config_calls}
        self.assertIn("AppCard.TFrame", configured)
        self.assertIn("AppPreview.TFrame", configured)
        self.assertIn("AppLoading.Horizontal.TProgressbar", configured)
        self.assertIn("AppStrip.TRadiobutton", configured)
        self.assertIn("AppStrip.TCheckbutton", configured)
        self.assertIn("Vertical.TScrollbar", configured)
        self.assertIn("Horizontal.TScrollbar", configured)
        self.assertTrue(any(style_name == "Vertical.TScrollbar" for style_name, _ in fake.layout_calls))
        mapped = {name for name, _ in fake.map_calls}
        self.assertIn("AppStrip.TRadiobutton", mapped)
        self.assertIn("AppStrip.TCheckbutton", mapped)

    def test_apply_theme_falls_back_when_bootstrap_scrollbar_builder_fails(self):
        fake = _FakeStyle(None)
        fake.fail_scrollbar_once = True
        fallback_calls = []
        with (
            patch("sdapp.shared.ui.theme.Style", return_value=fake),
            patch("sdapp.shared.ui.theme.BOOTSTRAP_AVAILABLE", True),
            patch(
                "sdapp.shared.ui.theme.tk_ttk.Style.configure",
                autospec=True,
                side_effect=lambda style_obj, style_name, **kwargs: fallback_calls.append((style_obj, style_name, kwargs)),
            ),
        ):
            apply_theme(root=None)
        self.assertTrue(any(style_name == "TScrollbar" for _, style_name, _ in fallback_calls))
        self.assertIn("TScrollbar", fake.registered)

    def test_build_preview_overlay_binds_drag_handlers(self):
        with patch("sdapp.analysis.ui.widgets.ttk.Frame", _FakeFrame), patch("sdapp.analysis.ui.widgets.tk.Canvas", _FakeCanvas), patch(
            "sdapp.analysis.ui.widgets.ttk.Label", _FakeLabel
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
