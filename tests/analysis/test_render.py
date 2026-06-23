import unittest

import numpy as np
from PIL import Image

from swell.analysis.core.render import RenderActions
from swell.analysis.core.seg_state import SegmentationState
from swell.analysis.core.viewport import ViewportState, compute_transform
from swell.shared.image_overlay import frame_to_rgb_u8


def _build_tk_harness_or_skip(test, factory):
    """Construct a harness that needs a real Tk root, skipping when Tk is
    unavailable (e.g. headless or misconfigured CI runners)."""
    import tkinter as tk

    try:
        return factory()
    except tk.TclError as exc:
        test.skipTest(f"Tk unavailable: {exc}")


class _CanvasStub:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.items = []

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height

    def winfo_ismapped(self):
        return True

    def delete(self, *_args):
        self.items.clear()

    def create_image(self, *args, **kwargs):
        self.items.append(("image", args, kwargs))

    def create_text(self, *args, **kwargs):
        self.items.append(("text", args, kwargs))

    def create_oval(self, *args, **kwargs):
        self.items.append(("oval", args, kwargs))

    def create_rectangle(self, *args, **kwargs):
        self.items.append(("rectangle", args, kwargs))

    def create_line(self, *args, **kwargs):
        self.items.append(("line", args, kwargs))


class _RenderHarness(RenderActions):
    pass


class _ViewportRenderHarness(RenderActions):
    def __init__(self):
        self.viewport_state = ViewportState(center_x=5.0, center_y=5.0, zoom_factor=2.0)

    def _get_canvas_viewport_transform(self, canvas, img_w, img_h):
        return compute_transform(
            self.viewport_state,
            canvas_width=canvas.winfo_width(),
            canvas_height=canvas.winfo_height(),
            image_width=img_w,
            image_height=img_h,
        )


class _DisplayHarness(RenderActions):
    def __init__(self):
        self.current_frame_idx = 0
        self.frame_names = ["frame.tif"]
        self.seg_state = SegmentationState()
        self.masks_cache = self.seg_state.masks_cache
        self.paint_layers = self.seg_state.paint_layers
        self.is_dragging = False
        self._mask_peek = False
        self.canvas_left = _CanvasStub(20, 20)
        self.canvas_preview = _CanvasStub(20, 20)
        self.canvas_right = None
        self.tool_mode = type("ToolMode", (), {"get": lambda _self: "select"})()
        self.captured_left = None
        self.captured_tokens = []

    def _get_frame_count(self):
        return 1

    def _get_visual_frame(self, _idx):
        return np.full((4, 4), 40, dtype=np.uint8)

    def _get_raw_frame(self, _idx):
        return np.full((4, 4), 40, dtype=np.uint8)

    def _get_canvas_viewport_transform(self, canvas, img_w, img_h):
        return compute_transform(
            ViewportState(center_x=2.0, center_y=2.0, zoom_factor=1.0),
            canvas_width=canvas.winfo_width(),
            canvas_height=canvas.winfo_height(),
            image_width=img_w,
            image_height=img_h,
        )

    def _cached_canvas_photo(self, canvas, img_arr, *, resample, fill_value, token):
        if canvas is self.canvas_left:
            self.captured_left = np.asarray(img_arr).copy()
            self.captured_tokens.append(tuple(token))
        return object(), self._get_canvas_viewport_transform(canvas, np.asarray(img_arr).shape[1], np.asarray(img_arr).shape[0])

    def _draw_brush_cursor_on_canvas(self):
        return None

    def _draw_overlay_elements(self, *_args):
        return None

    def _recompute_slider_jump_markers(self):
        return None

    def log_debug(self, *_args):
        return None

    def log_warn(self, *_args):
        return None


