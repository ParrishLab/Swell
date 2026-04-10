import copy

import cv2
import numpy as np


class InteractionController:
    def __init__(
        self,
        seg_state,
        points,
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
        canvas_left,
        slider,
        lbl_brush_val,
        get_frame_count,
        get_frame_shape_for_idx,
        get_display_transform,
        update_display,
        draw_paint_preview_segment,
        clear_paint_preview,
        draw_brush_cursor,
        recompute_slider_jump_markers,
        update_mask_prediction,
        get_model_ready,
        record_action,
        prune_empty_point_frames,
    ):
        self.seg_state = seg_state
        self.points = points
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
        self.canvas_left = canvas_left
        self.slider = slider
        self.lbl_brush_val = lbl_brush_val
        self.get_frame_count = get_frame_count
        self.get_frame_shape_for_idx = get_frame_shape_for_idx
        self.get_display_transform = get_display_transform
        self.update_display = update_display
        self.draw_paint_preview_segment = draw_paint_preview_segment
        self.clear_paint_preview = clear_paint_preview
        self.draw_brush_cursor = draw_brush_cursor
        self.recompute_slider_jump_markers = recompute_slider_jump_markers
        self.update_mask_prediction = update_mask_prediction
        self.get_model_ready = get_model_ready
        self.record_action = record_action
        self.prune_empty_point_frames = prune_empty_point_frames
        self._pending_dirty = False

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
        elif mode == "select":
            self._handle_selection(event)
            if idx in self.points:
                self.set_points_snapshot_before(copy.deepcopy(self.points[idx]))
            else:
                self.set_points_snapshot_before(None)
            self.set_is_dragging(True)
        else:
            self.set_is_dragging(True)
            self._handle_tool(event, is_click=True)
            self.set_selected_point(None)
            self.update_display()

    def on_mouse_drag(self, event):
        mode = self.tool_mode.get()
        if mode in ["brush", "eraser", "select"]:
            self._handle_tool(event, is_click=False)

        self.set_last_mouse_x(event.x)
        self.set_last_mouse_y(event.y)

    def on_mouse_up(self, _event):
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

        selected_point = self.get_selected_point()
        if mode == "select" and selected_point:
            idx, _ = selected_point
            if self.get_model_ready():
                self.update_mask_prediction(idx)

            points_before = self.get_points_snapshot_before()
            if points_before is not None:
                data_after = copy.deepcopy(self.points.get(idx))
                if data_after != points_before:
                    self.record_action("point", idx, points_before, data_after)
                    self.seg_state.invalidate_user_frames()
                    self.seg_state.invalidate_final_mask_frames()
                    self._pending_dirty = True

        if mode == "select":
            self.set_points_snapshot_before(None)

        self.recompute_slider_jump_markers()
        self.update_display()
        changed = bool(self._pending_dirty)
        self._pending_dirty = False
        return changed

    def _handle_selection(self, event):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return
        idx = self.get_current_frame_idx()
        new_selection = None
        if idx in self.points:
            orig_h, orig_w = self.get_frame_shape_for_idx(idx)
            ratio, offset_x, offset_y = self.get_display_transform(self.canvas_left, orig_w, orig_h)

            click_x = event.x
            click_y = event.y

            closest_dist = 1000
            found_idx = -1

            for i, pt in enumerate(self.points[idx]):
                cx = int(pt["x"] * ratio + offset_x)
                cy = int(pt["y"] * ratio + offset_y)
                dist = (cx - click_x) ** 2 + (cy - click_y) ** 2
                if dist < 100 and dist < closest_dist:
                    closest_dist = dist
                    found_idx = i

            if found_idx != -1:
                new_selection = (idx, found_idx)

        if self.get_selected_point() != new_selection:
            self.set_selected_point(new_selection)
            self.update_display()

    def delete_selected_point(self, _event=None):
        selected_point = self.get_selected_point()
        if selected_point:
            idx, pt_i = selected_point
            if idx in self.points and pt_i < len(self.points[idx]):
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
        return False

    def _handle_tool(self, event, is_click=False):
        frame_count = int(self.get_frame_count())
        if frame_count <= 0:
            return

        idx = self.get_current_frame_idx()
        mode = self.tool_mode.get()

        orig_h, orig_w = self.get_frame_shape_for_idx(idx)
        ratio, offset_x, offset_y = self.get_display_transform(self.canvas_left, orig_w, orig_h)

        img_x = int((event.x - offset_x) / ratio)
        img_y = int((event.y - offset_y) / ratio)

        if not (0 <= img_x < orig_w and 0 <= img_y < orig_h):
            return

        if mode == "select":
            selected_point = self.get_selected_point()
            if selected_point and self.get_is_dragging():
                s_idx, s_pt_i = selected_point
                if s_idx == idx and idx in self.points and s_pt_i < len(self.points[idx]):
                    self.points[idx][s_pt_i]["x"] = img_x
                    self.points[idx][s_pt_i]["y"] = img_y
                    self.seg_state.invalidate_final_mask_frames()
                    self._pending_dirty = True
                    self.update_display()

        elif mode in ["point_pos", "point_neg"]:
            if is_click:
                data_before = copy.deepcopy(self.points.get(idx))

                label = 1 if mode == "point_pos" else 0
                if idx not in self.points:
                    self.points[idx] = []
                self.points[idx].append({"x": img_x, "y": img_y, "label": label})
                self.seg_state.invalidate_user_frames()
                self.seg_state.invalidate_final_mask_frames()

                data_after = copy.deepcopy(self.points.get(idx))
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

    def clear_current_frame_data(self):
        idx = self.get_current_frame_idx()
        had_points = bool(idx in self.points and self.points[idx])
        had_mask = bool(idx in self.masks_cache and self.masks_cache[idx] is not None)
        had_paint = bool(idx in self.paint_layers)
        self.seg_state.clear_points(idx)
        self.seg_state.clear_mask(idx)
        self.seg_state.clear_paint_layer(idx)
        self.recompute_slider_jump_markers()
        self.update_display()
        changed = bool(had_points or had_mask or had_paint)
        if changed:
            self._pending_dirty = True
        return changed

    def _preview_paint_segment(self, x0, y0, x1, y1, ratio, offset_x, offset_y, mode):
        radius = max(1.0, float(self.brush_size.get()) * float(ratio))
        start_x = x0 * ratio + offset_x
        start_y = y0 * ratio + offset_y
        end_x = x1 * ratio + offset_x
        end_y = y1 * ratio + offset_y
        self.draw_paint_preview_segment(start_x, start_y, end_x, end_y, radius, mode)
