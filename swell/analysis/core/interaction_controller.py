import copy

import cv2
import numpy as np

from swell.analysis.core.region_tools import is_region_tool_mode, region_mode_from_tool_mode

DEFAULT_FILL_TOLERANCE = 8.0


class InteractionController:
    def __init__(
        self,
        seg_state,
        points,
        boxes,
        paint_layers,
        masks_cache,
        get_current_frame_idx,
        set_selected_point,
        get_selected_point,
        get_is_dragging,
        set_is_dragging,
        get_last_mouse_x,
        set_last_mouse_x,
        set_last_mouse_y,
        get_last_img_x,
        set_last_img_x,
        get_last_img_y,
        set_last_img_y,
        get_points_snapshot_before,
        set_points_snapshot_before,
        get_paint_snapshot_before,
        set_paint_snapshot_before,
        tool_mode,
        brush_size,
        fill_tolerance,
        region_mode,
        region_start_var,
        region_end_var,
        get_selected_region_id,
        set_selected_region_id,
        refresh_region_controls,
        canvas_left,
        slider,
        lbl_brush_val,
        get_frame_count,
        get_frame_shape_for_idx,
        get_visual_frame,
        get_display_transform,
        update_display,
        draw_paint_preview_segment,
        clear_paint_preview,
        draw_box_preview,
        clear_box_preview,
        draw_brush_cursor,
        recompute_slider_jump_markers,
        update_mask_prediction,
        get_model_ready,
        record_action,
        prune_empty_point_frames,
    ):
        self.seg_state = seg_state
        self.points = points
        self.boxes = boxes
        self.paint_layers = paint_layers
        self.masks_cache = masks_cache

        self.get_current_frame_idx = get_current_frame_idx
        self.set_selected_point = set_selected_point
        self.get_selected_point = get_selected_point
        self.get_is_dragging = get_is_dragging
        self.set_is_dragging = set_is_dragging
        self.get_last_mouse_x = get_last_mouse_x
        self.set_last_mouse_x = set_last_mouse_x
        self.set_last_mouse_y = set_last_mouse_y
        self.get_last_img_x = get_last_img_x
        self.set_last_img_x = set_last_img_x
        self.get_last_img_y = get_last_img_y
        self.set_last_img_y = set_last_img_y
        self.get_points_snapshot_before = get_points_snapshot_before
        self.set_points_snapshot_before = set_points_snapshot_before
        self.get_paint_snapshot_before = get_paint_snapshot_before
        self.set_paint_snapshot_before = set_paint_snapshot_before

        self.tool_mode = tool_mode
        self.brush_size = brush_size
        self.fill_tolerance = fill_tolerance
        self.region_mode = region_mode
        self.region_start_var = region_start_var
        self.region_end_var = region_end_var
        self.get_selected_region_id = get_selected_region_id
        self.set_selected_region_id = set_selected_region_id
        self.refresh_region_controls = refresh_region_controls
        self.canvas_left = canvas_left
        self.slider = slider
        self.lbl_brush_val = lbl_brush_val
        self.get_frame_count = get_frame_count
        self.get_frame_shape_for_idx = get_frame_shape_for_idx
        self.get_visual_frame = get_visual_frame
        self.get_display_transform = get_display_transform
        self.update_display = update_display
        self.draw_paint_preview_segment = draw_paint_preview_segment
        self.clear_paint_preview = clear_paint_preview
        self.draw_box_preview = draw_box_preview
        self.clear_box_preview = clear_box_preview
        self.draw_brush_cursor = draw_brush_cursor
        self.recompute_slider_jump_markers = recompute_slider_jump_markers
        self.update_mask_prediction = update_mask_prediction
        self.get_model_ready = get_model_ready
        self.record_action = record_action
        self.prune_empty_point_frames = prune_empty_point_frames
        self._pending_dirty = False
        self._box_drag_start_img = None
        self._box_drag_start_canvas = None
        self._box_snapshot_before = None
        self._box_drag_original = None
        self._box_drag_handle = None
        self._region_draft_points: list[list[float]] = []
        self._region_draft_closed = False
        self._region_drag_snapshot_before = None
        self._region_drag_record_before = None
        self._region_drag_original = None
        self._region_drag_start_img = None
        self._region_drag_handle = None

    @staticmethod
    def _paint_payloads_equal(before, after) -> bool:
        if before is after:
            return True
        if before is None or after is None:
            return before is None and after is None
        if not isinstance(before, dict) or not isinstance(after, dict):
            return before == after
        before_keys = set(before.keys())
        after_keys = set(after.keys())
        if before_keys != after_keys:
            return False
        for key in before_keys:
            left = before.get(key)
            right = after.get(key)
            if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
                if left is None or right is None:
                    if left is not None or right is not None:
                        return False
                    continue
                if not np.array_equal(np.asarray(left), np.asarray(right)):
                    return False
            elif left != right:
                return False
        return True

    def on_mouse_move(self, event):
        self.set_last_mouse_x(event.x)
        self.set_last_mouse_y(event.y)
        self.draw_brush_cursor()

    def on_mouse_leave(self, _event):
        self.canvas_left.delete("cursor_brush")
        self.canvas_left.config(cursor="arrow")
        self.set_last_mouse_x(None)

    def on_brush_size_change(self, val):
        self.lbl_brush_val.configure(text=f"{int(float(val))} px")

    def on_nav_left(self, _event=None):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return "break"
        current_idx = self.get_current_frame_idx()
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self.slider.set(new_idx)
        return "break"

    def on_nav_right(self, _event=None):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return "break"
        current_idx = self.get_current_frame_idx()
        new_idx = min(frame_count - 1, current_idx + 1)
        if new_idx != current_idx:
            self.slider.set(new_idx)
        return "break"

    def on_mouse_down(self, event):
        mode = self.tool_mode.get()
        idx = self.get_current_frame_idx()
        if mode in ["brush", "eraser"]:
            self.set_is_dragging(True)
            self.clear_paint_preview()
            self.set_last_mouse_x(event.x)
            self.set_last_mouse_y(event.y)
            if idx in self.paint_layers:
                self.set_paint_snapshot_before(
                    {
                        "plus": self.paint_layers[idx]["plus"].copy(),
                        "minus": self.paint_layers[idx]["minus"].copy(),
                    }
                )
            else:
                self.set_paint_snapshot_before(None)
            self._handle_tool(event, is_click=True)
        elif mode in ("fill", "fill_erase"):
            self.set_selected_point(None)
            self.set_selected_region_id(None)
            return bool(self._handle_tool(event, is_click=True))
        elif mode == "box":
            coords = self._canvas_event_to_image(event, clamp=True)
            if coords is None:
                return
            img_x, img_y, _orig_w, _orig_h, _ratio, _offset_x, _offset_y = coords
            self.set_is_dragging(True)
            self.set_selected_point(None)
            self.set_selected_region_id(None)
            self._box_drag_start_img = (img_x, img_y)
            self._box_drag_start_canvas = (event.x, event.y)
            self._box_snapshot_before = copy.deepcopy(self.boxes.get(idx))
            self.clear_box_preview()
            self.draw_box_preview(event.x, event.y, event.x, event.y)
        elif is_region_tool_mode(mode):
            coords = self._canvas_event_to_image(event, clamp=True)
            if coords is None:
                return
            img_x, img_y, _orig_w, _orig_h, _ratio, _offset_x, _offset_y = coords
            self.set_selected_point(None)
            self.set_selected_region_id(None)
            self._region_draft_points.append([float(img_x), float(img_y)])
            self._region_draft_closed = False
            self.refresh_region_controls()
            self.update_display()
        elif mode == "select":
            self._handle_selection(event)
            selected_point = self.get_selected_point()
            selected_region_id = self.get_selected_region_id()
            if selected_region_id:
                coords = self._canvas_event_to_image(event, clamp=True)
                if coords is not None:
                    img_x, img_y, _orig_w, _orig_h, ratio, _offset_x, _offset_y = coords
                    self._start_region_drag(idx, img_x, img_y, ratio)
                self.set_points_snapshot_before(None)
            elif self._is_box_selection(selected_point, idx):
                coords = self._canvas_event_to_image(event, clamp=True)
                if coords is not None:
                    img_x, img_y, _orig_w, _orig_h, ratio, _offset_x, _offset_y = coords
                    self._box_drag_handle = self._box_hit_test(idx, img_x, img_y, ratio)
                    self._box_drag_start_img = (img_x, img_y)
                else:
                    self._box_drag_handle = None
                    self._box_drag_start_img = None
                self._box_snapshot_before = copy.deepcopy(self.boxes.get(idx))
                self._box_drag_original = copy.deepcopy(self.boxes.get(idx))
                self.set_points_snapshot_before(None)
            elif idx in self.points:
                self.set_points_snapshot_before(copy.deepcopy(self.points[idx]))
            else:
                self.set_points_snapshot_before(None)
            self.set_is_dragging(True)
        else:
            self.set_is_dragging(True)
            self._handle_tool(event, is_click=True)
            self.set_selected_point(None)
            self.set_selected_region_id(None)
            self.update_display()

    def on_mouse_drag(self, event):
        mode = self.tool_mode.get()
        if mode in ["brush", "eraser", "select"]:
            self._handle_tool(event, is_click=False)
        elif mode == "box" and self.get_is_dragging() and self._box_drag_start_canvas is not None:
            x0, y0 = self._box_drag_start_canvas
            self.draw_box_preview(x0, y0, event.x, event.y)

        self.set_last_mouse_x(event.x)
        self.set_last_mouse_y(event.y)

    def on_mouse_up(self, event):
        self.set_is_dragging(False)

        mode = self.tool_mode.get()
        idx = self.get_current_frame_idx()
        if mode in ["brush", "eraser"]:
            self.clear_paint_preview()
            paint_before = self.get_paint_snapshot_before()
            data_after = None
            if idx in self.paint_layers:
                data_after = {
                    "plus": self.paint_layers[idx]["plus"].copy(),
                    "minus": self.paint_layers[idx]["minus"].copy(),
                }

            self.record_action("paint", idx, paint_before, data_after)
            self.set_paint_snapshot_before(None)
            self.update_display(update_preview=True)
            self.recompute_slider_jump_markers()
            if not self._paint_payloads_equal(paint_before, data_after):
                self._pending_dirty = True

        if mode == "box":
            self.clear_box_preview()
            before = copy.deepcopy(self._box_snapshot_before)
            start = self._box_drag_start_img
            coords = self._canvas_event_to_image(event, clamp=True)
            self._box_drag_start_img = None
            self._box_drag_start_canvas = None
            self._box_snapshot_before = None
            self._box_drag_original = None
            self._box_drag_handle = None
            if start is not None and coords is not None:
                end_x, end_y, orig_w, orig_h, _ratio, _offset_x, _offset_y = coords
                x0 = max(0.0, min(float(orig_w - 1), float(start[0])))
                y0 = max(0.0, min(float(orig_h - 1), float(start[1])))
                x1 = max(0.0, min(float(orig_w - 1), float(end_x)))
                y1 = max(0.0, min(float(orig_h - 1), float(end_y)))
                normalized = self.seg_state._normalize_box([x0, y0, x1, y1])
                if normalized is not None:
                    self.seg_state.set_box(idx, normalized)
                    after = copy.deepcopy(self.boxes.get(idx))
                    if before != after:
                        self.record_action("box", idx, before, after)
                        self.seg_state.invalidate_user_frames()
                        self.seg_state.invalidate_final_mask_frames()
                        self.recompute_slider_jump_markers()
                        self._pending_dirty = True
                    if self.get_model_ready():
                        self.update_mask_prediction(idx)
                    else:
                        self.update_display()
                else:
                    self.update_display()

        selected_point = self.get_selected_point()
        if mode == "select" and selected_point:
            idx, pt_i = selected_point
            if self.get_model_ready():
                self.update_mask_prediction(idx)

            if pt_i == "box":
                box_before = copy.deepcopy(self._box_snapshot_before)
                box_after = copy.deepcopy(self.boxes.get(idx))
                if box_before != box_after:
                    self.record_action("box", idx, box_before, box_after)
                    self.seg_state.invalidate_user_frames()
                    self.seg_state.invalidate_final_mask_frames()
                    self._pending_dirty = True
            else:
                points_before = self.get_points_snapshot_before()
                if points_before is not None:
                    data_after = copy.deepcopy(self.points.get(idx))
                    if data_after != points_before:
                        self.record_action("point", idx, points_before, data_after)
                        self.seg_state.invalidate_user_frames()
                        self.seg_state.invalidate_final_mask_frames()
                        self._pending_dirty = True

        if mode == "select" and self._region_drag_snapshot_before is not None:
            before = copy.deepcopy(self._region_drag_record_before)
            after = copy.deepcopy(self.seg_state.get_persistent_region(self.get_selected_region_id()))
            if before != after:
                self.record_action("region", idx, before, after)
                self.seg_state.invalidate_final_mask_frames()
                self.refresh_region_controls()
                self._pending_dirty = True

        if mode == "select":
            self.set_points_snapshot_before(None)
            self._box_snapshot_before = None
            self._box_drag_start_img = None
            self._box_drag_original = None
            self._region_drag_snapshot_before = None
            self._region_drag_record_before = None
            self._region_drag_original = None
            self._region_drag_start_img = None
            self._region_drag_handle = None

        self.recompute_slider_jump_markers()
        self.update_display()
        changed = bool(self._pending_dirty)
        self._pending_dirty = False
        return changed

    @staticmethod
    def _is_box_selection(selected_point, idx=None) -> bool:
        if not selected_point:
            return False
        selected_idx, selected_kind = selected_point
        return selected_kind == "box" and (idx is None or selected_idx == idx)

    def _box_handle_points(self, box):
        x0, y0, x1, y1 = (float(v) for v in box)
        mid_x = (x0 + x1) / 2.0
        mid_y = (y0 + y1) / 2.0
        return {
            "nw": (x0, y0),
            "n": (mid_x, y0),
            "ne": (x1, y0),
            "e": (x1, mid_y),
            "se": (x1, y1),
            "s": (mid_x, y1),
            "sw": (x0, y1),
            "w": (x0, mid_y),
        }

    def _box_hit_test(self, idx, img_x, img_y, ratio):
        box = self.boxes.get(idx)
        if box is None:
            return None
        normalized = self.seg_state._normalize_box(box)
        if normalized is None:
            return None
        x0, y0, x1, y1 = normalized
        handle_tolerance = max(3.0, 4.0 / max(float(ratio), 0.001))
        best_handle = None
        best_dist = None
        for handle, (hx, hy) in self._box_handle_points(normalized).items():
            dist = (float(img_x) - hx) ** 2 + (float(img_y) - hy) ** 2
            if dist <= handle_tolerance**2 and (best_dist is None or dist < best_dist):
                best_dist = dist
                best_handle = handle
        if best_handle is not None:
            return best_handle
        tolerance = max(2.0, 6.0 / max(float(ratio), 0.001))
        if (x0 - tolerance) <= img_x <= (x1 + tolerance) and (y0 - tolerance) <= img_y <= (y1 + tolerance):
            return "move"
        return None

    def _find_box_selection(self, idx, img_x, img_y, ratio):
        if self._box_hit_test(idx, img_x, img_y, ratio) is not None:
            return (idx, "box")
        return None

    def _region_snapshot(self):
        return copy.deepcopy(getattr(self.seg_state, "persistent_regions", []))

    def get_region_draft_points(self):
        return copy.deepcopy(self._region_draft_points)

    def is_region_draft_closed(self) -> bool:
        return bool(self._region_draft_closed)

    def cancel_region_draft(self):
        if not self._region_draft_points:
            return False
        self._region_draft_points = []
        self._region_draft_closed = False
        self.refresh_region_controls()
        self.update_display()
        return True

    def close_region_draft(self):
        if len(self._region_draft_points) < 3:
            return False
        self._region_draft_closed = True
        self.refresh_region_controls()
        self.update_display()
        return True

    def _region_frame_range_from_vars(self):
        frame_count = max(0, int(self.get_frame_count()))
        max_idx = max(0, frame_count - 1)
        try:
            start = int(float(self.region_start_var.get())) - 1
        except Exception:
            start = 0
        try:
            end = int(float(self.region_end_var.get())) - 1
        except Exception:
            end = max_idx
        start = max(0, min(max_idx, start))
        end = max(0, min(max_idx, end))
        if end < start:
            start, end = end, start
        return start, end

    def commit_region_draft(self):
        if len(self._region_draft_points) < 3:
            return False
        idx = self.get_current_frame_idx()
        h, w = self.get_frame_shape_for_idx(idx)
        polygon = self.seg_state._normalize_region_polygon(self._region_draft_points)
        if polygon is None:
            return False
        start, end = self._region_frame_range_from_vars()
        mode = self.seg_state._normalize_region_mode(region_mode_from_tool_mode(self.tool_mode.get()) or "include")
        candidate = {
            "mode": mode,
            "enabled": True,
            "visible": True,
            "frame_start": start,
            "frame_end": end,
            "polygon": polygon,
        }
        if self.seg_state.rasterize_persistent_region(candidate, (h, w)) is None:
            return False
        before = self._region_snapshot()
        region_id = self.seg_state.add_persistent_region(candidate)
        self.set_selected_region_id(region_id)
        self._region_draft_points = []
        self._region_draft_closed = False
        after = self._region_snapshot()
        self.record_action("region", idx, before, after)
        self.recompute_slider_jump_markers()
        self.refresh_region_controls()
        self.update_display()
        self._pending_dirty = True
        return True

    def apply_selected_region_options(self):
        region_id = self.get_selected_region_id()
        if not region_id:
            return False
        region = self.seg_state.get_persistent_region(region_id)
        if region is None:
            return False
        before = self._region_snapshot()
        start, end = self._region_frame_range_from_vars()
        patch = {
            "frame_start": start,
            "frame_end": end,
        }
        if not self.seg_state.update_persistent_region(region_id, patch):
            return False
        after = self._region_snapshot()
        if before == after:
            return False
        self.record_action("region", self.get_current_frame_idx(), before, after)
        self.recompute_slider_jump_markers()
        self.refresh_region_controls()
        self.update_display()
        self._pending_dirty = True
        return True

    def set_selected_region_mode(self, mode):
        region_id = self.get_selected_region_id()
        if not region_id:
            return False
        region = self.seg_state.get_persistent_region(region_id)
        if region is None:
            return False
        next_mode = self.seg_state._normalize_region_mode(mode)
        before = copy.deepcopy(region)
        if not self.seg_state.update_persistent_region(region_id, {"mode": next_mode}):
            return False
        after = copy.deepcopy(self.seg_state.get_persistent_region(region_id))
        if before == after:
            return False
        self.record_action("region", self.get_current_frame_idx(), before, after)
        self.recompute_slider_jump_markers()
        self.refresh_region_controls()
        self.update_display()
        self._pending_dirty = True
        return True

    def delete_selected_region(self):
        region_id = self.get_selected_region_id()
        if not region_id:
            return False
        before = self._region_snapshot()
        removed = self.seg_state.delete_persistent_region(region_id)
        if removed is None:
            return False
        self.set_selected_region_id(None)
        after = self._region_snapshot()
        self.record_action("region", self.get_current_frame_idx(), before, after)
        self.recompute_slider_jump_markers()
        self.refresh_region_controls()
        self.update_display()
        self._pending_dirty = True
        return True

    def duplicate_selected_region(self):
        region_id = self.get_selected_region_id()
        region = self.seg_state.get_persistent_region(region_id) if region_id else None
        if region is None:
            return False
        before = self._region_snapshot()
        clone = copy.deepcopy(region)
        clone.pop("id", None)
        new_id = self.seg_state.add_persistent_region(clone)
        self.set_selected_region_id(new_id)
        after = self._region_snapshot()
        self.record_action("region", self.get_current_frame_idx(), before, after)
        self.recompute_slider_jump_markers()
        self.refresh_region_controls()
        self.update_display()
        self._pending_dirty = True
        return True

    def set_region_flag(self, region_id: str, key: str, value: bool):
        if key not in {"enabled", "visible"}:
            return False
        before = copy.deepcopy(self.seg_state.get_persistent_region(region_id))
        if not self.seg_state.update_persistent_region(region_id, {key: bool(value)}):
            return False
        after = copy.deepcopy(self.seg_state.get_persistent_region(region_id))
        if before == after:
            return False
        self.record_action("region", self.get_current_frame_idx(), before, after)
        self.recompute_slider_jump_markers()
        self.refresh_region_controls()
        self.update_display()
        self._pending_dirty = True
        return True

    @staticmethod
    def _point_segment_distance(px, py, ax, ay, bx, by) -> float:
        vx = float(bx) - float(ax)
        vy = float(by) - float(ay)
        wx = float(px) - float(ax)
        wy = float(py) - float(ay)
        denom = vx * vx + vy * vy
        t = 0.0 if denom <= 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
        cx = float(ax) + t * vx
        cy = float(ay) + t * vy
        return float(((float(px) - cx) ** 2 + (float(py) - cy) ** 2) ** 0.5)

    def _region_hit_test(self, idx, img_x, img_y, ratio, *, prefer_region_id=None):
        tolerance = max(4.0, 7.0 / max(float(ratio), 0.001))
        current = list(getattr(self.seg_state, "persistent_regions", []) or [])
        preferred = str(prefer_region_id) if prefer_region_id else None
        ordered = list(reversed(current))
        if preferred:
            ordered = [r for r in ordered if str(r.get("id")) == preferred] + [r for r in ordered if str(r.get("id")) != preferred]
        for region in ordered:
            normalized = self.seg_state._normalize_persistent_region(region)
            if normalized is None or not bool(normalized.get("visible", True)):
                continue
            if not (int(normalized["frame_start"]) <= int(idx) <= int(normalized["frame_end"])):
                continue
            polygon = normalized.get("polygon") or []
            for point_idx, (x, y) in enumerate(polygon):
                if (float(img_x) - float(x)) ** 2 + (float(img_y) - float(y)) ** 2 <= tolerance**2:
                    return str(normalized["id"]), ("vertex", point_idx)
            for point_idx in range(len(polygon)):
                ax, ay = polygon[point_idx]
                bx, by = polygon[(point_idx + 1) % len(polygon)]
                if self._point_segment_distance(img_x, img_y, ax, ay, bx, by) <= tolerance:
                    return str(normalized["id"]), ("edge", point_idx + 1)
            pts = np.asarray(polygon, dtype=np.float32)
            if len(pts) >= 3 and cv2.pointPolygonTest(pts, (float(img_x), float(img_y)), False) >= 0:
                return str(normalized["id"]), ("move", None)
        return None

    def _find_region_selection(self, idx, img_x, img_y, ratio):
        hit = self._region_hit_test(idx, img_x, img_y, ratio)
        if hit is None:
            return None
        region_id, _handle = hit
        return (idx, f"region:{region_id}")

    def _point_hit_test(self, idx, event, ratio, offset_x, offset_y):
        if idx not in self.points:
            return None
        closest_dist = 1000
        found_idx = -1
        click_x = event.x
        click_y = event.y
        for i, pt in enumerate(self.points[idx]):
            cx = int(pt["x"] * ratio + offset_x)
            cy = int(pt["y"] * ratio + offset_y)
            dist = (cx - click_x) ** 2 + (cy - click_y) ** 2
            if dist < 100 and dist < closest_dist:
                closest_dist = dist
                found_idx = i
        if found_idx == -1:
            return None
        return (idx, found_idx)

    def _resolve_select_hit(self, idx, event, img_x, img_y, ratio, offset_x, offset_y):
        selected_point = self.get_selected_point()
        if self._is_box_selection(selected_point, idx) and self._box_hit_test(idx, img_x, img_y, ratio) is not None:
            return "box", (idx, "box")

        selected_region_id = self.get_selected_region_id()
        if selected_region_id:
            hit = self._region_hit_test(idx, img_x, img_y, ratio, prefer_region_id=selected_region_id)
            if hit is not None and str(hit[0]) == str(selected_region_id):
                return "region", str(selected_region_id)

        point_hit = self._point_hit_test(idx, event, ratio, offset_x, offset_y)
        if point_hit is not None:
            return "point", point_hit

        box_hit = self._find_box_selection(idx, img_x, img_y, ratio)
        if box_hit is not None:
            return "box", box_hit

        region_hit = self._find_region_selection(idx, img_x, img_y, ratio)
        if region_hit is not None:
            _s_idx, region_token = region_hit
            return "region", str(region_token).split("region:", 1)[1]

        return None, None

    def _start_region_drag(self, idx, img_x, img_y, ratio):
        hit = self._region_hit_test(idx, img_x, img_y, ratio, prefer_region_id=self.get_selected_region_id())
        if hit is None:
            self._region_drag_handle = None
            return
        region_id, handle = hit
        self.set_selected_region_id(region_id)
        self._region_drag_snapshot_before = self._region_snapshot()
        self._region_drag_record_before = copy.deepcopy(self.seg_state.get_persistent_region(region_id))
        self._region_drag_original = copy.deepcopy(self.seg_state.get_persistent_region(region_id))
        self._region_drag_start_img = (float(img_x), float(img_y))
        self._region_drag_handle = handle

    def _move_selected_region(self, idx, img_x, img_y, orig_w, orig_h):
        region_id = self.get_selected_region_id()
        original = self._region_drag_original
        start = self._region_drag_start_img
        handle = self._region_drag_handle
        if not region_id or original is None or start is None or handle is None:
            return
        polygon = copy.deepcopy(original.get("polygon") or [])
        if len(polygon) < 3:
            return
        if handle[0] == "edge":
            insert_idx = int(handle[1])
            polygon.insert(insert_idx, [float(start[0]), float(start[1])])
            if self.seg_state.update_persistent_region(region_id, {"polygon": polygon}):
                self._region_drag_original = copy.deepcopy(self.seg_state.get_persistent_region(region_id))
                self._region_drag_handle = ("vertex", insert_idx)
                handle = self._region_drag_handle
                original = self._region_drag_original
                self._pending_dirty = True
                self.refresh_region_controls()
            else:
                return
        if handle[0] == "move":
            dx = float(img_x) - float(start[0])
            dy = float(img_y) - float(start[1])
            moved = [[float(x) + dx, float(y) + dy] for x, y in polygon]
            min_x = min(x for x, _y in moved)
            max_x = max(x for x, _y in moved)
            min_y = min(y for _x, y in moved)
            max_y = max(y for _x, y in moved)
            shift_x = 0.0
            shift_y = 0.0
            if min_x < 0:
                shift_x = -min_x
            elif max_x > orig_w - 1:
                shift_x = float(orig_w - 1) - max_x
            if min_y < 0:
                shift_y = -min_y
            elif max_y > orig_h - 1:
                shift_y = float(orig_h - 1) - max_y
            polygon = [[x + shift_x, y + shift_y] for x, y in moved]
        elif handle[0] == "vertex":
            vertex_idx = int(handle[1])
            if not (0 <= vertex_idx < len(polygon)):
                return
            polygon[vertex_idx] = [
                max(0.0, min(float(orig_w - 1), float(img_x))),
                max(0.0, min(float(orig_h - 1), float(img_y))),
            ]
        else:
            return
        if self.seg_state.update_persistent_region(region_id, {"polygon": polygon}):
            self.seg_state.invalidate_final_mask_frames()
            self._pending_dirty = True
            self.update_display()

    def _move_selected_box(self, idx, img_x, img_y, orig_w, orig_h):
        if self._box_drag_start_img is None or self._box_drag_original is None:
            return
        normalized = self.seg_state._normalize_box(self._box_drag_original)
        if normalized is None:
            return
        start_x, start_y = self._box_drag_start_img
        x0, y0, x1, y1 = (float(v) for v in normalized)
        handle = self._box_drag_handle or "move"
        if handle == "move":
            dx = float(img_x) - float(start_x)
            dy = float(img_y) - float(start_y)
            width = x1 - x0
            height = y1 - y0
            new_x0 = x0 + dx
            new_y0 = y0 + dy
            max_x0 = max(0.0, float(orig_w - 1) - width)
            max_y0 = max(0.0, float(orig_h - 1) - height)
            new_x0 = max(0.0, min(max_x0, new_x0))
            new_y0 = max(0.0, min(max_y0, new_y0))
            next_box = [new_x0, new_y0, new_x0 + width, new_y0 + height]
        else:
            next_x0, next_y0, next_x1, next_y1 = x0, y0, x1, y1
            clamped_x = max(0.0, min(float(orig_w - 1), float(img_x)))
            clamped_y = max(0.0, min(float(orig_h - 1), float(img_y)))
            if "w" in handle:
                next_x0 = clamped_x
            if "e" in handle:
                next_x1 = clamped_x
            if "n" in handle:
                next_y0 = clamped_y
            if "s" in handle:
                next_y1 = clamped_y
            next_box = self.seg_state._normalize_box([next_x0, next_y0, next_x1, next_y1])
            if next_box is None:
                return
        self.seg_state.set_box(idx, next_box)
        self.seg_state.invalidate_final_mask_frames()
        self._pending_dirty = True
        self.update_display()

    def _canvas_event_to_image(self, event, *, clamp: bool = False):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return None
        idx = self.get_current_frame_idx()
        orig_h, orig_w = self.get_frame_shape_for_idx(idx)
        ratio, offset_x, offset_y = self.get_display_transform(self.canvas_left, orig_w, orig_h)
        if ratio <= 0:
            return None
        img_x = int((event.x - offset_x) / ratio)
        img_y = int((event.y - offset_y) / ratio)
        if bool(clamp):
            img_x = max(0, min(orig_w - 1, img_x))
            img_y = max(0, min(orig_h - 1, img_y))
        if not (0 <= img_x < orig_w and 0 <= img_y < orig_h):
            return None
        return img_x, img_y, orig_w, orig_h, ratio, offset_x, offset_y

    def _handle_selection(self, event):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return
        idx = self.get_current_frame_idx()
        coords = self._canvas_event_to_image(event, clamp=False)
        if coords is None:
            if self.get_selected_point() is not None:
                self.set_selected_point(None)
                self.update_display()
            return
        img_x, img_y, orig_w, orig_h, ratio, offset_x, offset_y = coords
        hit_kind, hit_value = self._resolve_select_hit(idx, event, img_x, img_y, ratio, offset_x, offset_y)

        if hit_kind == "region":
            new_region_id = str(hit_value)
            if self.get_selected_point() is not None:
                self.set_selected_point(None)
            if self.get_selected_region_id() != new_region_id:
                self.set_selected_region_id(new_region_id)
                self.refresh_region_controls()
            self.update_display()
            return

        new_selection = hit_value if hit_kind in {"point", "box"} else None
        if new_selection is not None:
            self.set_selected_region_id(None)
            self.refresh_region_controls()
        elif self.get_selected_region_id() is not None:
            self.set_selected_region_id(None)
            self.refresh_region_controls()

        if self.get_selected_point() != new_selection:
            self.set_selected_point(new_selection)
            self.update_display()

    def delete_selected_point(self, _event=None):
        selected_point = self.get_selected_point()
        if selected_point:
            idx, pt_i = selected_point
            if pt_i == "box" and idx in self.boxes:
                data_before = copy.deepcopy(self.boxes.get(idx))
                self.seg_state.clear_box(idx)
                self.set_selected_point(None)
                self.record_action("box", idx, data_before, None)
                self.seg_state.invalidate_user_frames()
                self.seg_state.invalidate_final_mask_frames()

                if self.get_model_ready():
                    self.update_mask_prediction(idx)
                else:
                    self.update_display()
                self.recompute_slider_jump_markers()
                self._pending_dirty = True
                return True

            if isinstance(pt_i, int) and idx in self.points and pt_i < len(self.points[idx]):
                data_before = copy.deepcopy(self.points[idx])

                del self.points[idx][pt_i]
                self.set_selected_point(None)

                data_after = copy.deepcopy(self.points.get(idx))
                if not self.points[idx]:
                    del self.points[idx]
                    data_after = None

                self.record_action("point", idx, data_before, data_after)
                self.prune_empty_point_frames()
                self.seg_state.invalidate_user_frames()
                self.seg_state.invalidate_final_mask_frames()

                if self.get_model_ready():
                    self.update_mask_prediction(idx)
                else:
                    self.update_display()
                self.recompute_slider_jump_markers()
                self._pending_dirty = True
                return True
        if self.get_selected_region_id():
            return self.delete_selected_region()
        return False

    def _handle_tool(self, event, is_click=False):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return

        idx = self.get_current_frame_idx()
        mode = self.tool_mode.get()
        
        # Modifier inversion (Shift: 1, Alt/Option: 8 or 16)
        has_modifier = bool(getattr(event, "state", 0) & 0x0019)
        if has_modifier:
            if mode == "point_pos":
                mode = "point_neg"
            elif mode == "point_neg":
                mode = "point_pos"
            elif mode == "brush":
                mode = "eraser"
            elif mode == "eraser":
                mode = "brush"

        coords = self._canvas_event_to_image(event, clamp=(mode == "select"))
        if coords is None:
            return
        img_x, img_y, orig_w, orig_h, ratio, offset_x, offset_y = coords

        if mode == "select":
            selected_region_id = self.get_selected_region_id()
            if selected_region_id and self.get_is_dragging():
                self._move_selected_region(idx, img_x, img_y, orig_w, orig_h)
                return False
            selected_point = self.get_selected_point()
            if selected_point and self.get_is_dragging():
                s_idx, s_pt_i = selected_point
                if s_idx == idx and s_pt_i == "box":
                    self._move_selected_box(idx, img_x, img_y, orig_w, orig_h)
                elif s_idx == idx and isinstance(s_pt_i, int) and idx in self.points and s_pt_i < len(self.points[idx]):
                    self.points[idx][s_pt_i]["x"] = img_x
                    self.points[idx][s_pt_i]["y"] = img_y
                    self.seg_state.invalidate_final_mask_frames()
                    self._pending_dirty = True
                    self.update_display()

        elif mode in ["point_pos", "point_neg"]:
            if is_click:
                data_before = copy.deepcopy(self.points.get(idx))
                mask_before = None
                if data_before is None and idx in self.masks_cache and self.masks_cache[idx] is not None:
                    mask_before = np.asarray(self.masks_cache[idx], dtype=bool).copy()

                label = 1 if mode == "point_pos" else 0
                if idx not in self.points:
                    self.points[idx] = []
                self.points[idx].append({"x": img_x, "y": img_y, "label": label})
                self.seg_state.invalidate_user_frames()
                self.seg_state.invalidate_final_mask_frames()

                data_after = copy.deepcopy(self.points.get(idx))
                if mask_before is not None:
                    self.record_action("point", idx, data_before, data_after, mask_before=mask_before)
                else:
                    self.record_action("point", idx, data_before, data_after)
                self.recompute_slider_jump_markers()
                self._pending_dirty = True

                if self.get_model_ready():
                    self.update_mask_prediction(idx)
                else:
                    self.update_display()

        elif mode in ["brush", "eraser"]:
            if is_click:
                self._apply_paint(idx, img_x, img_y, mode, orig_w, orig_h)
                self._preview_paint_segment(img_x, img_y, img_x, img_y, ratio, offset_x, offset_y, mode)
                self.set_last_img_x(img_x)
                self.set_last_img_y(img_y)
            else:
                last_img_x = self.get_last_img_x()
                last_img_y = self.get_last_img_y()
                if last_img_x is not None and last_img_y is not None:
                    self._apply_paint_line(idx, last_img_x, last_img_y, img_x, img_y, mode, orig_w, orig_h)
                    self._preview_paint_segment(last_img_x, last_img_y, img_x, img_y, ratio, offset_x, offset_y, mode)
                else:
                    self._apply_paint(idx, img_x, img_y, mode, orig_w, orig_h)
                    self._preview_paint_segment(img_x, img_y, img_x, img_y, ratio, offset_x, offset_y, mode)

                self.set_last_img_x(img_x)
                self.set_last_img_y(img_y)

            self.draw_brush_cursor()

        elif mode in ("fill", "fill_erase"):
            if is_click:
                return self._apply_bucket_fill(idx, img_x, img_y, orig_w, orig_h)
        return False

    def _apply_paint_line(self, frame_idx, x0, y0, x1, y1, mode, w, h):
        if frame_idx not in self.paint_layers:
            self.paint_layers[frame_idx] = {
                "plus": np.zeros((h, w), dtype=bool),
                "minus": np.zeros((h, w), dtype=bool),
            }

        radius = int(self.brush_size.get())
        thickness = radius * 2

        temp_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.line(temp_mask, (x0, y0), (x1, y1), 1, thickness)
        cv2.circle(temp_mask, (x0, y0), radius, 1, -1)
        cv2.circle(temp_mask, (x1, y1), radius, 1, -1)

        mask_bool = temp_mask > 0

        if mode == "brush":
            self.paint_layers[frame_idx]["plus"][mask_bool] = True
            self.paint_layers[frame_idx]["minus"][mask_bool] = False
        else:
            self.paint_layers[frame_idx]["minus"][mask_bool] = True
            self.paint_layers[frame_idx]["plus"][mask_bool] = False
        self.seg_state.invalidate_user_frames()
        self.seg_state.invalidate_final_mask_frames()

    def _apply_paint(self, frame_idx, x, y, mode, w, h):
        if frame_idx not in self.paint_layers:
            self.paint_layers[frame_idx] = {
                "plus": np.zeros((h, w), dtype=bool),
                "minus": np.zeros((h, w), dtype=bool),
            }

        radius = int(self.brush_size.get())
        temp_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(temp_mask, (x, y), radius, 1, -1)
        mask_bool = temp_mask > 0

        if mode == "brush":
            self.paint_layers[frame_idx]["plus"][mask_bool] = True
            self.paint_layers[frame_idx]["minus"][mask_bool] = False
        else:
            self.paint_layers[frame_idx]["minus"][mask_bool] = True
            self.paint_layers[frame_idx]["plus"][mask_bool] = False
        self.seg_state.invalidate_user_frames()
        self.seg_state.invalidate_final_mask_frames()

    def _paint_layer_snapshot(self, frame_idx):
        if frame_idx not in self.paint_layers:
            return None
        layer = self.paint_layers[frame_idx]
        plus = layer.get("plus")
        minus = layer.get("minus")
        if plus is None or minus is None:
            return None
        return {
            "plus": np.asarray(plus, dtype=bool).copy(),
            "minus": np.asarray(minus, dtype=bool).copy(),
        }

    def _ensure_paint_layer(self, frame_idx, w, h):
        layer = self.paint_layers.get(frame_idx)
        expected = (int(h), int(w))
        if not isinstance(layer, dict):
            layer = None
        plus = None if layer is None else self.seg_state._coerce_mask_to_shape(layer.get("plus"), expected)
        minus = None if layer is None else self.seg_state._coerce_mask_to_shape(layer.get("minus"), expected)
        if plus is None or minus is None:
            plus = np.zeros(expected, dtype=bool)
            minus = np.zeros(expected, dtype=bool)
            self.paint_layers[frame_idx] = {"plus": plus, "minus": minus}
        return self.paint_layers[frame_idx]

    def _record_paint_change(self, frame_idx, before, after) -> bool:
        if self._paint_payloads_equal(before, after):
            return False
        self.record_action("paint", frame_idx, before, after)
        self.seg_state.invalidate_user_frames()
        self.seg_state.invalidate_final_mask_frames()
        self.recompute_slider_jump_markers()
        return True

    @staticmethod
    def _connected_flood_region(image, seed_x: int, seed_y: int, tolerance: float) -> np.ndarray | None:
        arr = np.asarray(image)
        if arr.ndim < 2:
            return None
        h, w = arr.shape[:2]
        if not (0 <= int(seed_x) < w and 0 <= int(seed_y) < h):
            return None
        tol = max(0.0, float(tolerance))
        if arr.ndim == 2:
            work = arr.astype(np.float32, copy=False)
            seed = float(work[int(seed_y), int(seed_x)])
            candidate = np.abs(work - seed) <= tol
        else:
            work = arr[..., :3].astype(np.float32, copy=False)
            seed = work[int(seed_y), int(seed_x)]
            candidate = np.max(np.abs(work - seed), axis=2) <= tol
        return InteractionController._connected_component_region(candidate, int(seed_x), int(seed_y))

    @staticmethod
    def _connected_component_region(candidate: np.ndarray, seed_x: int, seed_y: int) -> np.ndarray | None:
        arr = np.asarray(candidate, dtype=bool)
        if arr.ndim != 2:
            return None
        h, w = arr.shape
        if not (0 <= int(seed_x) < w and 0 <= int(seed_y) < h):
            return None
        if not bool(arr[int(seed_y), int(seed_x)]):
            return None
        labels_count, labels = cv2.connectedComponents(arr.astype(np.uint8), connectivity=4)
        if labels_count <= 1:
            return np.zeros((h, w), dtype=bool)
        seed_label = int(labels[int(seed_y), int(seed_x)])
        if seed_label <= 0:
            return np.zeros((h, w), dtype=bool)
        return labels == seed_label

    def _mask_bounded_fill_region(self, frame_idx, img_x, img_y, w, h, mode: str) -> np.ndarray | None:
        final_mask = self.seg_state.compose_final_mask(frame_idx, (h, w))
        if final_mask is None:
            return None
        mask = np.asarray(final_mask, dtype=bool)
        if mask.shape != (int(h), int(w)) or not np.any(mask):
            return None
        if str(mode) == "remove":
            candidate = mask
        else:
            candidate = ~mask
        return self._connected_component_region(candidate, int(img_x), int(img_y))

    def _bounded_empty_mask_fill_region(self, frame_idx, img_x, img_y, w, h) -> np.ndarray | None:
        region = self._mask_bounded_fill_region(frame_idx, img_x, img_y, w, h, "add")
        if region is None or not np.any(region):
            return None
        if self._region_touches_border(region):
            return None
        return region

    @staticmethod
    def _region_touches_border(region: np.ndarray) -> bool:
        arr = np.asarray(region, dtype=bool)
        if arr.ndim != 2 or arr.size == 0:
            return False
        return bool(np.any(arr[0, :]) or np.any(arr[-1, :]) or np.any(arr[:, 0]) or np.any(arr[:, -1]))

    def _image_bucket_fill_region(self, frame_idx, img_x, img_y, w, h) -> np.ndarray | None:
        visual = self.get_visual_frame(frame_idx)
        if visual is None:
            return None
        visual_arr = np.asarray(visual)
        if visual_arr.shape[:2] != (int(h), int(w)):
            return None

        try:
            tolerance = float(self.fill_tolerance.get())
        except Exception:
            tolerance = DEFAULT_FILL_TOLERANCE
        return self._connected_flood_region(visual_arr, int(img_x), int(img_y), tolerance)

    def _apply_bucket_fill(self, frame_idx, img_x, img_y, w, h):
        # Add vs. remove is derived from the active tool (Fill (+) / Fill (-)),
        # mirroring how brush and eraser are distinct tools.
        mode = "remove" if str(self.tool_mode.get()) == "fill_erase" else "add"
        if mode == "remove":
            region = self._mask_bounded_fill_region(frame_idx, img_x, img_y, w, h, mode)
        else:
            region = self._bounded_empty_mask_fill_region(frame_idx, img_x, img_y, w, h)
            if region is None:
                region = self._image_bucket_fill_region(frame_idx, img_x, img_y, w, h)
        if region is None or not np.any(region):
            return False

        before = self._paint_layer_snapshot(frame_idx)
        layer = self._ensure_paint_layer(frame_idx, w, h)
        if mode == "remove":
            layer["minus"][region] = True
            layer["plus"][region] = False
        else:
            layer["plus"][region] = True
            layer["minus"][region] = False
        after = self._paint_layer_snapshot(frame_idx)
        changed = self._record_paint_change(frame_idx, before, after)
        if changed:
            self.update_display(update_preview=True)
        return changed

    @staticmethod
    def _fill_holes(mask: np.ndarray) -> np.ndarray:
        mask_bool = np.asarray(mask, dtype=bool)
        try:
            from scipy import ndimage

            return np.asarray(ndimage.binary_fill_holes(mask_bool), dtype=bool)
        except Exception:
            padded = np.pad(mask_bool.astype(np.uint8), 1, constant_values=0)
            flood = padded.copy()
            h, w = flood.shape
            cv2.floodFill(flood, np.zeros((h + 2, w + 2), dtype=np.uint8), (0, 0), 1)
            background = flood[1:-1, 1:-1].astype(bool) & ~mask_bool
            holes = ~mask_bool & ~background
            return mask_bool | holes

    def fill_current_frame_holes(self):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return False
        idx = self.get_current_frame_idx()
        h, w = self.get_frame_shape_for_idx(idx)
        final_mask = self.seg_state.compose_final_mask(idx, (h, w))
        if final_mask is None or not np.any(final_mask):
            return False
        filled = self._fill_holes(final_mask)
        holes = np.asarray(filled, dtype=bool) & ~np.asarray(final_mask, dtype=bool)
        if not np.any(holes):
            return False

        before = self._paint_layer_snapshot(idx)
        layer = self._ensure_paint_layer(idx, w, h)
        holes = holes & ~np.asarray(layer["minus"], dtype=bool)
        if not np.any(holes):
            return False
        layer["plus"][holes] = True
        after = self._paint_layer_snapshot(idx)
        changed = self._record_paint_change(idx, before, after)
        if changed:
            self.update_display(update_preview=True)
        return changed

    def clear_current_frame_data(self):
        idx = self.get_current_frame_idx()
        frame_before = self._snapshot_frame_state(idx)
        had_points = bool(idx in self.points and self.points[idx])
        had_box = bool(idx in self.boxes)
        had_mask = bool(idx in self.masks_cache and self.masks_cache[idx] is not None)
        had_paint = bool(idx in self.paint_layers)
        self.seg_state.clear_points(idx)
        self.seg_state.clear_box(idx)
        self.seg_state.clear_mask(idx)
        self.seg_state.clear_paint_layer(idx)
        frame_after = self._snapshot_frame_state(idx)
        self.recompute_slider_jump_markers()
        self.update_display()
        changed = bool(had_points or had_box or had_mask or had_paint)
        if changed:
            self.record_action("clear_frame", idx, frame_before, frame_after)
            self._pending_dirty = True
        return changed

    def _snapshot_frame_state(self, frame_idx):
        points_payload = copy.deepcopy(self.points.get(frame_idx))
        box_payload = copy.deepcopy(self.boxes.get(frame_idx))
        paint_payload = None
        layer = self.paint_layers.get(frame_idx)
        if isinstance(layer, dict):
            plus = layer.get("plus")
            minus = layer.get("minus")
            if plus is not None and minus is not None:
                paint_payload = {
                    "plus": np.asarray(plus, dtype=bool).copy(),
                    "minus": np.asarray(minus, dtype=bool).copy(),
                }
        mask_payload = None
        if frame_idx in self.masks_cache and self.masks_cache[frame_idx] is not None:
            mask_payload = np.asarray(self.masks_cache[frame_idx], dtype=bool).copy()
        return {
            "points": points_payload,
            "box": box_payload,
            "paint": paint_payload,
            "mask": mask_payload,
        }

    def _preview_paint_segment(self, x0, y0, x1, y1, ratio, offset_x, offset_y, mode):
        radius = max(1.0, float(self.brush_size.get()) * float(ratio))
        start_x = x0 * ratio + offset_x
        start_y = y0 * ratio + offset_y
        end_x = x1 * ratio + offset_x
        end_y = y1 * ratio + offset_y
        self.draw_paint_preview_segment(start_x, start_y, end_x, end_y, radius, mode)
