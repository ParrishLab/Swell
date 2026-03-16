import copy


class UndoActions:
    def record_action(self, action_type, frame_idx, data_before, data_after):
        action = {
            "type": action_type,
            "frame": frame_idx,
            "before": data_before,
            "after": data_after,
        }
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
        self._apply_state(action["frame"], action["before"], action["type"])
        self.log_info("Undo", f"Applied action: {action['type']}")
        return "break"

    def on_redo(self, event=None):
        if not self.redo_stack:
            self.log_info("Undo", "Nothing to redo.")
            return "break"

        action = self.redo_stack.pop()
        self.undo_stack.append(action)
        self._apply_state(action["frame"], action["after"], action["type"])
        self.log_info("Undo", f"Reapplied action: {action['type']}")
        return "break"

    def _apply_state(self, frame_idx, data, action_type):
        if action_type == "point":
            if data is None:
                self.seg_state.clear_points(frame_idx)
            else:
                self.seg_state.set_points(frame_idx, copy.deepcopy(data))

            if self.model_ready:
                self._update_mask_prediction(frame_idx)
            else:
                self.update_display()

        elif action_type == "paint":
            if data is None:
                self.seg_state.clear_paint_layer(frame_idx)
            else:
                self.seg_state.set_paint_layer(frame_idx, data["plus"].copy(), data["minus"].copy())
            self.update_display()

        self._prune_empty_point_frames()
        self._recompute_slider_jump_markers()

        if self.current_frame_idx != frame_idx:
            self.slider.set(frame_idx)
