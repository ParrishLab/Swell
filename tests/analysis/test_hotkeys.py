import unittest

from sdapp.analysis.app import SDSegmentationApp
from sdapp.analysis.core.region_tools import REGION_EXCLUDE_TOOL, REGION_INCLUDE_TOOL


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


class _WheelEvent:
    def __init__(self, widget, *, delta=0, num=None, x=10, y=12):
        self.widget = widget
        self.delta = delta
        self.num = num
        self.x = x
        self.y = y


class HotkeysTests(unittest.TestCase):
    def _make_app(self, focused_class):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.root = _RootStub(_FocusWidget(focused_class))
        app.tool_mode = _ToolModeVar("select")
        app.update_calls = 0
        app.update_display = lambda: setattr(app, "update_calls", app.update_calls + 1)
        app.canvas_left = object()
        app.zoom_calls = []
        app.reset_zoom_calls = 0
        app._zoom_shared_viewport = lambda canvas, direction, anchor_x=None, anchor_y=None: app.zoom_calls.append(
            (canvas, direction, anchor_x, anchor_y)
        ) or "break"
        app._reset_viewport_to_fit = lambda update_display=False: setattr(app, "reset_zoom_calls", app.reset_zoom_calls + 1)
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

    def test_k_sets_box_when_not_typing(self):
        app = self._make_app("Canvas")
        out = app._set_tool_box_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.tool_mode.get(), "box")
        self.assertEqual(app.update_calls, 1)

    def test_g_sets_fill_when_not_typing(self):
        app = self._make_app("Canvas")
        out = app._set_tool_fill_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.tool_mode.get(), "fill")
        self.assertEqual(app.update_calls, 1)

    def test_shift_g_sets_fill_erase_when_not_typing(self):
        app = self._make_app("Canvas")
        out = app._set_tool_fill_erase_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.tool_mode.get(), "fill_erase")
        self.assertEqual(app.update_calls, 1)

    def test_r_sets_include_region_when_not_typing(self):
        app = self._make_app("Canvas")
        app._reset_region_options_to_default_range = lambda: None
        out = app._set_tool_region_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.tool_mode.get(), REGION_INCLUDE_TOOL)
        self.assertEqual(app.update_calls, 1)

    def test_shift_r_sets_exclude_region_when_not_typing(self):
        app = self._make_app("Canvas")
        app._reset_region_options_to_default_range = lambda: None
        out = app._set_tool_region_exclude_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.tool_mode.get(), REGION_EXCLUDE_TOOL)
        self.assertEqual(app.update_calls, 1)

    def test_l_toggles_ground_truth_when_not_typing(self):
        app = self._make_app("Canvas")
        app.gt_calls = 0
        app.toggle_ground_truth_current_frame = lambda: setattr(app, "gt_calls", app.gt_calls + 1)
        out = app._toggle_ground_truth_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.gt_calls, 1)

    def test_l_ignored_while_typing(self):
        app = self._make_app("Entry")
        app.gt_calls = 0
        app.toggle_ground_truth_current_frame = lambda: setattr(app, "gt_calls", app.gt_calls + 1)
        self.assertIsNone(app._toggle_ground_truth_hotkey())
        self.assertEqual(app.gt_calls, 0)

    def test_hotkeys_ignored_while_typing(self):
        app = self._make_app("Entry")
        app._reset_region_options_to_default_range = lambda: None
        out = app._set_tool_brush_hotkey()
        self.assertIsNone(out)
        self.assertEqual(app.tool_mode.get(), "select")
        self.assertEqual(app.update_calls, 0)
        self.assertIsNone(app._set_tool_region_hotkey())
        self.assertIsNone(app._set_tool_region_exclude_hotkey())
        self.assertEqual(app.tool_mode.get(), "select")

    def test_zoom_hotkeys_delegate_to_shared_viewport(self):
        app = self._make_app("Canvas")
        self.assertEqual(app._zoom_in_hotkey(), "break")
        self.assertEqual(app._zoom_out_hotkey(), "break")
        self.assertEqual([call[1] for call in app.zoom_calls], [1, -1])

    def test_reset_zoom_hotkey_ignored_while_typing(self):
        app = self._make_app("Entry")
        out = app._reset_zoom_hotkey()
        self.assertIsNone(out)
        self.assertEqual(app.reset_zoom_calls, 0)

    def test_reset_zoom_hotkey_resets_viewport(self):
        app = self._make_app("Canvas")
        out = app._reset_zoom_hotkey()
        self.assertEqual(out, "break")
        self.assertEqual(app.reset_zoom_calls, 1)

    def test_save_current_masks_hotkey_invokes_save(self):
        app = self._make_app("Entry")
        app.save_calls = 0
        app.save_current_masks = lambda: setattr(app, "save_calls", app.save_calls + 1)

        out = app._save_current_masks_hotkey()

        self.assertEqual(out, "break")
        self.assertEqual(app.save_calls, 1)

    def test_mouse_wheel_zooms_hovered_canvas(self):
        app = self._make_app("Canvas")
        hovered = object()
        out = app._on_canvas_mouse_wheel(_WheelEvent(hovered, delta=120, x=33, y=44))
        self.assertEqual(out, "break")
        self.assertEqual(app.zoom_calls[0], (hovered, 1, 33, 44))


if __name__ == "__main__":
    unittest.main()
