import copy
import numpy as np


class UndoActions:
    def record_action(self, action_type, frame_idx, data_before, data_after, **metadata):
        action = {
            "type": action_type,
            "frame": frame_idx,
            "before": data_before,
            "after": data_after,
        }
        if metadata:
            action.update(dict(metadata))
        self.undo_stack.append(action)
        self.redo_stack.clear()
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def on_undo(self, event=None):
        if not self.undo_stack:
            self.log_info("Undo", "Nothing to undo.")
            return "break"

        action = self.undo_stack.pop()
        self.redo_stack.append(action)
        self._apply_state(action["frame"], action["before"], action["type"], action=action, direction="undo")
        self.log_info("Undo", f"Applied action: {action['type']}")
        return "break"

    def on_redo(self, event=None):
        if not self.redo_stack:
            self.log_info("Undo", "Nothing to redo.")
            return "break"

        action = self.redo_stack.pop()
        self.undo_stack.append(action)
        self._apply_state(action["frame"], action["after"], action["type"], action=action, direction="redo")
        self.log_info("Undo", f"Reapplied action: {action['type']}")
        return "break"

    def _apply_state(self, frame_idx, data, action_type, *, action=None, direction="undo"):
        if action_type == "point":
            restored_mask = False
            if data is None:
                self.seg_state.clear_points(frame_idx)
            else:
                self.seg_state.set_points(frame_idx, copy.deepcopy(data))

            if isinstance(action, dict):
                mask_key = "mask_before" if str(direction) == "undo" else "mask_after"
                if mask_key in action:
                    mask_payload = action.get(mask_key)
                    if mask_payload is None:
                        self.seg_state.clear_mask(frame_idx)
                    else:
                        self.seg_state.set_mask(frame_idx, np.asarray(mask_payload, dtype=bool).copy())
                    restored_mask = True

            if not restored_mask:
                if self.model_ready:
                    self._update_mask_prediction(frame_idx)
                else:
                    self.update_display()
            else:
                self.update_display()

        elif action_type == "paint":
            if data is None:
                self.seg_state.clear_paint_layer(frame_idx)
            else:
                self.seg_state.set_paint_layer(frame_idx, data["plus"].copy(), data["minus"].copy())
            self.update_display()
        elif action_type == "clear_frame":
            payload = dict(data or {})
            points_payload = payload.get("points")
            paint_payload = payload.get("paint")
            mask_payload = payload.get("mask")

            if points_payload:
                self.seg_state.set_points(frame_idx, copy.deepcopy(points_payload))
            else:
                self.seg_state.clear_points(frame_idx)

            if isinstance(paint_payload, dict):
                plus = paint_payload.get("plus")
                minus = paint_payload.get("minus")
                if plus is not None and minus is not None:
                    self.seg_state.set_paint_layer(
                        frame_idx,
                        np.asarray(plus, dtype=bool).copy(),
                        np.asarray(minus, dtype=bool).copy(),
                    )
                else:
                    self.seg_state.clear_paint_layer(frame_idx)
            else:
                self.seg_state.clear_paint_layer(frame_idx)

            if mask_payload is not None:
                self.seg_state.set_mask(frame_idx, np.asarray(mask_payload, dtype=bool).copy())
            else:
                self.seg_state.clear_mask(frame_idx)
            self.update_display()

        self._prune_empty_point_frames()
        self._recompute_slider_jump_markers()

        if self.current_frame_idx != frame_idx:
            self.slider.set(frame_idx)
