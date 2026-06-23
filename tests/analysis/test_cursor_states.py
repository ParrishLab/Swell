import unittest

from swell.analysis.app import SwellAnalysisApp


class _ToolModeVar:
    def __init__(self, value="select"):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class _BrushSizeVar:
    def __init__(self, value=10.0):
        self.value = float(value)

    def get(self):
        return self.value


class _CanvasStub:
    def __init__(self):
        self.cursor = None
        self.deleted = []
        self.ovals = []

    def config(self, **kwargs):
        self.cursor = kwargs.get("cursor", self.cursor)

    def delete(self, tag):
        self.deleted.append(tag)

    def create_oval(self, *args, **kwargs):
        self.ovals.append((args, kwargs))


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


class CursorStateTests(unittest.TestCase):
    def _make_app(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app.root = _RootStub(_FocusWidget("Canvas"))
        app.tool_mode = _ToolModeVar("select")
        app.brush_size = _BrushSizeVar(10.0)
        app.display_ratio = 1.0
        app.last_mouse_x = None
        app.last_mouse_y = None
        app._space_pan_requested = False
        app._viewport_pan_active = False
        app._viewport_pan_canvas = None
        app.canvas_left = _CanvasStub()
        app.canvas_right = _CanvasStub()
        app.canvas_preview = _CanvasStub()
        return app

    def test_draw_brush_cursor_keeps_pan_cursor_when_pan_is_active(self):
        app = self._make_app()
        app._viewport_pan_active = True
        app._viewport_pan_canvas = app.canvas_left

        app._draw_brush_cursor_on_canvas()

        self.assertEqual(app.canvas_left.cursor, "fleur")
        self.assertIn("cursor_brush", app.canvas_left.deleted)

    def test_space_pan_toggles_viewport_cursors(self):
        app = self._make_app()

        app._set_space_pan_active()
        self.assertTrue(app._space_pan_requested)
        self.assertEqual(app.canvas_left.cursor, "fleur")
        self.assertEqual(app.canvas_right.cursor, "fleur")
        self.assertEqual(app.canvas_preview.cursor, "fleur")

        app._clear_space_pan_active()
        self.assertFalse(app._space_pan_requested)
        self.assertEqual(app.canvas_left.cursor, "arrow")
        self.assertEqual(app.canvas_right.cursor, "arrow")
        self.assertEqual(app.canvas_preview.cursor, "arrow")


if __name__ == "__main__":
    unittest.main()
