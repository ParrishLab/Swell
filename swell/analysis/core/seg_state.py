from __future__ import annotations

import uuid
from typing import Optional

import cv2
import numpy as np


class SegmentationState:
    def __init__(self):
        self.points: dict[int, list[dict]] = {}
        self.boxes: dict[int, list[float]] = {}
        self.paint_layers: dict[int, dict[str, np.ndarray]] = {}
        self.masks_cache: dict[int, np.ndarray] = {}
        self.ground_truth_frames: set[int] = set()
        self.persistent_regions: list[dict] = []
        self._region_raster_cache: dict[tuple, np.ndarray] = {}
        self.leverage_cache: dict[int, float] = {}
        self.leverage_suggested_frame: int | None = None

        self.frames_with_valid_points: set[int] = set()
        self.frames_with_valid_boxes: set[int] = set()
        self.frames_with_user_input: set[int] = set()
        self.frames_with_nonempty_final_mask: set[int] = set()
        self._final_mask_frames_scope: tuple[int, tuple[int, int]] | None = None
        self.frames_with_nonempty_mask_no_regions: set[int] = set()
        self._mask_frames_no_regions_scope: tuple[int, tuple[int, int]] | None = None

        self.dirty_valid_point_frames = True
        self.dirty_valid_box_frames = True
        self.dirty_user_frames = True
        self.dirty_final_mask_frames = True
        self.dirty_mask_frames_no_regions = True

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

    @staticmethod
    def _normalize_box(box) -> list[float] | None:
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return None
        try:
            x0, y0, x1, y1 = (float(v) for v in box)
        except (TypeError, ValueError):
            return None
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if (right - left) < 2.0 or (bottom - top) < 2.0:
            return None
        return [left, top, right, bottom]

    def _has_valid_box_for_frame(self, frame_idx: int) -> bool:
        return self._normalize_box(self.boxes.get(frame_idx)) is not None

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
        self.dirty_valid_box_frames = True
        self.dirty_user_frames = True

    def invalidate_final_mask_frames(self):
        self.dirty_final_mask_frames = True
        self._final_mask_frames_scope = None
        self.dirty_mask_frames_no_regions = True
        self._mask_frames_no_regions_scope = None

    def _mark_user_changed(self):
        self.dirty_valid_point_frames = True
        self.dirty_valid_box_frames = True
        self.dirty_user_frames = True
        self.invalidate_final_mask_frames()

    def set_points(self, frame_idx: int, points_list: list[dict]):
        if points_list:
            self.points[int(frame_idx)] = points_list
        else:
            self.points.pop(int(frame_idx), None)
        self._mark_user_changed()

    def clear_points(self, frame_idx: int):
        self.points.pop(int(frame_idx), None)
        self._mark_user_changed()

    def set_box(self, frame_idx: int, box):
        normalized = self._normalize_box(box)
        idx = int(frame_idx)
        if normalized is None:
            self.boxes.pop(idx, None)
        else:
            self.boxes[idx] = normalized
        self._mark_user_changed()

    def clear_box(self, frame_idx: int):
        self.boxes.pop(int(frame_idx), None)
        self._mark_user_changed()

    def set_paint_layer(self, frame_idx: int, plus: np.ndarray, minus: np.ndarray):
        self.paint_layers[int(frame_idx)] = {"plus": plus, "minus": minus}
        self._mark_user_changed()

    def clear_paint_layer(self, frame_idx: int):
        self.paint_layers.pop(int(frame_idx), None)
        self._mark_user_changed()

    def set_mask(self, frame_idx: int, mask: np.ndarray):
        self.masks_cache[int(frame_idx)] = mask
        self.invalidate_final_mask_frames()

    def clear_mask(self, frame_idx: int):
        idx = int(frame_idx)
        self.masks_cache.pop(idx, None)
        self.ground_truth_frames.discard(idx)
        self.invalidate_user_frames()
        self.invalidate_final_mask_frames()

    def set_ground_truth(self, frame_idx: int, enabled: bool):
        idx = int(frame_idx)
        before = idx in self.ground_truth_frames
        if enabled:
            self.ground_truth_frames.add(idx)
        else:
            self.ground_truth_frames.discard(idx)
        if before != (idx in self.ground_truth_frames):
            self.invalidate_user_frames()

    def is_ground_truth_frame(self, frame_idx: int) -> bool:
        return int(frame_idx) in self.ground_truth_frames

    def get_ground_truth_frames(self, frame_count: Optional[int] = None) -> set[int]:
        return self._bounded_frame_set(self.ground_truth_frames, frame_count)

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
            self._mark_user_changed()

    def get_valid_point_frames(self) -> set[int]:
        if self.dirty_valid_point_frames:
            self.frames_with_valid_points = {idx for idx in self.points if self._has_valid_points_for_frame(idx)}
            self.dirty_valid_point_frames = False
        return set(self.frames_with_valid_points)

    def get_valid_box_frames(self, frame_count: Optional[int] = None) -> set[int]:
        if self.dirty_valid_box_frames:
            self.frames_with_valid_boxes = {idx for idx in self.boxes if self._has_valid_box_for_frame(idx)}
            self.dirty_valid_box_frames = False
        return self._bounded_frame_set(self.frames_with_valid_boxes, frame_count)

    @staticmethod
    def _bounded_frame_set(frames, frame_count: Optional[int] = None) -> set[int]:
        out = set()
        for value in frames or []:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx < 0:
                continue
            if frame_count is not None and idx >= int(frame_count):
                continue
            out.add(idx)
        return out

    def get_user_frames(self, frame_count: Optional[int] = None) -> set[int]:
        if self.dirty_user_frames:
            frames = set(self.get_valid_point_frames())
            frames.update(self.get_valid_box_frames())
            for frame_idx in self.paint_layers:
                if self.has_nonempty_paint(frame_idx):
                    frames.add(int(frame_idx))
            self.frames_with_user_input = frames
            self.dirty_user_frames = False
        return self._bounded_frame_set(self.frames_with_user_input, frame_count)

    def get_prompt_anchor_frames(self, frame_count: Optional[int] = None) -> set[int]:
        frames = set(self.get_user_frames(frame_count))
        frames.update(self.get_ground_truth_frames(frame_count))
        return self._bounded_frame_set(frames, frame_count)

    def get_timeline_extent_frames(self, frame_count: int, base_shape) -> set[int]:
        return self.get_nonempty_mask_frames_without_regions(frame_count, base_shape)

    def get_exportable_mask_frames(self, frame_count: int, base_shape) -> set[int]:
        return self.get_nonempty_final_mask_frames(frame_count, base_shape)

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

    @staticmethod
    def _shape_hw(base_shape) -> tuple[int, int] | None:
        try:
            h, w = int(base_shape[0]), int(base_shape[1])
        except Exception:
            return None
        if h <= 0 or w <= 0:
            return None
        return h, w

    @staticmethod
    def _normalize_region_mode(mode) -> str:
        return "exclude" if str(mode).lower() == "exclude" else "include"

    @staticmethod
    def _normalize_region_polygon(polygon) -> list[list[float]] | None:
        if not isinstance(polygon, (list, tuple)):
            return None
        out: list[list[float]] = []
        for point in polygon:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                return None
            try:
                x = float(point[0])
                y = float(point[1])
            except (TypeError, ValueError):
                return None
            out.append([x, y])
        if len(out) < 3:
            return None
        area = 0.0
        for idx, (x0, y0) in enumerate(out):
            x1, y1 = out[(idx + 1) % len(out)]
            area += (float(x0) * float(y1)) - (float(x1) * float(y0))
        if abs(area) < 1.0:
            return None
        return out

    def _normalize_persistent_region(self, region) -> dict | None:
        if not isinstance(region, dict):
            return None
        polygon = self._normalize_region_polygon(region.get("polygon"))
        if polygon is None:
            return None
        try:
            start = int(region.get("frame_start", 0))
        except (TypeError, ValueError):
            start = 0
        try:
            end = int(region.get("frame_end", start))
        except (TypeError, ValueError):
            end = start
        start = max(0, start)
        end = max(0, end)
        if end < start:
            start, end = end, start
        return {
            "id": str(region.get("id") or ""),
            "mode": self._normalize_region_mode(region.get("mode", "include")),
            "enabled": bool(region.get("enabled", True)),
            "visible": bool(region.get("visible", True)),
            "frame_start": start,
            "frame_end": end,
            "polygon": polygon,
        }

    def _clear_region_raster_cache(self):
        self._region_raster_cache.clear()

    @staticmethod
    def _region_raster_cache_key(region: dict, shape_hw: tuple[int, int]) -> tuple:
        polygon = tuple((round(float(x), 4), round(float(y), 4)) for x, y in region.get("polygon", []))
        return (
            str(region.get("id") or ""),
            str(region.get("mode") or "include"),
            bool(region.get("enabled", True)),
            int(region.get("frame_start", 0)),
            int(region.get("frame_end", 0)),
            polygon,
            (int(shape_hw[0]), int(shape_hw[1])),
        )

    def add_persistent_region(self, region) -> str:
        candidate = dict(region or {})
        if not candidate.get("id"):
            candidate["id"] = f"region_{uuid.uuid4().hex}"
        normalized = self._normalize_persistent_region(candidate)
        if normalized is None:
            return ""
        self.persistent_regions.append(normalized)
        self._clear_region_raster_cache()
        self.invalidate_final_mask_frames()
        return str(normalized["id"])

    def get_persistent_region(self, region_id) -> dict | None:
        rid = str(region_id)
        for region in self.persistent_regions:
            if str(region.get("id")) == rid:
                return region
        return None

    def update_persistent_region(self, region_id, patch) -> bool:
        rid = str(region_id)
        for i, region in enumerate(list(self.persistent_regions)):
            if str(region.get("id")) != rid:
                continue
            candidate = dict(region)
            candidate.update(dict(patch or {}))
            candidate["id"] = rid
            normalized = self._normalize_persistent_region(candidate)
            if normalized is None:
                return False
            if normalized == region:
                return False
            self.persistent_regions[i] = normalized
            self._clear_region_raster_cache()
            self.invalidate_final_mask_frames()
            return True
        return False

    def delete_persistent_region(self, region_id) -> dict | None:
        rid = str(region_id)
        for i, region in enumerate(list(self.persistent_regions)):
            if str(region.get("id")) == rid:
                removed = self.persistent_regions.pop(i)
                self._clear_region_raster_cache()
                self.invalidate_final_mask_frames()
                return removed
        return None

    def clear_persistent_regions(self):
        if self.persistent_regions:
            self.persistent_regions.clear()
            self._clear_region_raster_cache()
            self.invalidate_final_mask_frames()

    def get_active_persistent_regions(self, frame_idx, base_shape) -> list[dict]:
        shape = self._shape_hw(base_shape)
        if shape is None:
            return []
        idx = int(frame_idx)
        active = []
        for region in list(self.persistent_regions):
            normalized = self._normalize_persistent_region(region)
            if normalized is None:
                continue
            if not bool(normalized.get("enabled", True)):
                continue
            if int(normalized["frame_start"]) <= idx <= int(normalized["frame_end"]):
                active.append(normalized)
        return active

    def rasterize_persistent_region(self, region, base_shape) -> np.ndarray | None:
        shape = self._shape_hw(base_shape)
        if shape is None:
            return None
        normalized = self._normalize_persistent_region(region)
        if normalized is None or not bool(normalized.get("enabled", True)):
            return None
        key = self._region_raster_cache_key(normalized, shape)
        cached = self._region_raster_cache.get(key)
        if cached is not None:
            return cached

        h, w = shape
        pts = []
        for x, y in normalized.get("polygon") or []:
            xi = int(round(max(0.0, min(float(w - 1), float(x)))))
            yi = int(round(max(0.0, min(float(h - 1), float(y)))))
            pts.append([xi, yi])
        if len(pts) < 3:
            return None
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [np.asarray(pts, dtype=np.int32)], 1)
        out = mask.astype(bool)
        if not np.any(out):
            return None
        out.setflags(write=False)
        self._region_raster_cache[key] = out
        return out

    def compose_final_mask(self, frame_idx: int, base_shape, apply_persistent_regions: bool = True) -> np.ndarray | None:
        if frame_idx < 0:
            return None
        expected_shape = self._shape_hw(base_shape)
        if expected_shape is None:
            return None
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

        if apply_persistent_regions:
            # Includes OR straight into final_mask; excludes are deferred so
            # they always win over includes, matching the previous
            # union-then-apply semantics without the two scratch allocations.
            exclude_masks: list[np.ndarray] = []
            for region in self.get_active_persistent_regions(frame_idx, expected_shape):
                region_mask = self.rasterize_persistent_region(region, expected_shape)
                if region_mask is None:
                    continue
                if str(region.get("mode")) == "exclude":
                    exclude_masks.append(region_mask)
                else:
                    final_mask |= region_mask
            for region_mask in exclude_masks:
                final_mask[region_mask] = False

        return final_mask

    def has_nonempty_final_mask(self, frame_idx: int, base_shape, *, apply_persistent_regions: bool = True) -> bool:
        mask = self.compose_final_mask(frame_idx, base_shape, apply_persistent_regions=apply_persistent_regions)
        return bool(mask is not None and np.any(mask))

    @staticmethod
    def _normalize_frame_key(value) -> int | None:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            return None
        return idx

    def _candidate_nonempty_final_mask_frames(self, frame_count: int, *, include_regions: bool) -> set[int]:
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

        if include_regions:
            for region in list(self.persistent_regions):
                normalized = self._normalize_persistent_region(region)
                if normalized is None or not bool(normalized.get("enabled", True)):
                    continue
                start = max(0, int(normalized["frame_start"]))
                end = min(max_idx, int(normalized["frame_end"]))
                if end >= start:
                    candidates.update(range(start, end + 1))

        return candidates

    def get_nonempty_mask_frames_without_regions(self, frame_count: int, base_shape) -> set[int]:
        scope = (int(frame_count), tuple(int(v) for v in base_shape[:2]))
        if self.dirty_mask_frames_no_regions or self._mask_frames_no_regions_scope != scope:
            frames_with_masks = set()
            for frame_idx in self._candidate_nonempty_final_mask_frames(frame_count, include_regions=False):
                if self.has_nonempty_final_mask(frame_idx, base_shape, apply_persistent_regions=False):
                    frames_with_masks.add(frame_idx)
            self.frames_with_nonempty_mask_no_regions = frames_with_masks
            self._mask_frames_no_regions_scope = scope
            self.dirty_mask_frames_no_regions = False
        return set(self.frames_with_nonempty_mask_no_regions)

    def get_nonempty_final_mask_frames(self, frame_count: int, base_shape) -> set[int]:
        scope = (int(frame_count), tuple(int(v) for v in base_shape[:2]))
        if self.dirty_final_mask_frames or self._final_mask_frames_scope != scope:
            frames_with_masks = set()
            for frame_idx in self._candidate_nonempty_final_mask_frames(frame_count, include_regions=True):
                if self.has_nonempty_final_mask(frame_idx, base_shape):
                    frames_with_masks.add(frame_idx)
            self.frames_with_nonempty_final_mask = frames_with_masks
            self._final_mask_frames_scope = scope
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
        frame_ids = sorted(set(self.points.keys()) | set(self.boxes.keys()) | set(self.paint_layers.keys()))
        for frame_idx in frame_ids:
            entry = {}
            if frame_idx in self.points and self.points[frame_idx]:
                entry["points"] = self.points[frame_idx]
            if frame_idx in self.boxes:
                box = self._normalize_box(self.boxes.get(frame_idx))
                if box is not None:
                    entry["box"] = box
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
        regions = []
        for region in list(self.persistent_regions):
            normalized = self._normalize_persistent_region(region)
            if normalized is not None:
                regions.append(normalized)
        return {
            "event_id": str(event_id),
            "frames": frames,
            "ground_truth_frames": sorted(int(i) for i in self.ground_truth_frames if int(i) >= 0),
            "persistent_regions": regions,
        }

    def load_prompts_json(self, payload: dict, base_shape=None):
        self.points.clear()
        self.boxes.clear()
        self.paint_layers.clear()
        self.ground_truth_frames.clear()
        self.persistent_regions.clear()
        self._clear_region_raster_cache()

        frames = payload.get("frames", {})
        for frame_key, frame_payload in frames.items():
            frame_idx = int(frame_key)
            points = frame_payload.get("points")
            if isinstance(points, list) and points:
                self.points[frame_idx] = points

            box = self._normalize_box(frame_payload.get("box"))
            if box is not None:
                self.boxes[frame_idx] = box

            plus_rle = frame_payload.get("paint_plus_rle")
            minus_rle = frame_payload.get("paint_minus_rle")
            if plus_rle is not None or minus_rle is not None:
                plus = self._decode_rle(plus_rle or {}, shape_hint=base_shape)
                minus = self._decode_rle(minus_rle or {}, shape_hint=base_shape)
                self.paint_layers[frame_idx] = {"plus": plus, "minus": minus}

        for value in payload.get("ground_truth_frames", []) or []:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx >= 0:
                self.ground_truth_frames.add(idx)

        for region in payload.get("persistent_regions", []) or []:
            normalized = self._normalize_persistent_region(region)
            if normalized is not None:
                if not normalized.get("id"):
                    normalized["id"] = f"region_{uuid.uuid4().hex}"
                self.persistent_regions.append(normalized)

        self.dirty_valid_point_frames = True
        self.dirty_valid_box_frames = True
        self.dirty_user_frames = True
        self.invalidate_final_mask_frames()