class RenderActionsTests(unittest.TestCase):
    def test_display_transform_matches_non_upscaled_rendering(self):
        harness = _RenderHarness()
        canvas = _CanvasStub(width=400, height=300)

        ratio, offset_x, offset_y = harness._get_display_transform(canvas, img_w=100, img_h=50)

        self.assertEqual(ratio, 1.0)
        self.assertEqual(offset_x, 150)
        self.assertEqual(offset_y, 125)

    def test_rendered_center_pixel_stays_aligned_across_canvases(self):
        harness = _ViewportRenderHarness()
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        for y in range(10):
            for x in range(10):
                img[y, x] = [x * 10, y * 10, 0]

        left_img, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=100, height=80),
            img,
            resample=Image.Resampling.NEAREST,
            fill_value=(241, 241, 241),
        )
        preview_img, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=60, height=60),
            img,
            resample=Image.Resampling.NEAREST,
            fill_value=(241, 241, 241),
        )

        left_center = left_img.getpixel((50, 40))
        preview_center = preview_img.getpixel((30, 30))
        self.assertEqual(left_center[:2], preview_center[:2])

    def test_mask_preview_render_uses_nearest_neighbor_values(self):
        harness = _ViewportRenderHarness()
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[:, 5:] = 255
        preview_img, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=63, height=63),
            mask,
            resample=Image.Resampling.NEAREST,
            fill_value=0,
        )
        values = set(preview_img.getdata())
        self.assertEqual(values, {0, 255})

    def test_affine_transform_falls_back_from_lanczos_to_bicubic(self):
        harness = _ViewportRenderHarness()
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[:, :] = [10, 20, 30]
        rendered, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=40, height=40),
            img,
            resample=Image.Resampling.LANCZOS,
            fill_value=(241, 241, 241),
        )
        self.assertEqual(rendered.size, (40, 40))

    def test_display_photo_cache_accessor_not_shadowed_by_cache_store(self):
        harness = _ViewportRenderHarness()
        cache = harness._display_photo_cache()
        cache["sentinel"] = object()

        self.assertIs(harness._display_photo_cache(), cache)

    def test_slider_move_does_not_mark_dirty(self):
        harness = _RenderHarness()
        harness.current_frame_idx = 0
        harness.update_display = lambda: None
        harness._schedule_analysis_prewarm = lambda _idx: None
        harness._initial_frame_nav_ts = None
        calls = []
        harness._mark_project_dirty = lambda reason="": calls.append(str(reason))

        harness.on_slider_move(3)

        self.assertEqual(harness.current_frame_idx, 3)
        self.assertEqual(calls, [])

    def test_mask_peek_suppresses_overlay_and_participates_in_cache_token(self):
        harness = _DisplayHarness()
        base_mask = np.zeros((4, 4), dtype=bool)
        base_mask[1:3, 1:3] = True
        minus = np.zeros((4, 4), dtype=bool)
        minus[1, 1] = True
        plus = np.zeros((4, 4), dtype=bool)
        harness.seg_state.set_mask(0, base_mask)
        harness.seg_state.set_paint_layer(0, plus, minus)

        harness.update_display(update_preview=False)
        overlaid = harness.captured_left.copy()
        token_without_peek = harness.captured_tokens[-1]

        harness._mask_peek = True
        harness.update_display(update_preview=False)
        peeked = harness.captured_left.copy()
        token_with_peek = harness.captured_tokens[-1]

        expected_base = frame_to_rgb_u8(np.full((4, 4), 40, dtype=np.uint8))
        self.assertFalse(np.array_equal(overlaid, expected_base))
        self.assertTrue(np.array_equal(peeked, expected_base))
        self.assertNotEqual(token_without_peek, token_with_peek)

    def test_region_overlay_draws_visible_selected_region_handles(self):
        harness = _ViewportRenderHarness()
        harness.current_frame_idx = 0
        harness.points = {}
        harness.boxes = {}
        harness.selected_point = None
        harness.selected_region_id = "region_a"
        harness.seg_state = SegmentationState()
        harness.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "include",
                "visible": True,
                "frame_start": 0,
                "frame_end": 1,
                "polygon": [[1, 1], [5, 1], [5, 5]],
            }
        )
        harness.interaction_controller = None
        harness.canvas_left = _CanvasStub(width=100, height=100)
        transform = harness._get_canvas_viewport_transform(harness.canvas_left, 10, 10)

        harness._draw_overlay_elements(transform, (10, 10))

        self.assertTrue(any(item[0] == "line" for item in harness.canvas_left.items))
        self.assertTrue(any(item[0] == "rectangle" for item in harness.canvas_left.items))

    def test_single_point_region_draft_draws_handle_without_line(self):
        harness = _ViewportRenderHarness()
        harness.current_frame_idx = 0
        harness.points = {}
        harness.boxes = {}
        harness.selected_point = None
        harness.selected_region_id = None
        harness.seg_state = SegmentationState()
        harness.canvas_left = _CanvasStub(width=100, height=100)
        harness.interaction_controller = type(
            "DraftController",
            (),
            {
                "get_region_draft_points": lambda _self: [[2.0, 3.0]],
                "is_region_draft_closed": lambda _self: False,
            },
        )()
        transform = harness._get_canvas_viewport_transform(harness.canvas_left, 10, 10)

        harness._draw_overlay_elements(transform, (10, 10))

        self.assertFalse(any(item[0] == "line" for item in harness.canvas_left.items))
        self.assertTrue(any(item[0] == "rectangle" for item in harness.canvas_left.items))

    def test_selected_box_handles_use_tk_color_string(self):
        harness = _DisplayHarness()
        harness.points = {}
        harness.boxes = {0: [1.0, 1.0, 3.0, 3.0]}
        harness.selected_point = (0, "box")
        transform = harness._get_canvas_viewport_transform(harness.canvas_left, 4, 4)

        RenderActions._draw_overlay_elements(harness, transform, (4, 4))

        rectangles = [item for item in harness.canvas_left.items if item[0] == "rectangle"]
        self.assertEqual(len(rectangles), 9)
        self.assertEqual(rectangles[0][2].get("outline"), "yellow")
        handle_fills = [kwargs.get("fill") for _kind, _args, kwargs in rectangles[1:]]
        self.assertTrue(all(isinstance(fill, str) and fill.startswith("#") for fill in handle_fills))
        handle_outlines = [kwargs.get("outline") for _kind, _args, kwargs in rectangles[1:]]
        self.assertEqual(set(handle_outlines), {"yellow"})

    def test_unselected_box_outline_matches_unselected_point_outline(self):
        harness = _DisplayHarness()
        harness.points = {}
        harness.boxes = {0: [1.0, 1.0, 3.0, 3.0]}
        harness.selected_point = None
        transform = harness._get_canvas_viewport_transform(harness.canvas_left, 4, 4)

        RenderActions._draw_overlay_elements(harness, transform, (4, 4))

        rectangles = [item for item in harness.canvas_left.items if item[0] == "rectangle"]
        self.assertEqual(len(rectangles), 1)
        self.assertEqual(rectangles[0][2].get("outline"), "white")

    def test_ghost_outlines_caching_and_rendering(self):
        import tkinter as tk
        class _GhostHarness(_DisplayHarness):
            def __init__(self):
                self.root = tk.Tk()
                super().__init__()
                self.ghost_outlines_enabled_var = tk.BooleanVar(value=True)
                self.ghost_range_var = tk.IntVar(value=2)
                self.leverage_visibility_var = tk.BooleanVar(value=True)
                self.current_frame_idx = 2
                self.frame_names = ["f0", "f1", "f2", "f3", "f4"]

                m1 = np.zeros((4, 4), dtype=bool)
                m1[0, 0] = True
                m3 = np.zeros((4, 4), dtype=bool)
                m3[3, 3] = True

                self.seg_state.set_mask(1, m1)
                self.seg_state.set_mask(3, m3)

            def _get_frame_count(self):
                return 5

        harness = _build_tk_harness_or_skip(self, _GhostHarness)
        try:
            harness.update_display(update_preview=False)
            self.assertTrue(hasattr(harness, "_ghost_contours_cache"))
            self.assertEqual(len(harness._ghost_contours_cache), 2)

            token_with_ghosts = harness.captured_tokens[-1]
            self.assertTrue(token_with_ghosts[5])
            self.assertEqual(len(token_with_ghosts[6]), 4)

            m1_new = np.zeros((4, 4), dtype=bool)
            m1_new[1, 1] = True
            harness.seg_state.set_mask(1, m1_new)

            harness.update_display(update_preview=False)
            token_after_edit = harness.captured_tokens[-1]
            self.assertNotEqual(token_with_ghosts, token_after_edit)
        finally:
            harness.root.destroy()

    def test_ghost_outlines_require_explicit_toggle(self):
        import tkinter as tk
        class _GhostHarness(_DisplayHarness):
            def __init__(self):
                self.root = tk.Tk()
                super().__init__()
                self.ghost_outlines_enabled_var = tk.BooleanVar(value=False)
                self.ghost_range_var = tk.IntVar(value=1)
                self.leverage_visibility_var = tk.BooleanVar(value=True)
                self.current_frame_idx = 1
                self.frame_names = ["f0", "f1", "f2"]

                m0 = np.zeros((4, 4), dtype=bool)
                m0[0, 0] = True
                self.seg_state.set_mask(0, m0)

            def _get_frame_count(self):
                return 3

        harness = _build_tk_harness_or_skip(self, _GhostHarness)
        try:
            harness.tool_mode = type("ToolMode", (), {"get": lambda _self: "select"})()
            harness.update_display(update_preview=False)
            token_select = harness.captured_tokens[-1]
            self.assertFalse(token_select[5])

            harness.tool_mode = type("ToolMode", (), {"get": lambda _self: "brush"})()
            harness.update_display(update_preview=False)
            token_brush = harness.captured_tokens[-1]
            self.assertFalse(token_brush[5])

            harness.ghost_outlines_enabled_var.set(True)
            harness.update_display(update_preview=False)
            token_enabled = harness.captured_tokens[-1]
            self.assertTrue(token_enabled[5])
        finally:
            harness.root.destroy()

    def test_view_dock_controls_and_callbacks(self):
        import tkinter as tk
        from swell.analysis.ui.layout import LayoutBuilder
        from swell.analysis.ui.theme import SPACING

        class _MockApp(LayoutBuilder):
            def __init__(self):
                self.root = tk.Tk()
                self.ghost_outlines_enabled_var = tk.BooleanVar(value=False)
                self.ghost_range_var = tk.IntVar(value=2)
                self.leverage_visibility_var = tk.BooleanVar(value=True)
                self.tool_mode = tk.StringVar(value="select")

                self.seg_state = SegmentationState()
                self.slider = type("Slider", (), {"set": lambda s, v: setattr(self, "slider_val", v)})()
                self.slider_val = None
                self.log_calls = []

            def _build_dock_section(self, parent, *, row, title, collapsible=True, open_state=True, tooltip=None):
                del tooltip
                body = tk.Frame(parent)
                body.grid()
                return parent, body

            def update_display(self):
                pass

            def _redraw_slider_overlay(self):
                pass

            def toggle_ground_truth_current_frame(self):
                pass

            def log_info(self, context, msg):
                self.log_calls.append((context, msg))

        app = _build_tk_harness_or_skip(self, _MockApp)
        parent = tk.Frame(app.root)

        section = app._build_view_section(parent, row=0)
        self.assertIsNotNone(section)
        self.assertEqual(app.btn_ground_truth.cget("text"), "Lock current frame as ground truth")
        self.assertFalse(hasattr(app, "chk_ghost_auto"))

        app._on_ghost_range_scale_changed(5.0)
        self.assertEqual(app.ghost_range_var.get(), 5)
        self.assertEqual(app.lbl_ghost_range_val.cget("text"), "5")

        app.jump_to_suggested_correction()
        self.assertEqual(app.slider_val, None)
        self.assertIn(("View", "No suggested correction frame available"), app.log_calls)

        app.seg_state.leverage_suggested_frame = 3
        app.jump_to_suggested_correction()
        self.assertEqual(app.slider_val, 3)
        self.assertIn(("View", "Jumped to suggested correction frame 4"), app.log_calls)

        app.root.destroy()

    def test_region_options_bar_uses_split_region_semantics(self):
        import tkinter as tk
        from swell.analysis.ui.layout import LayoutBuilder

        class _MockApp(LayoutBuilder):
            def __init__(self):
                self.root = tk.Tk()

            def on_sensitivity_change(self, _val):
                pass

            def on_brush_size_change(self, _val):
                pass

            def fill_current_frame_holes(self):
                pass

            def close_region_draft(self):
                pass

            def cancel_region_draft(self):
                pass

            def commit_region_draft(self):
                pass

            def _apply_selected_region_options_event(self, _event=None):
                pass

            def convert_selected_region_mode(self):
                pass

        def _texts(widget):
            out = []
            for child in widget.winfo_children():
                try:
                    text = child.cget("text")
                    if text:
                        out.append(str(text))
                except Exception:
                    pass
                out.extend(_texts(child))
            return out

        app = _build_tk_harness_or_skip(self, _MockApp)
        app.root.withdraw()
        try:
            parent = tk.Frame(app.root)
            app._build_tool_options_bar(parent)
            texts = _texts(app.tool_option_frames["region_include"])

            self.assertIn("Include Region", texts)
            self.assertIn("Frames", texts)
            self.assertIn("Close Shape", texts)
            self.assertIn("Discard", texts)
            self.assertIn("Add Region", texts)
            self.assertIn("Convert to Exclude", texts)
            self.assertNotIn("Commit Region", texts)
            self.assertNotIn("Apply Selected", texts)
            self.assertNotIn("Close Polygon", texts)
            self.assertNotIn("Include", texts)
            self.assertNotIn("Exclude", texts)
        finally:
            app.root.destroy()

    def test_save_current_masks_button_is_fixed_below_inspector_scroll(self):
        import tkinter as tk
        from swell.analysis.ui.layout import LayoutBuilder

        class _MockApp(LayoutBuilder):
            def __init__(self):
                self.root = tk.Tk()

            def _placeholder(self, parent, row):
                frame = tk.Frame(parent)
                frame.grid(row=row, column=0, sticky="ew")
                return frame

            def _build_reference_section(self, parent, row):
                return self._placeholder(parent, row)

            def _build_propagation_group(self, parent, column, *, row=0):
                del column
                return self._placeholder(parent, row)

            def _build_event_metrics_group(self, parent, column, *, row=0):
                del column
                return self._placeholder(parent, row)

            def _build_view_section(self, parent, row):
                return self._placeholder(parent, row)

            def _build_regions_section(self, parent, row):
                return self._placeholder(parent, row)

            def save_current_masks(self):
                pass

            def toggle_ground_truth_current_frame(self):
                pass

        app = _build_tk_harness_or_skip(self, _MockApp)
        app.root.withdraw()
        try:
            parent = tk.Frame(app.root)
            parent.grid(row=0, column=0, sticky="nsew")

            app.build_inspector_dock(parent)

            save_frame = app.btn_save_masks.master
            self.assertIs(save_frame.master, app.inspector_dock)
            self.assertIsNot(save_frame.master, app.inspector_scroll_body)
            self.assertEqual(str(save_frame.grid_info().get("row")), "1")
            self.assertEqual(str(app.inspector_scroll_canvas.grid_info().get("row")), "0")
        finally:
            app.root.destroy()

    def test_ghost_contour_roi_blend_matches_full_image(self):
        import cv2

        from swell.analysis.core.render import GHOST_CONTOUR_THICKNESS

        class _GhostBlendHarness(RenderActions):
            def __init__(self):
                self.seg_state = SegmentationState()
                self._ghost_contours_cache = {}

            def _array_content_token(self, arr):
                return (arr.shape, int(arr.sum()))

        harness = _GhostBlendHarness()
        h = w = 128
        mask = np.zeros((h, w), dtype=bool)
        mask[40:90, 35:100] = True
        harness.seg_state.set_mask(3, mask)
        color = (0, 191, 255)
        alpha = 0.6

        base = np.full((h, w, 3), 50, dtype=np.uint8)

        # Reference: the original full-image copy + addWeighted.
        _, entry = harness._ghost_cache_entry(3, mask, h, w)
        overlay = base.copy()
        cv2.drawContours(overlay, entry["contours"], -1, color, GHOST_CONTOUR_THICKNESS)
        reference = cv2.addWeighted(base, 1.0 - alpha, overlay, alpha, 0)

        roi_result = base.copy()
        token = harness._draw_ghost_contour(roi_result, 3, color, alpha)

        self.assertEqual(token, (3, (mask.shape, int(mask.sum()))))
        self.assertTrue(np.array_equal(roi_result, reference))

    def test_ghost_contour_empty_frame_returns_none_token(self):
        class _GhostBlendHarness(RenderActions):
            def __init__(self):
                self.seg_state = SegmentationState()
                self._ghost_contours_cache = {}

            def _array_content_token(self, arr):
                return (arr.shape, int(arr.sum()))

        harness = _GhostBlendHarness()
        img = np.full((32, 32, 3), 50, dtype=np.uint8)
        before = img.copy()
        token = harness._draw_ghost_contour(img, 9, (255, 0, 128), 0.5)
        self.assertEqual(token, (9, None))
        self.assertTrue(np.array_equal(img, before))


if __name__ == "__main__":
    unittest.main()
