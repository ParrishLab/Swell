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
        defer_display_until_navigation = bool(getattr(self, "current_frame_idx", frame_idx) != frame_idx)

        def _update_display_if_current_frame():
            if not defer_display_until_navigation:
                self.update_display()

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
                    _update_display_if_current_frame()
            else:
                _update_display_if_current_frame()

        elif action_type == "paint":
            if data is None:
                self.seg_state.clear_paint_layer(frame_idx)
            else:
                self.seg_state.set_paint_layer(frame_idx, data["plus"].copy(), data["minus"].copy())
            _update_display_if_current_frame()
        elif action_type == "box":
            if data is None:
                self.seg_state.clear_box(frame_idx)
            else:
                self.seg_state.set_box(frame_idx, copy.deepcopy(data))
            if self.model_ready:
                self._update_mask_prediction(frame_idx)
            else:
                _update_display_if_current_frame()
        elif action_type == "region":
            if isinstance(data, dict):
                normalized = self.seg_state._normalize_persistent_region(data)
                if normalized is not None:
                    replaced = False
                    for i, region in enumerate(list(self.seg_state.persistent_regions)):
                        if str(region.get("id")) == str(normalized.get("id")):
                            self.seg_state.persistent_regions[i] = normalized
                            replaced = True
                            break
                    if not replaced:
                        self.seg_state.persistent_regions.append(normalized)
                    if hasattr(self.seg_state, "_clear_region_raster_cache"):
                        self.seg_state._clear_region_raster_cache()
            else:
                self.seg_state.persistent_regions.clear()
                for region in list(data or []):
                    normalized = self.seg_state._normalize_persistent_region(region)
                    if normalized is not None:
                        self.seg_state.persistent_regions.append(normalized)
                if hasattr(self.seg_state, "_clear_region_raster_cache"):
                    self.seg_state._clear_region_raster_cache()
            self.seg_state.invalidate_final_mask_frames()
            if hasattr(self, "selected_region_id"):
                valid_ids = {str(r.get("id")) for r in self.seg_state.persistent_regions}
                if getattr(self, "selected_region_id", None) not in valid_ids:
                    self.selected_region_id = None
            if hasattr(self, "_refresh_regions_dock"):
                self._refresh_regions_dock()
            if hasattr(self, "_sync_region_options_from_selection"):
                self._sync_region_options_from_selection()
            _update_display_if_current_frame()
        elif action_type == "ground_truth":
            self.seg_state.set_ground_truth(frame_idx, bool(data))
            if hasattr(self, "_refresh_ground_truth_controls"):
                self._refresh_ground_truth_controls()
            _update_display_if_current_frame()
        elif action_type == "clear_frame":
            payload = dict(data or {})
            points_payload = payload.get("points")
            box_payload = payload.get("box")
            paint_payload = payload.get("paint")
            mask_payload = payload.get("mask")

            if points_payload:
                self.seg_state.set_points(frame_idx, copy.deepcopy(points_payload))
            else:
                self.seg_state.clear_points(frame_idx)

            if box_payload is not None:
                self.seg_state.set_box(frame_idx, copy.deepcopy(box_payload))
            else:
                self.seg_state.clear_box(frame_idx)

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
            _update_display_if_current_frame()

        self._prune_empty_point_frames()
        self._recompute_slider_jump_markers()
        # Edits restored by undo/redo change the composed masks, so the leverage
        # heatmap must be recomputed or it would show stale trouble regions.
        self._schedule_leverage_recompute()

        if self.current_frame_idx != frame_idx:
            self.slider.set(frame_idx)
