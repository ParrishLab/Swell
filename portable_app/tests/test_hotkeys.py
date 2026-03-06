import unittest

from app.app import SDSegmentationApp


class _ToolModeVar:
    def __init__(self, value="select"):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class _FocusWidget:
    def __init__(self, cls_name):
        self._cls_name = cls_name

    def winfo_class(self):
        return self._cls_name


class _RootStub:
    def __init__(self, focused):
        self._focused = focused

    def focus_get(self):
        return self._focused


class HotkeysTests(unittest.TestCase):
    def _make_app(self, focused_class):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.root = _RootStub(_FocusWidget(focused_class))
        app.tool_mode = _ToolModeVar("select")
        app.update_calls = 0
        app.update_display = lambda: setattr(app, "update_calls", app.update_calls + 1)
        return app

    def test_b_sets_brush_when_not_typing(self):
        app = self._make_app("Canvas")
        out = app._set_tool_brush_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.tool_mode.get(), "brush")
        self.assertEqual(app.update_calls, 1)

    def test_e_sets_eraser_when_not_typing(self):
        app = self._make_app("Canvas")
        out = app._set_tool_eraser_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.tool_mode.get(), "eraser")
        self.assertEqual(app.update_calls, 1)

    def test_hotkeys_ignored_while_typing(self):
        app = self._make_app("Entry")
        out = app._set_tool_brush_hotkey()
        self.assertIsNone(out)
        self.assertEqual(app.tool_mode.get(), "select")
        self.assertEqual(app.update_calls, 0)


if __name__ == "__main__":
    unittest.main()
