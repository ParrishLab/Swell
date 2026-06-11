import unittest

import numpy as np

from sdapp.analysis.core.interaction_controller import InteractionController
from sdapp.analysis.core.region_tools import REGION_EXCLUDE_TOOL, REGION_INCLUDE_TOOL
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
        self.rectangles = []

    def delete(self, tag):
        self.deleted.append(tag)

    def config(self, **kwargs):
        self.cursor = kwargs.get("cursor")

    def create_rectangle(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))


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
        boxes = {}
        paint_layers = {}
        masks_cache = {}
        seg_state.points = points
        seg_state.boxes = boxes
        seg_state.paint_layers = paint_layers
        seg_state.masks_cache = masks_cache
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
            "box_previews": [],
            "box_clears": 0,
            "preview_clears": 0,
            "recompute": 0,
            "mask_updates": 0,
            "prunes": 0,
            "region_refresh": 0,
        }
        frames_sub_viz = [np.zeros((20, 20), dtype=np.uint8) for _ in range(3)]
        frames_sub_viz[0][2:8, 2:8] = 40
        frames_sub_viz[0][12:16, 12:16] = 90
        frames_raw = [np.zeros((20, 20), dtype=np.uint8) for _ in range(3)]
        tool_mode = _Var("point_pos")
        brush_size = _Var(3)
        # Fill add/remove is now derived from tool_mode ("fill" / "fill_erase");
        # this var is retained only to keep the returned tuple shape stable.
        fill_mode = _Var("add")
        fill_tolerance = _Var(8.0)
        region_mode = _Var("include")
        region_start_var = _Var("1")
        region_end_var = _Var("3")
        canvas_left = _CanvasStub()
        slider = _SliderStub(holder)
        lbl = _LabelStub()
        frame_shape = (20, 20)

        c = InteractionController(
            seg_state=seg_state,
            points=points,
            boxes=boxes,
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
            fill_tolerance=fill_tolerance,
            region_mode=region_mode,
            region_start_var=region_start_var,
            region_end_var=region_end_var,
            get_selected_region_id=lambda: holder.get("selected_region_id"),
            set_selected_region_id=lambda v: holder.__setitem__("selected_region_id", v),
            refresh_region_controls=lambda: holder.__setitem__("region_refresh", holder["region_refresh"] + 1),
            canvas_left=canvas_left,
            slider=slider,
            lbl_brush_val=lbl,
            get_frame_count=lambda: len(frames_sub_viz),
            get_frame_shape_for_idx=lambda _idx: frame_shape,
            get_visual_frame=lambda idx: frames_sub_viz[idx],
            get_display_transform=lambda _canvas, _w, _h: display_transform,
            update_display=lambda **kwargs: holder.__setitem__("updates", holder["updates"] + 1),
            draw_paint_preview_segment=lambda *args: holder["preview_segments"].append(args),
            clear_paint_preview=lambda: holder.__setitem__("preview_clears", holder["preview_clears"] + 1),
            draw_box_preview=lambda *args: holder["box_previews"].append(args),
            clear_box_preview=lambda: holder.__setitem__("box_clears", holder["box_clears"] + 1),
            draw_brush_cursor=lambda: None,
            recompute_slider_jump_markers=lambda: holder.__setitem__("recompute", holder["recompute"] + 1),
            update_mask_prediction=lambda _idx: holder.__setitem__("mask_updates", holder["mask_updates"] + 1),
            get_model_ready=lambda: holder["model_ready"],
            record_action=lambda *args: holder["records"].append(args),
            prune_empty_point_frames=lambda: holder.__setitem__("prunes", holder["prunes"] + 1),
        )
        return c, holder, tool_mode, lbl, fill_mode, fill_tolerance

    def test_nav_right_moves_slider(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        result = controller.on_nav_right()
        self.assertEqual(holder["current_idx"], 1)
        self.assertEqual(result, "break")

    def test_nav_left_returns_break_without_moving_past_zero(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        result = controller.on_nav_left()
        self.assertEqual(holder["current_idx"], 0)
        self.assertEqual(result, "break")

    def test_on_brush_size_change_updates_label(self):
        controller, _holder, _mode, lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.on_brush_size_change("12")
        self.assertEqual(lbl.text, "12 px")

    def test_point_click_adds_point_and_records_action(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller(display_transform=(2.0, 0.0, 0.0))
        mode.set("point_pos")
        controller._handle_tool(_Event(5, 6), is_click=True)
        self.assertIn(0, controller.points)
        self.assertEqual(controller.points[0][0]["label"], 1)
        self.assertEqual(len(holder["records"]), 1)
        self.assertEqual(holder["mask_updates"], 1)

    def test_delete_selected_point_removes_frame_when_last(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.points[0] = [{"x": 1, "y": 1, "label": 1}]
        holder["selected_point"] = (0, 0)
        controller.delete_selected_point()
        self.assertNotIn(0, controller.points)
        self.assertIsNone(holder["selected_point"])
        self.assertEqual(holder["recompute"], 1)

    def test_brush_drag_uses_preview_and_defers_full_redraw_until_mouse_up(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("brush")

        controller.on_mouse_down(_Event(5, 6))
        controller.on_mouse_drag(_Event(8, 9))

        self.assertIn(0, controller.paint_layers)
        self.assertEqual(holder["updates"], 0)
        self.assertEqual(len(holder["preview_segments"]), 2)

        changed = controller.on_mouse_up(_Event(8, 9))

        self.assertEqual(holder["preview_clears"], 2)
        self.assertEqual(holder["updates"], 2)
        self.assertEqual(len(holder["records"]), 1)
        self.assertTrue(changed)

    def test_mouse_up_compares_paint_payloads_without_numpy_truthiness_error(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("brush")
        layer = {
            "plus": np.zeros((6, 6), dtype=bool),
            "minus": np.zeros((6, 6), dtype=bool),
        }
        layer["plus"][2, 3] = True
        controller.paint_layers[0] = {
            "plus": layer["plus"].copy(),
            "minus": layer["minus"].copy(),
        }
        holder["paint_snapshot_before"] = {
            "plus": layer["plus"].copy(),
            "minus": layer["minus"].copy(),
        }

        changed = controller.on_mouse_up(_Event(0, 0))

        self.assertFalse(changed)

    def test_point_click_maps_canvas_coordinates_through_zoomed_transform(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller(display_transform=(2.0, 10.0, 20.0))
        mode.set("point_pos")
        controller._handle_tool(_Event(14, 28), is_click=True)
        self.assertEqual(controller.points[0][0]["x"], 2)
        self.assertEqual(controller.points[0][0]["y"], 4)
        self.assertEqual(holder["mask_updates"], 1)

    def test_brush_preview_radius_scales_with_zoom(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller(display_transform=(2.0, 10.0, 20.0))
        mode.set("brush")
        controller.on_mouse_down(_Event(14, 28))
        radius = holder["preview_segments"][0][4]
        self.assertEqual(radius, 6.0)

    def test_mouse_up_without_edit_returns_false(self):
        controller, _holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("select")

        changed = controller.on_mouse_up(_Event(0, 0))

        self.assertFalse(changed)

    def test_delete_selected_point_returns_false_when_no_selection(self):
        controller, _holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()

        changed = controller.delete_selected_point()

        self.assertFalse(changed)

    def test_clear_current_frame_data_returns_false_when_frame_empty(self):
        controller, _holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()

        changed = controller.clear_current_frame_data()

        self.assertFalse(changed)

    def test_clear_current_frame_data_records_undoable_clear_frame_snapshot(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.seg_state.points = controller.points
        controller.seg_state.boxes = controller.boxes
        controller.seg_state.paint_layers = controller.paint_layers
        controller.seg_state.masks_cache = controller.masks_cache
        controller.points[0] = [{"x": 2, "y": 2, "label": 1}]
        controller.boxes[0] = [1.0, 2.0, 8.0, 9.0]
        controller.paint_layers[0] = {
            "plus": np.ones((20, 20), dtype=bool),
            "minus": np.zeros((20, 20), dtype=bool),
        }
        controller.masks_cache[0] = np.ones((20, 20), dtype=bool)

        changed = controller.clear_current_frame_data()

        self.assertTrue(changed)
        self.assertEqual(len(holder["records"]), 1)
        action_type, frame_idx, before_payload, after_payload = holder["records"][0]
        self.assertEqual(action_type, "clear_frame")
        self.assertEqual(frame_idx, 0)
        self.assertIsInstance(before_payload, dict)
        self.assertIn("points", before_payload)
        self.assertIn("box", before_payload)
        self.assertIn("paint", before_payload)
        self.assertIn("mask", before_payload)
        self.assertIsNone(after_payload["points"])
        self.assertIsNone(after_payload["box"])
        self.assertIsNone(after_payload["paint"])
        self.assertIsNone(after_payload["mask"])

    def test_box_drag_stores_normalized_image_coordinates_and_records_action(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("box")

        controller.on_mouse_down(_Event(10, 12))
        controller.on_mouse_drag(_Event(4, 5))
        changed = controller.on_mouse_up(_Event(4, 5))

        self.assertTrue(changed)
        self.assertEqual(controller.boxes[0], [4.0, 5.0, 10.0, 12.0])
        self.assertGreaterEqual(len(holder["box_previews"]), 2)
        self.assertGreaterEqual(holder["box_clears"], 1)
        self.assertEqual(holder["records"][0][0], "box")
        self.assertEqual(holder["mask_updates"], 1)

    def test_box_drag_ignores_tiny_boxes(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("box")

        controller.on_mouse_down(_Event(10, 10))
        changed = controller.on_mouse_up(_Event(11, 11))

        self.assertFalse(changed)
        self.assertNotIn(0, controller.boxes)
        self.assertEqual(holder["records"], [])

    def test_select_click_selects_box_prompt(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.seg_state.boxes = controller.boxes
        controller.boxes[0] = [4.0, 5.0, 10.0, 12.0]
        mode.set("select")

        controller.on_mouse_down(_Event(6, 7))

        self.assertEqual(holder["selected_point"], (0, "box"))

    def test_select_drag_moves_box_prompt_and_records_action(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.seg_state.boxes = controller.boxes
        controller.boxes[0] = [2.0, 2.0, 16.0, 16.0]
        mode.set("select")

        controller.on_mouse_down(_Event(9, 9))
        controller.on_mouse_drag(_Event(11, 12))
        changed = controller.on_mouse_up(_Event(11, 12))

        self.assertTrue(changed)
        self.assertEqual(controller.boxes[0], [4.0, 5.0, 18.0, 19.0])
        self.assertEqual(holder["records"][0], ("box", 0, [2.0, 2.0, 16.0, 16.0], [4.0, 5.0, 18.0, 19.0]))
        self.assertEqual(holder["mask_updates"], 1)

    def test_select_drag_box_handle_resizes_prompt(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.seg_state.boxes = controller.boxes
        controller.boxes[0] = [4.0, 5.0, 10.0, 12.0]
        mode.set("select")

        controller.on_mouse_down(_Event(10, 12))
        controller.on_mouse_drag(_Event(14, 16))
        changed = controller.on_mouse_up(_Event(14, 16))

        self.assertTrue(changed)
        self.assertEqual(controller.boxes[0], [4.0, 5.0, 14.0, 16.0])
        self.assertEqual(holder["records"][0], ("box", 0, [4.0, 5.0, 10.0, 12.0], [4.0, 5.0, 14.0, 16.0]))
        self.assertEqual(holder["mask_updates"], 1)

    def test_delete_selected_box_prompt_removes_box(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.seg_state.boxes = controller.boxes
        controller.boxes[0] = [4.0, 5.0, 10.0, 12.0]
        holder["selected_point"] = (0, "box")

        changed = controller.delete_selected_point()

        self.assertTrue(changed)
        self.assertNotIn(0, controller.boxes)
        self.assertIsNone(holder["selected_point"])
        self.assertEqual(holder["records"][0], ("box", 0, [4.0, 5.0, 10.0, 12.0], None))
        self.assertEqual(holder["mask_updates"], 1)

    def test_include_region_tool_commits_polygon_with_range_and_records_action(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set(REGION_INCLUDE_TOOL)

        controller.on_mouse_down(_Event(2, 2))
        controller.on_mouse_down(_Event(8, 2))
        controller.on_mouse_down(_Event(8, 8))
        changed = controller.commit_region_draft()

        self.assertTrue(changed)
        self.assertEqual(len(controller.seg_state.persistent_regions), 1)
        region = controller.seg_state.persistent_regions[0]
        self.assertEqual(region["mode"], "include")
        self.assertEqual(region["frame_start"], 0)
        self.assertEqual(region["frame_end"], 2)
        self.assertEqual(holder["selected_region_id"], region["id"])
        self.assertEqual(holder["records"][0][0], "region")

    def test_exclude_region_tool_commits_exclude_polygon(self):
        controller, _holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set(REGION_EXCLUDE_TOOL)

        controller.on_mouse_down(_Event(2, 2))
        controller.on_mouse_down(_Event(8, 2))
        controller.on_mouse_down(_Event(8, 8))
        changed = controller.commit_region_draft()

        self.assertTrue(changed)
        self.assertEqual(controller.seg_state.persistent_regions[0]["mode"], "exclude")

    def test_region_tool_rejects_tiny_invalid_polygon(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set(REGION_INCLUDE_TOOL)

        controller.on_mouse_down(_Event(2, 2))
        controller.on_mouse_down(_Event(2, 2))
        controller.on_mouse_down(_Event(2, 2))
        changed = controller.commit_region_draft()

        self.assertFalse(changed)
        self.assertEqual(controller.seg_state.persistent_regions, [])
        self.assertEqual(holder["records"], [])

    def test_selected_region_range_update_records_action_without_changing_mode(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        region_id = controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "exclude",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[2, 2], [8, 2], [8, 8]],
            }
        )
        holder["selected_region_id"] = region_id
        controller.region_start_var.set("2")
        controller.region_end_var.set("3")

        changed = controller.apply_selected_region_options()

        self.assertTrue(changed)
        region = controller.seg_state.get_persistent_region(region_id)
        self.assertEqual(region["mode"], "exclude")
        self.assertEqual(region["frame_start"], 1)
        self.assertEqual(region["frame_end"], 2)
        self.assertEqual(holder["records"][0][0], "region")

    def test_convert_selected_region_mode_records_action(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        region_id = controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[2, 2], [8, 2], [8, 8]],
            }
        )
        holder["selected_region_id"] = region_id

        changed = controller.set_selected_region_mode("exclude")

        self.assertTrue(changed)
        self.assertEqual(controller.seg_state.get_persistent_region(region_id)["mode"], "exclude")
        self.assertEqual(holder["records"][0][0], "region")

    def test_select_drag_moves_region_and_records_action(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller(display_transform=(2.0, 0.0, 0.0))
        region_id = controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[2, 2], [16, 2], [16, 16], [2, 16]],
            }
        )
        mode.set("select")

        controller.on_mouse_down(_Event(18, 18))
        controller.on_mouse_drag(_Event(22, 24))
        changed = controller.on_mouse_up(_Event(22, 24))

        self.assertTrue(changed)
        self.assertEqual(holder["selected_region_id"], region_id)
        moved = controller.seg_state.get_persistent_region(region_id)
        self.assertEqual(moved["polygon"][0], [4.0, 5.0])
        self.assertEqual(holder["records"][0][0], "region")

    def test_select_hit_priority_prefers_point_over_unselected_region_vertex(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.points[0] = [{"x": 2, "y": 2, "label": 1}]
        controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[2, 2], [12, 2], [12, 12], [2, 12]],
            }
        )
        mode.set("select")

        controller.on_mouse_down(_Event(2, 2))

        self.assertEqual(holder["selected_point"], (0, 0))
        self.assertIsNone(holder.get("selected_region_id"))

    def test_select_hit_priority_prefers_box_over_unselected_region_body(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.boxes[0] = [2.0, 2.0, 14.0, 14.0]
        controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[1, 1], [16, 1], [16, 16], [1, 16]],
            }
        )
        mode.set("select")

        controller.on_mouse_down(_Event(8, 8))

        self.assertEqual(holder["selected_point"], (0, "box"))
        self.assertIsNone(holder.get("selected_region_id"))

    def test_selected_region_handle_keeps_priority_over_nearby_point(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.points[0] = [{"x": 2, "y": 2, "label": 1}]
        region_id = controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[2, 2], [12, 2], [12, 12], [2, 12]],
            }
        )
        holder["selected_region_id"] = region_id
        mode.set("select")

        controller.on_mouse_down(_Event(2, 2))

        self.assertEqual(holder["selected_region_id"], region_id)
        self.assertIsNone(holder["selected_point"])

    def test_select_region_edge_inserts_vertex_and_records_single_undo_action(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        region_id = controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[1, 1], [18, 1], [18, 18], [1, 18]],
            }
        )
        mode.set("select")

        controller.on_mouse_down(_Event(10, 1))
        controller.on_mouse_drag(_Event(10, 4))
        changed = controller.on_mouse_up(_Event(10, 4))

        self.assertTrue(changed)
        region = controller.seg_state.get_persistent_region(region_id)
        self.assertEqual(len(region["polygon"]), 5)
        self.assertEqual(holder["records"][0][0], "region")
        self.assertEqual(len(holder["records"]), 1)

    def test_delete_selected_region_removes_region(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        region_id = controller.seg_state.add_persistent_region(
            {
                "id": "region_a",
                "mode": "exclude",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[2, 2], [8, 2], [8, 8]],
            }
        )
        holder["selected_region_id"] = region_id

        changed = controller.delete_selected_point()

        self.assertTrue(changed)
        self.assertEqual(controller.seg_state.persistent_regions, [])
        self.assertIsNone(holder["selected_region_id"])
        self.assertEqual(holder["records"][0][0], "region")

    def test_fill_click_writes_plus_paint_and_records_action(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("fill")

        changed = controller.on_mouse_down(_Event(3, 3))

        self.assertTrue(changed)
        self.assertIn(0, controller.paint_layers)
        self.assertTrue(np.all(controller.paint_layers[0]["plus"][2:8, 2:8]))
        self.assertFalse(np.any(controller.paint_layers[0]["minus"][2:8, 2:8]))
        self.assertEqual(holder["records"][0][0], "paint")
        self.assertEqual(holder["recompute"], 1)

    def test_fill_click_remove_noops_when_no_mask_is_under_click(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("fill_erase")

        changed = controller.on_mouse_down(_Event(3, 3))

        self.assertFalse(changed)
        self.assertNotIn(0, controller.paint_layers)
        self.assertEqual(holder["records"], [])

    def test_fill_click_inside_brushed_outline_uses_paint_as_boundary(self):
        controller, _holder, mode, _lbl, _fill_mode, fill_tolerance = self._make_controller()
        mode.set("fill")
        fill_tolerance.set(64.0)
        plus = np.zeros((20, 20), dtype=bool)
        plus[4:15, 4] = True
        plus[4:15, 14] = True
        plus[4, 4:15] = True
        plus[14, 4:15] = True
        minus = np.zeros((20, 20), dtype=bool)
        controller.seg_state.set_paint_layer(0, plus, minus)

        changed = controller.on_mouse_down(_Event(8, 8))

        self.assertTrue(changed)
        self.assertTrue(np.all(controller.paint_layers[0]["plus"][5:14, 5:14]))
        self.assertFalse(controller.paint_layers[0]["plus"][0, 0])
        self.assertTrue(controller.paint_layers[0]["plus"][4, 4])

    def test_fill_click_inside_mask_hole_prefers_bounded_region_even_when_image_component_is_smaller_elsewhere(self):
        controller, _holder, mode, _lbl, _fill_mode, fill_tolerance = self._make_controller()
        mode.set("fill")
        fill_tolerance.set(64.0)
        mask = np.zeros((20, 20), dtype=bool)
        mask[3:17, 3] = True
        mask[3:17, 16] = True
        mask[3, 3:17] = True
        mask[16, 3:17] = True
        controller.seg_state.set_mask(0, mask)

        changed = controller.on_mouse_down(_Event(10, 10))

        self.assertTrue(changed)
        self.assertTrue(np.all(controller.paint_layers[0]["plus"][4:16, 4:16]))
        self.assertFalse(controller.paint_layers[0]["plus"][0, 0])

    def test_fill_click_prefers_image_component_when_mask_exists_elsewhere(self):
        controller, _holder, mode, _lbl, _fill_mode, fill_tolerance = self._make_controller()
        mode.set("fill")
        fill_tolerance.set(8.0)
        mask = np.zeros((20, 20), dtype=bool)
        mask[15:18, 2:5] = True
        controller.seg_state.set_mask(0, mask)

        changed = controller.on_mouse_down(_Event(3, 3))

        self.assertTrue(changed)
        self.assertTrue(np.all(controller.paint_layers[0]["plus"][2:8, 2:8]))
        self.assertFalse(controller.paint_layers[0]["plus"][0, 0])
        self.assertFalse(controller.paint_layers[0]["plus"][14, 14])

    def test_fill_remove_uses_mask_component_under_click(self):
        controller, _holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("fill_erase")
        mask = np.zeros((20, 20), dtype=bool)
        mask[2:7, 2:7] = True
        mask[12:17, 12:17] = True
        controller.seg_state.set_mask(0, mask)

        changed = controller.on_mouse_down(_Event(3, 3))

        self.assertTrue(changed)
        self.assertTrue(np.all(controller.paint_layers[0]["minus"][2:7, 2:7]))
        self.assertFalse(np.any(controller.paint_layers[0]["minus"][12:17, 12:17]))

    def test_fill_remove_outside_mask_is_noop(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("fill_erase")
        mask = np.zeros((20, 20), dtype=bool)
        mask[2:7, 2:7] = True
        controller.seg_state.set_mask(0, mask)

        changed = controller.on_mouse_down(_Event(12, 12))

        self.assertFalse(changed)
        self.assertNotIn(0, controller.paint_layers)
        self.assertEqual(holder["records"], [])

    def test_fill_click_outside_image_is_ignored(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mode.set("fill")

        changed = controller.on_mouse_down(_Event(50, 50))

        self.assertFalse(changed)
        self.assertNotIn(0, controller.paint_layers)
        self.assertEqual(holder["records"], [])

    def test_fill_holes_fills_internal_hole_only(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mask = np.zeros((20, 20), dtype=bool)
        mask[2:10, 2:10] = True
        mask[5:7, 5:7] = False
        controller.seg_state.set_mask(0, mask)

        changed = controller.fill_current_frame_holes()

        self.assertTrue(changed)
        self.assertTrue(np.all(controller.paint_layers[0]["plus"][5:7, 5:7]))
        self.assertFalse(controller.paint_layers[0]["plus"][1, 1])
        self.assertEqual(holder["records"][0][0], "paint")

    def test_fill_holes_preserves_existing_minus_paint(self):
        controller, _holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        mask = np.zeros((20, 20), dtype=bool)
        mask[2:10, 2:10] = True
        mask[5:7, 5:7] = False
        controller.seg_state.set_mask(0, mask)
        plus = np.zeros((20, 20), dtype=bool)
        minus = np.zeros((20, 20), dtype=bool)
        minus[5, 5] = True
        controller.seg_state.set_paint_layer(0, plus, minus)

        changed = controller.fill_current_frame_holes()

        self.assertTrue(changed)
        self.assertFalse(controller.paint_layers[0]["plus"][5, 5])
        self.assertTrue(controller.paint_layers[0]["minus"][5, 5])
        self.assertTrue(controller.paint_layers[0]["plus"][6, 6])

    def test_fill_holes_noops_without_active_mask(self):
        controller, holder, _mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()

        changed = controller.fill_current_frame_holes()

        self.assertFalse(changed)
        self.assertEqual(holder["records"], [])

    def test_select_point_click_does_not_dirty_project(self):
        controller, holder, mode, _lbl, _fill_mode, _fill_tolerance = self._make_controller()
        controller.points[0] = [{"x": 5, "y": 5, "label": 1}]
        mode.set("select")

        # Simulate clicking the point without dragging it
        controller.on_mouse_down(_Event(5, 5))
        changed = controller.on_mouse_up(_Event(5, 5))

        self.assertFalse(changed)
        self.assertEqual(len(holder["records"]), 0)


if __name__ == "__main__":
    unittest.main()
