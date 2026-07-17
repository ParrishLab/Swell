from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
import math
from typing import Any

import cv2
import numpy as np


@dataclass
class TrackingConfig:
    min_component_area_px: int = 4
    min_persistence_frames: int = 2
    max_centroid_distance_px: float = 12.0
    max_boundary_distance_px: float = 6.0


@dataclass(frozen=True)
class PhysicalTrackingConfig:
    min_component_area_mm2: float = 0.00025
    min_persistence_frames: int = 2
    max_centroid_distance_mm: float = 0.10
    max_boundary_distance_mm: float = 0.05

    def to_pixel_config(self, scale_px_per_mm: float) -> TrackingConfig:
        scale = float(scale_px_per_mm)
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("scale_px_per_mm must be finite and greater than zero")
        return TrackingConfig(
            min_component_area_px=int(math.ceil(float(self.min_component_area_mm2) * scale * scale)),
            min_persistence_frames=int(self.min_persistence_frames),
            max_centroid_distance_px=float(self.max_centroid_distance_mm) * scale,
            max_boundary_distance_px=float(self.max_boundary_distance_mm) * scale,
        )


@dataclass
class ConnectedComponent:
    frame_index: int
    component_id: int
    mask: np.ndarray
    area_px: int
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    contour_xy: np.ndarray | None = None


@dataclass
class TrackFrameAssignment:
    frame_index: int
    component_id: int
    area_px: int
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    mask: np.ndarray


@dataclass
class TrackRecord:
    track_id: int
    parent_track_ids: list[int] = field(default_factory=list)
    child_track_ids: list[int] = field(default_factory=list)
    frame_assignments: list[TrackFrameAssignment] = field(default_factory=list)
    birth_frame: int | None = None
    end_frame: int | None = None
    merge_frame: int | None = None
    merged_into_track_id: int | None = None
    terminal_status: str = "active"
    root_track_id: int | None = None

    @property
    def last_assignment(self) -> TrackFrameAssignment | None:
        if not self.frame_assignments:
            return None
        return self.frame_assignments[-1]


