from __future__ import annotations

from typing import Optional

import numpy as np


class SegmentationState:
    def __init__(self):
        self.points: dict[int, list[dict]] = {}
        self.paint_layers: dict[int, dict[str, np.ndarray]] = {}
        self.masks_cache: dict[int, np.ndarray] = {}
        self.leverage_cache: dict[int, float] = {}
        self.leverage_suggested_frame: int | None = None

        self.frames_with_valid_points: set[int] = set()
        self.frames_with_user_input: set[int] = set()
        self.frames_with_nonempty_final_mask: set[int] = set()

        self.dirty_valid_point_frames = True
        self.dirty_user_frames = True
        self.dirty_final_mask_frames = True

    def _has_valid_points_for_frame(self, frame_idx: int) -> bool:
        pt_list = self.points.get(frame_idx)
        if not isinstance(pt_list, list) or len(pt_list) == 0:
            return False
        for point in pt_list:
            if not isinstance(point, dict):
                return False
            if "x" not in point or "y" not in point or "label" not in point:
                return False
        return True

    def has_nonempty_paint(self, frame_idx: int) -> bool:
        layer = self.paint_layers.get(frame_idx)
        if not isinstance(layer, dict):
            return False
        plus = layer.get("plus")
        minus = layer.get("minus")
        if plus is None or minus is None:
            return False
        try:
            return bool(np.any(plus) or np.any(minus))
        except Exception:
            return False

    def invalidate_user_frames(self):
        self.dirty_valid_point_frames = True
        self.dirty_user_frames = True

    def invalidate_final_mask_frames(self):
        self.dirty_final_mask_frames = True

    def set_points(self, frame_idx: int, points_list: list[dict]):
        if points_list:
            self.points[frame_idx] = points_list
        else:
            self.points.pop(frame_idx, None)
        self.dirty_valid_point_frames = True
        self.dirty_user_frames = True
        self.dirty_final_mask_frames = True

    def clear_points(self, frame_idx: int):
        self.points.pop(frame_idx, None)
        self.dirty_valid_point_frames = True
        self.dirty_user_frames = True
        self.dirty_final_mask_frames = True

    def set_paint_layer(self, frame_idx: int, plus: np.ndarray, minus: np.ndarray):
        self.paint_layers[frame_idx] = {"plus": plus, "minus": minus}
        self.dirty_valid_point_frames = True
        self.dirty_user_frames = True
        self.dirty_final_mask_frames = True

    def clear_paint_layer(self, frame_idx: int):
        self.paint_layers.pop(frame_idx, None)
        self.dirty_valid_point_frames = True
        self.dirty_user_frames = True
        self.dirty_final_mask_frames = True

    def set_mask(self, frame_idx: int, mask: np.ndarray):
        self.masks_cache[frame_idx] = mask
        self.dirty_final_mask_frames = True

    def clear_mask(self, frame_idx: int):
        self.masks_cache.pop(frame_idx, None)
        self.dirty_final_mask_frames = True

    def set_leverage_map(self, leverage: dict[int, float], suggested: int | None):
        self.leverage_cache = dict(leverage)
        self.leverage_suggested_frame = suggested

    def prune_invalid_points(self):
        to_delete = []
        for frame_idx in self.points:
            if not self._has_valid_points_for_frame(frame_idx):
                to_delete.append(frame_idx)
        for frame_idx in to_delete:
            del self.points[frame_idx]
        if to_delete:
            self.dirty_valid_point_frames = True
            self.dirty_user_frames = True
            self.dirty_final_mask_frames = True

    def get_valid_point_frames(self) -> set[int]:
        if self.dirty_valid_point_frames:
            self.frames_with_valid_points = {idx for idx in self.points if self._has_valid_points_for_frame(idx)}
            self.dirty_valid_point_frames = False
        return set(self.frames_with_valid_points)

    def get_user_frames(self, frame_count: Optional[int] = None) -> set[int]:
        if self.dirty_user_frames:
            frames = set(self.get_valid_point_frames())
            for frame_idx in self.paint_layers:
                if self.has_nonempty_paint(frame_idx):
                    frames.add(frame_idx)
            self.frames_with_user_input = frames
            self.dirty_user_frames = False

        if frame_count is None:
            return set(self.frames_with_user_input)
        max_idx = frame_count - 1
        return {idx for idx in self.frames_with_user_input if 0 <= idx <= max_idx}

    @staticmethod
    def _coerce_mask_to_shape(mask, shape_hw: tuple[int, int]) -> np.ndarray | None:
        expected = (int(shape_hw[0]), int(shape_hw[1]))
        try:
            arr = np.asarray(mask, dtype=bool)
        except Exception:
            return None
        if arr.ndim == 2 and arr.shape == expected:
            return arr
        squeezed = np.squeeze(arr)
        if squeezed.ndim == 2 and squeezed.shape == expected:
            return np.asarray(squeezed, dtype=bool)
        return None

    def compose_final_mask(self, frame_idx: int, base_shape) -> np.ndarray | None:
        if frame_idx < 0:
            return None
        h, w = base_shape[:2]
        expected_shape = (int(h), int(w))
        final_mask = np.zeros(expected_shape, dtype=bool)

        if frame_idx in self.masks_cache and self.masks_cache[frame_idx] is not None:
            cached_mask = self._coerce_mask_to_shape(self.masks_cache[frame_idx], expected_shape)
            if cached_mask is not None:
                final_mask = np.asarray(cached_mask, dtype=bool).copy()

        if frame_idx in self.paint_layers:
            layer = self.paint_layers[frame_idx]
            plus = self._coerce_mask_to_shape(layer.get("plus"), expected_shape)
            minus = self._coerce_mask_to_shape(layer.get("minus"), expected_shape)
            if plus is not None and minus is not None:
                final_mask = (final_mask | plus) & ~minus

        return final_mask

    def has_nonempty_final_mask(self, frame_idx: int, base_shape) -> bool:
        mask = self.compose_final_mask(frame_idx, base_shape)
        return bool(mask is not None and np.any(mask))

    @staticmethod
    def _normalize_frame_key(value) -> int | None:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            return None
        return idx

    def _candidate_nonempty_final_mask_frames(self, frame_count: int) -> set[int]:
        candidates: set[int] = set()
        max_idx = int(frame_count) - 1
        if max_idx < 0:
            return candidates

        for key in self.masks_cache.keys():
            idx = self._normalize_frame_key(key)
            if idx is not None and 0 <= idx <= max_idx:
                candidates.add(idx)

        for key in self.paint_layers.keys():
            idx = self._normalize_frame_key(key)
            if idx is not None and 0 <= idx <= max_idx:
                candidates.add(idx)

        return candidates

    def get_nonempty_final_mask_frames(self, frame_count: int, base_shape) -> set[int]:
        if self.dirty_final_mask_frames:
            frames_with_masks = set()
            # Only frames with masks/paint can produce non-empty finals.
            for frame_idx in self._candidate_nonempty_final_mask_frames(frame_count):
                if self.has_nonempty_final_mask(frame_idx, base_shape):
                    frames_with_masks.add(frame_idx)
            self.frames_with_nonempty_final_mask = frames_with_masks
            self.dirty_final_mask_frames = False
        return set(self.frames_with_nonempty_final_mask)

    @staticmethod
    def _encode_rle(mask: np.ndarray) -> dict:
        flat = np.asarray(mask, dtype=np.uint8).ravel()
        if flat.size == 0:
            return {"shape": list(mask.shape), "runs": []}
        runs = []
        start = None
        for i, val in enumerate(flat):
            if val and start is None:
                start = i
            elif (not val) and start is not None:
                runs.append([int(start), int(i - start)])
                start = None
        if start is not None:
            runs.append([int(start), int(flat.size - start)])
        return {"shape": list(mask.shape), "runs": runs}

    @staticmethod
    def _decode_rle(payload: dict, shape_hint=None) -> np.ndarray:
        shape = tuple(payload.get("shape") or shape_hint or ())
        if not shape:
            return np.zeros((0, 0), dtype=bool)
        out = np.zeros(int(np.prod(shape)), dtype=np.uint8)
        for run in payload.get("runs", []):
            if not isinstance(run, list) or len(run) != 2:
                continue
            start, length = int(run[0]), int(run[1])
            end = max(start, start + max(0, length))
            out[start:end] = 1
        return out.reshape(shape).astype(bool)

    def to_prompts_json(self, event_id: str) -> dict:
        frames = {}
        frame_ids = sorted(set(self.points.keys()) | set(self.paint_layers.keys()))
        for frame_idx in frame_ids:
            entry = {}
            if frame_idx in self.points and self.points[frame_idx]:
                entry["points"] = self.points[frame_idx]
            if frame_idx in self.paint_layers:
                layer = self.paint_layers[frame_idx]
                plus = layer.get("plus")
                minus = layer.get("minus")
                if plus is not None:
                    entry["paint_plus_rle"] = self._encode_rle(np.asarray(plus, dtype=bool))
                if minus is not None:
                    entry["paint_minus_rle"] = self._encode_rle(np.asarray(minus, dtype=bool))
            if entry:
                frames[str(int(frame_idx))] = entry
        return {"event_id": str(event_id), "frames": frames}

    def load_prompts_json(self, payload: dict, base_shape=None):
        self.points.clear()
        self.paint_layers.clear()

        frames = payload.get("frames", {})
        for frame_key, frame_payload in frames.items():
            frame_idx = int(frame_key)
            points = frame_payload.get("points")
            if isinstance(points, list) and points:
                self.points[frame_idx] = points

            plus_rle = frame_payload.get("paint_plus_rle")
            minus_rle = frame_payload.get("paint_minus_rle")
            if plus_rle is not None or minus_rle is not None:
                plus = self._decode_rle(plus_rle or {}, shape_hint=base_shape)
                minus = self._decode_rle(minus_rle or {}, shape_hint=base_shape)
                self.paint_layers[frame_idx] = {"plus": plus, "minus": minus}

        self.dirty_valid_point_frames = True
        self.dirty_user_frames = True
        self.dirty_final_mask_frames = True
