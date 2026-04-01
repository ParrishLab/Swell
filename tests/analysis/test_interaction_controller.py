import unittest

import numpy as np

from sdapp.analysis.core.interaction_controller import InteractionController
from sdapp.analysis.core.seg_state import SegmentationState


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _CanvasStub:
    def __init__(self):
        self.deleted = []
        self.cursor = None

    def delete(self, tag):
        self.deleted.append(tag)

    def config(self, **kwargs):
        self.cursor = kwargs.get("cursor")


class _SliderStub:
    def __init__(self, holder):
        self.holder = holder
        self.values = []

    def set(self, value):
        self.values.append(value)
        self.holder["current_idx"] = value


class _LabelStub:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)


class _Event:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class InteractionControllerTests(unittest.TestCase):
    def _make_controller(self, *, display_transform=(1.0, 0.0, 0.0)):
        seg_state = SegmentationState()
        points = {}
        paint_layers = {}
        masks_cache = {}
        holder = {
            "current_idx": 0,
            "selected_point": None,
            "is_dragging": False,
            "last_mouse_x": None,
            "last_mouse_y": None,
            "last_img_x": None,
            "last_img_y": None,
            "points_snapshot_before": None,
            "paint_snapshot_before": None,
            "model_ready": True,
            "records": [],
            "updates": 0,
            "preview_segments": [],
            "preview_clears": 0,
            "recompute": 0,
            "mask_updates": 0,
            "prunes": 0,
        }
        frames_sub_viz = [np.zeros((20, 20), dtype=np.uint8) for _ in range(3)]
        frames_raw = [np.zeros((20, 20), dtype=np.uint8) for _ in range(3)]
        tool_mode = _Var("point_pos")
        brush_size = _Var(3)
        canvas_left = _CanvasStub()
        slider = _SliderStub(holder)
        lbl = _LabelStub()
        frame_shape = (20, 20)

        c = InteractionController(
            seg_state=seg_state,
            points=points,
            paint_layers=paint_layers,
            masks_cache=masks_cache,
            get_current_frame_idx=lambda: holder["current_idx"],
            set_selected_point=lambda v: holder.__setitem__("selected_point", v),
            get_selected_point=lambda: holder["selected_point"],
            get_is_dragging=lambda: holder["is_dragging"],
            set_is_dragging=lambda v: holder.__setitem__("is_dragging", v),
            get_last_mouse_x=lambda: holder["last_mouse_x"],
            set_last_mouse_x=lambda v: holder.__setitem__("last_mouse_x", v),
            set_last_mouse_y=lambda v: holder.__setitem__("last_mouse_y", v),
            get_last_img_x=lambda: holder["last_img_x"],
            set_last_img_x=lambda v: holder.__setitem__("last_img_x", v),
            get_last_img_y=lambda: holder["last_img_y"],
            set_last_img_y=lambda v: holder.__setitem__("last_img_y", v),
            get_points_snapshot_before=lambda: holder["points_snapshot_before"],
            set_points_snapshot_before=lambda v: holder.__setitem__("points_snapshot_before", v),
            get_paint_snapshot_before=lambda: holder["paint_snapshot_before"],
            set_paint_snapshot_before=lambda v: holder.__setitem__("paint_snapshot_before", v),
            tool_mode=tool_mode,
            brush_size=brush_size,
            canvas_left=canvas_left,
            slider=slider,
            lbl_brush_val=lbl,
            get_frame_count=lambda: len(frames_sub_viz),
            get_frame_shape_for_idx=lambda _idx: frame_shape,
            get_display_transform=lambda _canvas, _w, _h: display_transform,
            update_display=lambda **kwargs: holder.__setitem__("updates", holder["updates"] + 1),
            draw_paint_preview_segment=lambda *args: holder["preview_segments"].append(args),
            clear_paint_preview=lambda: holder.__setitem__("preview_clears", holder["preview_clears"] + 1),
            draw_brush_cursor=lambda: None,
            recompute_slider_jump_markers=lambda: holder.__setitem__("recompute", holder["recompute"] + 1),
            update_mask_prediction=lambda _idx: holder.__setitem__("mask_updates", holder["mask_updates"] + 1),
            get_model_ready=lambda: holder["model_ready"],
            record_action=lambda *args: holder["records"].append(args),
            prune_empty_point_frames=lambda: holder.__setitem__("prunes", holder["prunes"] + 1),
        )
        return c, holder, tool_mode, lbl

    def test_nav_right_moves_slider(self):
        controller, holder, _mode, _lbl = self._make_controller()
        controller.on_nav_right()
        self.assertEqual(holder["current_idx"], 1)

    def test_on_brush_size_change_updates_label(self):
        controller, _holder, _mode, lbl = self._make_controller()
        controller.on_brush_size_change("12")
        self.assertEqual(lbl.text, "12 px")

    def test_point_click_adds_point_and_records_action(self):
        controller, holder, mode, _lbl = self._make_controller()
        mode.set("point_pos")
        controller._handle_tool(_Event(5, 6), is_click=True)
        self.assertIn(0, controller.points)
        self.assertEqual(controller.points[0][0]["label"], 1)
        self.assertEqual(len(holder["records"]), 1)
        self.assertEqual(holder["mask_updates"], 1)

    def test_delete_selected_point_removes_frame_when_last(self):
        controller, holder, _mode, _lbl = self._make_controller()
        controller.points[0] = [{"x": 1, "y": 1, "label": 1}]
        holder["selected_point"] = (0, 0)
        controller.delete_selected_point()
        self.assertNotIn(0, controller.points)
        self.assertIsNone(holder["selected_point"])
        self.assertEqual(holder["recompute"], 1)

    def test_brush_drag_uses_preview_and_defers_full_redraw_until_mouse_up(self):
        controller, holder, mode, _lbl = self._make_controller()
        mode.set("brush")

        controller.on_mouse_down(_Event(5, 6))
        controller.on_mouse_drag(_Event(8, 9))

        self.assertIn(0, controller.paint_layers)
        self.assertEqual(holder["updates"], 0)
        self.assertEqual(len(holder["preview_segments"]), 2)

        controller.on_mouse_up(_Event(8, 9))

        self.assertEqual(holder["preview_clears"], 2)
        self.assertEqual(holder["updates"], 2)
        self.assertEqual(len(holder["records"]), 1)

    def test_point_click_maps_canvas_coordinates_through_zoomed_transform(self):
        controller, holder, mode, _lbl = self._make_controller(display_transform=(2.0, 10.0, 20.0))
        mode.set("point_pos")
        controller._handle_tool(_Event(14, 28), is_click=True)
        self.assertEqual(controller.points[0][0]["x"], 2)
        self.assertEqual(controller.points[0][0]["y"], 4)
        self.assertEqual(holder["mask_updates"], 1)

    def test_brush_preview_radius_scales_with_zoom(self):
        controller, holder, mode, _lbl = self._make_controller(display_transform=(2.0, 10.0, 20.0))
        mode.set("brush")
        controller.on_mouse_down(_Event(14, 28))
        radius = holder["preview_segments"][0][4]
        self.assertEqual(radius, 6.0)


if __name__ == "__main__":
    unittest.main()