def _extract_components(mask: np.ndarray, frame_index: int) -> list[ConnectedComponent]:
    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2 or not np.any(arr):
        return []
    labels_count, labels, stats, centroids = cv2.connectedComponentsWithStats(arr.astype(np.uint8), connectivity=8)
    out: list[ConnectedComponent] = []
    for label_id in range(1, int(labels_count)):
        area = int(stats[label_id, cv2.CC_STAT_AREA])
        if area <= 0:
            continue
        component_mask = labels == label_id
        contour_xy = None
        contours, _ = cv2.findContours(component_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if contours:
            contour = max(contours, key=cv2.contourArea)
            if contour is not None and len(contour) >= 1:
                contour_xy = contour[:, 0, :].astype(np.float64)
        out.append(
            ConnectedComponent(
                frame_index=int(frame_index),
                component_id=int(label_id),
                mask=np.asarray(component_mask, dtype=bool),
                area_px=int(area),
                centroid_x=float(centroids[label_id][0]),
                centroid_y=float(centroids[label_id][1]),
                bbox_x=int(stats[label_id, cv2.CC_STAT_LEFT]),
                bbox_y=int(stats[label_id, cv2.CC_STAT_TOP]),
                bbox_w=int(stats[label_id, cv2.CC_STAT_WIDTH]),
                bbox_h=int(stats[label_id, cv2.CC_STAT_HEIGHT]),
                contour_xy=contour_xy,
            )
        )
    return out


def _boundary_distance_px(lhs: ConnectedComponent, rhs: ConnectedComponent) -> float:
    left = lhs.contour_xy
    right = rhs.contour_xy
    if left is None and lhs.mask is not None:
        contours, _ = cv2.findContours(np.asarray(lhs.mask, dtype=np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if contours:
            left = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64)
    if right is None and rhs.mask is not None:
        contours, _ = cv2.findContours(np.asarray(rhs.mask, dtype=np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if contours:
            right = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64)
    if left is None or right is None or len(left) == 0 or len(right) == 0:
        return float("inf")
    delta = left[:, None, :] - right[None, :, :]
    dist2 = np.sum(delta * delta, axis=2)
    return float(np.sqrt(float(np.min(dist2)))) if dist2.size else float("inf")


def _component_distance_score(
    prev_component: ConnectedComponent,
    curr_component: ConnectedComponent,
    *,
    config: TrackingConfig,
) -> float | None:
    centroid_distance = float(
        np.hypot(
            float(prev_component.centroid_x) - float(curr_component.centroid_x),
            float(prev_component.centroid_y) - float(curr_component.centroid_y),
        )
    )
    if centroid_distance <= float(config.max_centroid_distance_px):
        return centroid_distance
    boundary_distance = _boundary_distance_px(prev_component, curr_component)
    if boundary_distance <= float(config.max_boundary_distance_px):
        return float(config.max_centroid_distance_px) + boundary_distance
    return None


def _append_assignment(track: TrackRecord, component: ConnectedComponent) -> None:
    track.frame_assignments.append(
        TrackFrameAssignment(
            frame_index=int(component.frame_index),
            component_id=int(component.component_id),
            area_px=int(component.area_px),
            centroid_x=float(component.centroid_x),
            centroid_y=float(component.centroid_y),
            bbox_x=int(component.bbox_x),
            bbox_y=int(component.bbox_y),
            bbox_w=int(component.bbox_w),
            bbox_h=int(component.bbox_h),
            mask=np.asarray(component.mask, dtype=bool).copy(),
        )
    )
    if track.birth_frame is None:
        track.birth_frame = int(component.frame_index)


def _track_persistence_frames(track: TrackRecord) -> int:
    return len(track.frame_assignments)


def _track_max_area_px(track: TrackRecord) -> int:
    if not track.frame_assignments:
        return 0
    return max(int(frame.area_px) for frame in track.frame_assignments)


def _prune_tracks(tracks: dict[int, TrackRecord], *, config: TrackingConfig) -> dict[int, TrackRecord]:
    kept_ids = {
        int(track_id)
        for track_id, track in tracks.items()
        if _track_max_area_px(track) >= int(config.min_component_area_px)
        or _track_persistence_frames(track) >= int(config.min_persistence_frames)
    }
    kept: dict[int, TrackRecord] = {}
    for track_id in sorted(kept_ids):
        track = tracks[int(track_id)]
        kept[int(track_id)] = TrackRecord(
            track_id=int(track.track_id),
            parent_track_ids=[int(v) for v in track.parent_track_ids if int(v) in kept_ids],
            child_track_ids=[int(v) for v in track.child_track_ids if int(v) in kept_ids],
            frame_assignments=list(track.frame_assignments),
            birth_frame=track.birth_frame,
            end_frame=track.end_frame,
            merge_frame=track.merge_frame,
            merged_into_track_id=(int(track.merged_into_track_id) if track.merged_into_track_id in kept_ids else None),
            terminal_status=str(track.terminal_status),
            root_track_id=track.root_track_id,
        )
    return kept


def _assign_root_track_ids(tracks: dict[int, TrackRecord]) -> None:
    adjacency: dict[int, set[int]] = defaultdict(set)
    for track_id, track in tracks.items():
        for parent_id in track.parent_track_ids:
            adjacency[int(track_id)].add(int(parent_id))
            adjacency[int(parent_id)].add(int(track_id))
        for child_id in track.child_track_ids:
            adjacency[int(track_id)].add(int(child_id))
            adjacency[int(child_id)].add(int(track_id))
        adjacency.setdefault(int(track_id), set())
    seen: set[int] = set()
    for track_id in sorted(tracks):
        if int(track_id) in seen:
            continue
        stack = [int(track_id)]
        component: list[int] = []
        while stack:
            current = int(stack.pop())
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            stack.extend(sorted(adjacency.get(current, set()) - seen))
        root_id = min(component) if component else int(track_id)
        for member in component:
            tracks[int(member)].root_track_id = int(root_id)


def build_object_lineage(
    frame_indices: list[int],
    masks: list[np.ndarray],
    *,
    config: TrackingConfig | None = None,
) -> dict[str, Any]:
    cfg = config or TrackingConfig()
    tracks: dict[int, TrackRecord] = {}
    active_track_ids: set[int] = set()
    next_track_id = 1
    components_by_frame: list[list[ConnectedComponent]] = [
        _extract_components(mask, int(frame_idx))
        for frame_idx, mask in zip(list(frame_indices), list(masks))
    ]

    for frame_idx, components in zip(list(frame_indices), components_by_frame):
        prev_track_ids = sorted(active_track_ids)
        overlaps: dict[tuple[int, int], int] = {}
        curr_to_prev: dict[int, list[int]] = defaultdict(list)
        prev_to_curr: dict[int, list[int]] = defaultdict(list)
        for prev_track_id in prev_track_ids:
            prev_track = tracks[int(prev_track_id)]
            prev_frame = prev_track.last_assignment
            if prev_frame is None:
                continue
            prev_mask = np.asarray(prev_frame.mask, dtype=bool)
            for curr_idx, component in enumerate(components):
                overlap = int(np.count_nonzero(prev_mask & np.asarray(component.mask, dtype=bool)))
                if overlap <= 0:
                    continue
                overlaps[(int(prev_track_id), int(curr_idx))] = int(overlap)
                curr_to_prev[int(curr_idx)].append(int(prev_track_id))
                prev_to_curr[int(prev_track_id)].append(int(curr_idx))

        assigned_curr: set[int] = set()
        consumed_prev: set[int] = set()
        next_active_track_ids: set[int] = set()

        for curr_idx in sorted(idx for idx, parents in curr_to_prev.items() if len(set(parents)) > 1):
            parent_ids = sorted(set(curr_to_prev[int(curr_idx)]))
            child_track = TrackRecord(track_id=int(next_track_id), parent_track_ids=[int(v) for v in parent_ids])
            next_track_id += 1
            _append_assignment(child_track, components[int(curr_idx)])
            tracks[int(child_track.track_id)] = child_track
            assigned_curr.add(int(curr_idx))
            next_active_track_ids.add(int(child_track.track_id))
            for parent_id in parent_ids:
                parent_track = tracks[int(parent_id)]
                if int(child_track.track_id) not in parent_track.child_track_ids:
                    parent_track.child_track_ids.append(int(child_track.track_id))
                parent_track.merge_frame = int(frame_idx)
                if parent_track.last_assignment is not None:
                    parent_track.end_frame = int(parent_track.last_assignment.frame_index)
                parent_track.merged_into_track_id = int(child_track.track_id)
                parent_track.terminal_status = "merged"
                consumed_prev.add(int(parent_id))

        direct_candidates: list[tuple[int, int, int]] = []
        for prev_track_id, curr_indices in prev_to_curr.items():
            if int(prev_track_id) in consumed_prev:
                continue
            for curr_idx in curr_indices:
                if int(curr_idx) in assigned_curr:
                    continue
                if len(set(curr_to_prev.get(int(curr_idx), []))) != 1:
                    continue
                direct_candidates.append((int(overlaps[(int(prev_track_id), int(curr_idx))]), int(prev_track_id), int(curr_idx)))
        direct_candidates.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
        for _overlap, prev_track_id, curr_idx in direct_candidates:
            if int(prev_track_id) in consumed_prev or int(curr_idx) in assigned_curr:
                continue
            track = tracks[int(prev_track_id)]
            _append_assignment(track, components[int(curr_idx)])
            assigned_curr.add(int(curr_idx))
            consumed_prev.add(int(prev_track_id))
            next_active_track_ids.add(int(prev_track_id))

        fallback_candidates: list[tuple[float, int, int]] = []
        for prev_track_id in prev_track_ids:
            if int(prev_track_id) in consumed_prev:
                continue
            prev_track = tracks[int(prev_track_id)]
            prev_frame = prev_track.last_assignment
            if prev_frame is None:
                continue
            prev_component = ConnectedComponent(
                frame_index=int(prev_frame.frame_index),
                component_id=int(prev_frame.component_id),
                mask=np.asarray(prev_frame.mask, dtype=bool),
                area_px=int(prev_frame.area_px),
                centroid_x=float(prev_frame.centroid_x),
                centroid_y=float(prev_frame.centroid_y),
                bbox_x=int(prev_frame.bbox_x),
                bbox_y=int(prev_frame.bbox_y),
                bbox_w=int(prev_frame.bbox_w),
                bbox_h=int(prev_frame.bbox_h),
            )
            for curr_idx, component in enumerate(components):
                if int(curr_idx) in assigned_curr:
                    continue
                score = _component_distance_score(prev_component, component, config=cfg)
                if score is None:
                    continue
                fallback_candidates.append((float(score), int(prev_track_id), int(curr_idx)))
        fallback_candidates.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
        for _score, prev_track_id, curr_idx in fallback_candidates:
            if int(prev_track_id) in consumed_prev or int(curr_idx) in assigned_curr:
                continue
            track = tracks[int(prev_track_id)]
            _append_assignment(track, components[int(curr_idx)])
            assigned_curr.add(int(curr_idx))
            consumed_prev.add(int(prev_track_id))
            next_active_track_ids.add(int(prev_track_id))

        for curr_idx, component in enumerate(components):
            if int(curr_idx) in assigned_curr:
                continue
            track = TrackRecord(track_id=int(next_track_id))
            next_track_id += 1
            _append_assignment(track, component)
            tracks[int(track.track_id)] = track
            next_active_track_ids.add(int(track.track_id))

        for prev_track_id in prev_track_ids:
            if int(prev_track_id) in consumed_prev:
                continue
            track = tracks[int(prev_track_id)]
            if track.last_assignment is not None:
                track.end_frame = int(track.last_assignment.frame_index)
            if track.terminal_status == "active":
                track.terminal_status = "ended"

        active_track_ids = set(int(v) for v in next_active_track_ids)

    for track_id in sorted(active_track_ids):
        track = tracks[int(track_id)]
        if track.last_assignment is not None:
            track.end_frame = int(track.last_assignment.frame_index)
        if track.terminal_status == "active":
            track.terminal_status = "active"

    raw_track_count = len(tracks)
    kept_tracks = _prune_tracks(tracks, config=cfg)
    _assign_root_track_ids(kept_tracks)

    object_track_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    track_area_rows: list[dict[str, Any]] = []
    track_relative_rows: list[dict[str, Any]] = []

    for track_id in sorted(kept_tracks):
        track = kept_tracks[int(track_id)]
        for assignment in track.frame_assignments:
            object_track_rows.append(
                {
                    "track_id": int(track.track_id),
                    "root_track_id": int(track.root_track_id or track.track_id),
                    "frame_index": int(assignment.frame_index),
                    "area_px": int(assignment.area_px),
                    "centroid_x": float(assignment.centroid_x),
                    "centroid_y": float(assignment.centroid_y),
                    "bbox_x": int(assignment.bbox_x),
                    "bbox_y": int(assignment.bbox_y),
                    "bbox_w": int(assignment.bbox_w),
                    "bbox_h": int(assignment.bbox_h),
                }
            )
        lineage_rows.append(
            {
                "track_id": int(track.track_id),
                "root_track_id": int(track.root_track_id or track.track_id),
                "parent_track_ids": json_dumps(track.parent_track_ids),
                "child_track_ids": json_dumps(track.child_track_ids),
                "birth_frame": int(track.birth_frame) if track.birth_frame is not None else "",
                "end_frame": int(track.end_frame) if track.end_frame is not None else "",
                "merge_frame": int(track.merge_frame) if track.merge_frame is not None else "",
                "merged_into_track_id": int(track.merged_into_track_id) if track.merged_into_track_id is not None else "",
                "terminal_status": str(track.terminal_status),
                "persistence_frames": int(_track_persistence_frames(track)),
                "max_area_px": int(_track_max_area_px(track)),
            }
        )

    summary = {
        "raw_track_count": int(raw_track_count),
        "kept_track_count": int(len(kept_tracks)),
        "noise_filtered_track_count": int(max(0, raw_track_count - len(kept_tracks))),
        "merge_event_count": int(sum(1 for track in kept_tracks.values() if len(track.parent_track_ids) > 1)),
        "merged_parent_count": int(sum(1 for track in kept_tracks.values() if track.terminal_status == "merged")),
        "active_terminal_count": int(sum(1 for track in kept_tracks.values() if track.terminal_status == "active")),
        "ended_terminal_count": int(sum(1 for track in kept_tracks.values() if track.terminal_status == "ended")),
        "config": {
            "min_component_area_px": int(cfg.min_component_area_px),
            "min_persistence_frames": int(cfg.min_persistence_frames),
            "max_centroid_distance_px": float(cfg.max_centroid_distance_px),
            "max_boundary_distance_px": float(cfg.max_boundary_distance_px),
        },
    }
    return {
        "tracks": kept_tracks,
        "object_track_rows": object_track_rows,
        "lineage_rows": lineage_rows,
        "track_area_rows": track_area_rows,
        "track_relative_rows": track_relative_rows,
        "summary": summary,
    }


def json_dumps(value: Any) -> str:
    return json.dumps(value)
