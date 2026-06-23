from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from swell.analysis.core.project_fingerprint import compute_file_fingerprint
from swell.analysis.core.project_schema import default_project_state, utc_now_iso
from swell.analysis.core.seg_state import SegmentationState


@dataclass
class EventMetadata:
    event_id: str
    label: str
    start_idx: int
    end_idx: int
    analysis_output_dir: str | None = None
    propagation_completed: bool = True


@dataclass
class EventAnalysisState:
    points: dict[int, list[dict]] = field(default_factory=dict)
    boxes: dict[int, list[float]] = field(default_factory=dict)
    persistent_regions: list[dict] = field(default_factory=list)
    paint_layers: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)
    masks_committed: dict[int, np.ndarray] = field(default_factory=dict)
    masks_draft: dict[int, np.ndarray] | None = None
    use_draft: bool = False
    ground_truth_frames: set[int] = field(default_factory=set)


@dataclass
class EventRecord:
    metadata: EventMetadata
    analysis: EventAnalysisState


@dataclass
class SessionSnapshot:
    frame_count: int
    frame_shape: tuple[int, int]
    current_frame_idx: int
    active_event_id: str
    tool_mode: str
    display_ratio: float
    img_offset_x: int
    img_offset_y: int
    analysis_start: int
    analysis_end: int
    prop_start: int
    prop_end: int
    export_start: int
    export_end: int
    baseline_frame_count: int
    scale_px_per_mm: Any
    scale_points: list
    scale_axis_lock: bool
    scale_image_path: str
    roi_points: list
    roi_polygons: list
    roi_mask: np.ndarray | None
    created_at: str
    current_image_source_paths: list[str]
    event_records: dict[str, EventRecord]


@dataclass
class LoadedSessionActions:
    active_event_id: str
    event_records: dict[str, EventRecord]
    scale_px_per_mm: Any
    scale_points: list
    scale_axis_lock: bool
    scale_image_path: str
    roi_points: list
    roi_polygons: list
    roi_mask: np.ndarray | None
    baseline_frame_count: int


@dataclass
class PropagationTransition:
    event_record: EventRecord
    restored_masks: dict[int, np.ndarray] | None


class ProjectSessionService:
    def copy_points_dict(self, points: dict[int, list[dict]]) -> dict[int, list[dict]]:
        out = {}
        for frame_idx, pt_list in points.items():
            copied = []
            for pt in pt_list:
                copied.append({"x": float(pt["x"]), "y": float(pt["y"]), "label": int(pt["label"])})
            out[int(frame_idx)] = copied
        return out

    def copy_boxes_dict(self, boxes: dict[int, list[float]]) -> dict[int, list[float]]:
        out = {}
        for frame_idx, box in boxes.items():
            normalized = SegmentationState._normalize_box(box)
            if normalized is not None:
                out[int(frame_idx)] = list(normalized)
        return out

    def copy_persistent_regions(self, regions: list[dict]) -> list[dict]:
        tmp = SegmentationState()
        out: list[dict] = []
        seen: set[str] = set()
        for raw in list(regions or []):
            normalized = tmp._normalize_persistent_region(raw)
            if normalized is None:
                continue
            region_id = str(normalized.get("id"))
            if region_id in seen:
                normalized["id"] = tmp._new_region_id()
                region_id = str(normalized["id"])
            seen.add(region_id)
            out.append(normalized)
        return out

    def copy_masks_dict(self, masks: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
        return {int(idx): np.asarray(mask, dtype=bool).copy() for idx, mask in masks.items() if mask is not None}

    def copy_paint_layers(self, layers: dict[int, dict[str, np.ndarray]]) -> dict[int, dict[str, np.ndarray]]:
        out = {}
        for frame_idx, layer in layers.items():
            plus = np.asarray(layer.get("plus"), dtype=bool).copy()
            minus = np.asarray(layer.get("minus"), dtype=bool).copy()
            out[int(frame_idx)] = {"plus": plus, "minus": minus}
        return out

    def apply_paint_to_masks(
        self,
        masks: dict[int, np.ndarray],
        paint_layers: dict[int, dict[str, np.ndarray]],
    ) -> dict[int, np.ndarray]:
        """Return a new masks dict with paint layers merged in (same logic as the renderer)."""
        if not paint_layers:
            return self.copy_masks_dict(masks)
        out = self.copy_masks_dict(masks)
        for frame_idx, layer in paint_layers.items():
            idx = int(frame_idx)
            plus = np.asarray(layer.get("plus"), dtype=bool)
            minus = np.asarray(layer.get("minus"), dtype=bool)
            base = out.get(idx)
            if base is None:
                base = np.zeros_like(plus)
            if base.shape != plus.shape or base.shape != minus.shape:
                continue
            out[idx] = ((base | plus) & ~minus).copy()
        return out

    def event_mask_bounds(self, mask_dict: dict[int, np.ndarray], frame_count: int) -> tuple[int, int]:
        if not mask_dict:
            return 0, max(0, frame_count - 1)
        nonempty = [idx for idx, mask in mask_dict.items() if mask is not None and np.any(mask)]
        if not nonempty:
            return 0, max(0, frame_count - 1)
        return int(min(nonempty)), int(max(nonempty))

    def masks_dict_to_array(self, mask_dict: dict[int, np.ndarray], frame_count: int, shape_hw: tuple[int, int]) -> np.ndarray:
        h, w = int(shape_hw[0]), int(shape_hw[1])
        arr = np.zeros((int(frame_count), h, w), dtype=np.uint8)
        for frame_idx, mask in mask_dict.items():
            idx = int(frame_idx)
            if 0 <= idx < frame_count and mask is not None:
                mask_arr = np.asarray(mask, dtype=np.uint8)
                if tuple(mask_arr.shape) != (h, w):
                    squeezed = np.squeeze(mask_arr)
                    if tuple(squeezed.shape) != (h, w):
                        continue
                    mask_arr = np.asarray(squeezed, dtype=np.uint8)
                arr[idx] = mask_arr
        return arr

    def array_to_masks_dict(self, masks_array, frame_count: int) -> dict[int, np.ndarray]:
        out = {}
        arr = np.asarray(masks_array)
        if arr.ndim != 3 or arr.shape[0] != frame_count:
            return out
        for i in range(frame_count):
            mask = arr[i].astype(bool)
            if np.any(mask):
                out[i] = mask
        return out

    def build_image_manifest(self, source_paths: list[str]) -> dict[str, Any]:
        images = []
        for idx, raw_path in enumerate(source_paths):
            p = Path(raw_path)
            entry = {
                "id": f"image_{idx + 1}",
                "relative_path": str(p),
                "absolute_path": str(p.resolve()) if p.exists() else str(p),
            }
            if p.exists() and p.is_file():
                try:
                    entry["fingerprint"] = compute_file_fingerprint(p)
                except Exception:
                    entry["fingerprint"] = {}
            else:
                entry["fingerprint"] = {}
            images.append(entry)
        return {"images": images}

    def _default_event_record(self, event_id: str, frame_count: int) -> EventRecord:
        label = "Event 1" if event_id == "event_001" else event_id
        return EventRecord(
            metadata=EventMetadata(
                event_id=str(event_id),
                label=str(label),
                start_idx=0,
                end_idx=max(0, frame_count - 1),
                analysis_output_dir=None,
                propagation_completed=True,
            ),
            analysis=EventAnalysisState(),
        )

    def ensure_event_record(self, event_id: str, frame_count: int, event_records: dict[str, EventRecord] | None = None) -> EventRecord:
        if event_records is None:
            event_records = {}
        event_id = str(event_id or "event_001")
        record = event_records.get(event_id)
        if record is None:
            record = self._default_event_record(event_id, frame_count)
            event_records[event_id] = record
        elif not isinstance(record, EventRecord):
            record = self._coerce_event_record(event_id, record, frame_count)
            event_records[event_id] = record
        return record

    def _coerce_event_record(self, event_id: str, raw: EventRecord | dict[str, Any], frame_count: int) -> EventRecord:
        if isinstance(raw, EventRecord):
            return raw
        if isinstance(raw, dict) and "metadata" in raw and "analysis" in raw:
            md = raw["metadata"]
            an = raw["analysis"]
            metadata = md if isinstance(md, EventMetadata) else EventMetadata(
                event_id=str(getattr(md, "event_id", None) or md.get("event_id") or event_id),
                label=str(getattr(md, "label", None) or md.get("label") or event_id),
                start_idx=int(getattr(md, "start_idx", None) if hasattr(md, "start_idx") else md.get("start_idx", 0)),
                end_idx=int(getattr(md, "end_idx", None) if hasattr(md, "end_idx") else md.get("end_idx", max(0, frame_count - 1))),
                analysis_output_dir=getattr(md, "analysis_output_dir", None) if hasattr(md, "analysis_output_dir") else md.get("analysis_output_dir"),
                propagation_completed=bool(getattr(md, "propagation_completed", True) if hasattr(md, "propagation_completed") else md.get("propagation_completed", True)),
            )
            analysis = an if isinstance(an, EventAnalysisState) else EventAnalysisState(
                points=self.copy_points_dict(an.get("points", {})),
                boxes=self.copy_boxes_dict(an.get("boxes", {})),
                persistent_regions=self.copy_persistent_regions(an.get("persistent_regions", [])),
                paint_layers=self.copy_paint_layers(an.get("paint_layers", {})),
                masks_committed=self.copy_masks_dict(an.get("masks_committed", {})),
                masks_draft=self.copy_masks_dict(an.get("masks_draft", {})) if an.get("masks_draft") is not None else None,
                use_draft=bool(an.get("use_draft", False)),
                ground_truth_frames={int(f) for f in an.get("ground_truth_frames", set()) or set()},
            )
            return EventRecord(metadata=metadata, analysis=analysis)
        raw = dict(raw or {})
        return EventRecord(
            metadata=EventMetadata(
                event_id=str(raw.get("id", event_id)),
                label=str(raw.get("label", event_id)),
                start_idx=int(raw.get("frame_start", 0)),
                end_idx=int(raw.get("frame_end", max(0, frame_count - 1))),
                analysis_output_dir=raw.get("analysis_output_dir"),
                propagation_completed=bool(raw.get("propagation_completed", True)),
            ),
            analysis=EventAnalysisState(
                points=self.copy_points_dict(raw.get("points", {})),
                boxes=self.copy_boxes_dict(raw.get("boxes", {})),
                persistent_regions=self.copy_persistent_regions(raw.get("persistent_regions", [])),
                paint_layers=self.copy_paint_layers(raw.get("paint_layers", {})),
                masks_committed=self.copy_masks_dict(raw.get("masks_committed", {})),
                masks_draft=self.copy_masks_dict(raw.get("masks_draft", {})) if raw.get("masks_draft") is not None else None,
                use_draft=bool(raw.get("use_draft", False)),
                ground_truth_frames={int(f) for f in raw.get("ground_truth_frames", set()) or set()},
            ),
        )

    def coerce_event_records(self, event_records: dict[str, EventRecord | dict[str, Any]] | None, frame_count: int) -> dict[str, EventRecord]:
        out: dict[str, EventRecord] = {}
        for event_id, record in dict(event_records or {}).items():
            out[str(event_id)] = self._coerce_event_record(str(event_id), record, frame_count)
        if not out:
            out["event_001"] = self._default_event_record("event_001", frame_count)
        return out

    def event_record_to_legacy_dict(self, record: EventRecord) -> dict[str, Any]:
        return {
            "id": record.metadata.event_id,
            "label": record.metadata.label,
            "points": self.copy_points_dict(record.analysis.points),
            "boxes": self.copy_boxes_dict(record.analysis.boxes),
            "persistent_regions": self.copy_persistent_regions(record.analysis.persistent_regions),
            "paint_layers": self.copy_paint_layers(record.analysis.paint_layers),
            "masks_committed": self.copy_masks_dict(record.analysis.masks_committed),
            "masks_draft": self.copy_masks_dict(record.analysis.masks_draft or {}) if record.analysis.masks_draft is not None else None,
            "use_draft": bool(record.analysis.use_draft),
            "frame_start": int(record.metadata.start_idx),
            "frame_end": int(record.metadata.end_idx),
            "propagation_completed": bool(record.metadata.propagation_completed),
            "analysis_output_dir": record.metadata.analysis_output_dir,
        }

    def event_records_to_legacy_dict(self, event_records: dict[str, EventRecord]) -> dict[str, dict[str, Any]]:
        return {str(event_id): self.event_record_to_legacy_dict(record) for event_id, record in event_records.items()}

    def sync_workspace_into_event(
        self,
        *,
        frame_count: int,
        event_id: str,
        seg_state: SegmentationState,
        event_records: dict[str, EventRecord],
    ) -> dict[str, EventRecord]:
        record = self.ensure_event_record(event_id, frame_count, event_records)
        record.analysis.points = self.copy_points_dict(seg_state.points)
        record.analysis.boxes = self.copy_boxes_dict(seg_state.boxes)
        record.analysis.persistent_regions = self.copy_persistent_regions(seg_state.persistent_regions)
        record.analysis.paint_layers = self.copy_paint_layers(seg_state.paint_layers)
        record.analysis.ground_truth_frames = set(seg_state.ground_truth_frames)
        if bool(record.analysis.use_draft) and not bool(record.metadata.propagation_completed):
            record.analysis.masks_draft = self.copy_masks_dict(seg_state.masks_cache)
            record.analysis.masks_committed = self.copy_masks_dict(record.analysis.masks_committed)
        else:
            record.analysis.masks_committed = self.apply_paint_to_masks(
                seg_state.masks_cache, seg_state.paint_layers
            )
            if bool(record.metadata.propagation_completed):
                record.analysis.masks_draft = None
            record.analysis.use_draft = False
        start_idx, end_idx = self.event_mask_bounds(record.analysis.masks_committed, frame_count)
        if record.metadata.start_idx is None:
            record.metadata.start_idx = start_idx
        else:
            record.metadata.start_idx = int(record.metadata.start_idx)
        if record.metadata.end_idx is None:
            record.metadata.end_idx = end_idx
        else:
            record.metadata.end_idx = int(record.metadata.end_idx)
        return event_records

    def load_event_into_workspace(self, *, event_id: str, event_records: dict[str, EventRecord], seg_state: SegmentationState) -> None:
        record = event_records.get(event_id)
        if record is None:
            return
        seg_state.points.clear()
        for frame_idx, pt_list in record.analysis.points.items():
            seg_state.points[int(frame_idx)] = [
                {"x": float(pt["x"]), "y": float(pt["y"]), "label": int(pt["label"])} for pt in pt_list
            ]

        seg_state.boxes.clear()
        for frame_idx, box in record.analysis.boxes.items():
            normalized = SegmentationState._normalize_box(box)
            if normalized is not None:
                seg_state.boxes[int(frame_idx)] = normalized

        seg_state.persistent_regions.clear()
        seg_state.persistent_regions.extend(self.copy_persistent_regions(record.analysis.persistent_regions))

        seg_state.paint_layers.clear()
        for frame_idx, layer in record.analysis.paint_layers.items():
            seg_state.paint_layers[int(frame_idx)] = {
                "plus": np.asarray(layer.get("plus"), dtype=bool).copy(),
                "minus": np.asarray(layer.get("minus"), dtype=bool).copy(),
            }

        source_masks = record.analysis.masks_committed
        if bool(record.analysis.use_draft) and record.analysis.masks_draft is not None:
            source_masks = record.analysis.masks_draft
        seg_state.masks_cache.clear()
        seg_state.set_leverage_map({}, None)
        for frame_idx, mask in source_masks.items():
            seg_state.masks_cache[int(frame_idx)] = np.asarray(mask, dtype=bool).copy()

        seg_state.ground_truth_frames = {
            int(f) for f in record.analysis.ground_truth_frames if int(f) in seg_state.masks_cache
        }

        seg_state.invalidate_user_frames()
        seg_state.invalidate_final_mask_frames()

    def update_event_metadata(
        self,
        event_id: str,
        event_records: dict[str, EventRecord],
        *,
        label: str | None = None,
        start_idx: int | None = None,
        end_idx: int | None = None,
        analysis_output_dir: str | None = None,
    ) -> None:
        record = self.ensure_event_record(event_id, max(1, (end_idx + 1) if end_idx is not None else 1), event_records)
        if label is not None:
            record.metadata.label = str(label)
        if start_idx is not None:
            record.metadata.start_idx = int(start_idx)
        if end_idx is not None:
            record.metadata.end_idx = int(end_idx)
        if analysis_output_dir is not None or analysis_output_dir is None:
            record.metadata.analysis_output_dir = analysis_output_dir

    def build_payload(self, snapshot: SessionSnapshot) -> tuple[dict, dict, dict, dict]:
        event_records = self.coerce_event_records(snapshot.event_records, snapshot.frame_count)

        state = default_project_state(app_version="1.3.0")
        state["created_at"] = snapshot.created_at
        state["last_saved"] = utc_now_iso()
        state["ui_state"] = {
            "last_frame": int(snapshot.current_frame_idx),
            "active_event_id": str(snapshot.active_event_id or "event_001"),
            "active_tool": str(snapshot.tool_mode),
            "zoom_level": float(snapshot.display_ratio),
            "canvas_offset": [int(snapshot.img_offset_x), int(snapshot.img_offset_y)],
            "analysis_start": int(snapshot.analysis_start),
            "analysis_end": int(snapshot.analysis_end),
            "prop_start": int(snapshot.prop_start),
            "prop_end": int(snapshot.prop_end),
            "export_start": int(snapshot.export_start),
            "export_end": int(snapshot.export_end),
        }
        state["global"] = {
            "scale_px_per_mm": snapshot.scale_px_per_mm,
            "scale_points": list(snapshot.scale_points) if snapshot.scale_points else [],
            "scale_axis_lock": bool(snapshot.scale_axis_lock),
            "scale_image_path": str(snapshot.scale_image_path or ""),
            "roi": {"ref": "roi.json"},
            "baseline_frame_count": int(snapshot.baseline_frame_count),
        }
        state["events"] = []
        state["image_manifest"] = {"ref": "images.json"}

        roi_data = {
            "roi_points": list(snapshot.roi_points) if snapshot.roi_points else [],
            "roi_polygons": list(snapshot.roi_polygons) if snapshot.roi_polygons else [],
            "roi_mask_shape": list(snapshot.roi_mask.shape) if snapshot.roi_mask is not None else None,
            "roi_mask_rle": SegmentationState._encode_rle(snapshot.roi_mask.astype(bool)) if snapshot.roi_mask is not None else None,
        }
        images_manifest = self.build_image_manifest(snapshot.current_image_source_paths)
        event_payloads = {}
        for event_id, record in event_records.items():
            prompts_state = SegmentationState()
            prompts_state.points = self.copy_points_dict(record.analysis.points)
            prompts_state.boxes = self.copy_boxes_dict(record.analysis.boxes)
            prompts_state.persistent_regions = self.copy_persistent_regions(record.analysis.persistent_regions)
            prompts_state.paint_layers = self.copy_paint_layers(record.analysis.paint_layers)
            prompts_state.ground_truth_frames = set(record.analysis.ground_truth_frames)
            prompts = prompts_state.to_prompts_json(event_id)
            committed = self.copy_masks_dict(record.analysis.masks_committed)
            draft = record.analysis.masks_draft
            frame_start, frame_end = self.event_mask_bounds(committed, snapshot.frame_count)
            frame_start = int(record.metadata.start_idx if record.metadata.start_idx is not None else frame_start)
            frame_end = int(record.metadata.end_idx if record.metadata.end_idx is not None else frame_end)
            propagation_completed = bool(record.metadata.propagation_completed)
            masks_draft_ref = f"events/{event_id}/masks_draft.npz" if (draft is not None and not propagation_completed) else None
            state["events"].append(
                {
                    "id": event_id,
                    "label": str(record.metadata.label),
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                    "masks_ref": f"events/{event_id}/masks.npz",
                    "prompts_ref": f"events/{event_id}/prompts.json",
                    "masks_draft_ref": masks_draft_ref,
                    "propagation_completed": propagation_completed,
                    "analysis_output_dir": record.metadata.analysis_output_dir,
                }
            )
            payload = {
                "masks": self.masks_dict_to_array(committed, snapshot.frame_count, snapshot.frame_shape),
                "prompts": prompts,
            }
            if masks_draft_ref is not None:
                payload["masks_draft"] = self.masks_dict_to_array(
                    self.copy_masks_dict(draft or {}),
                    snapshot.frame_count,
                    snapshot.frame_shape,
                )
            event_payloads[event_id] = payload
        return state, images_manifest, roi_data, event_payloads

    def apply_loaded_project(
        self,
        *,
        state: dict,
        loaded_event_payloads: dict[str, dict],
        frame_count: int,
        frame_shape: tuple[int, int],
        choose_resume_draft: Callable[[str], bool],
        decode_rle: Callable[[dict], np.ndarray],
    ) -> LoadedSessionActions:
        event_records: dict[str, EventRecord] = {}
        active_id = str(state.get("ui_state", {}).get("active_event_id", "event_001"))
        for ev_spec in state.get("events", []):
            event_id = str(ev_spec.get("id", "event_001"))
            payload = loaded_event_payloads.get(event_id, {})
            committed = self.array_to_masks_dict(payload.get("masks"), frame_count)
            draft_arr = payload.get("masks_draft")
            draft = self.array_to_masks_dict(draft_arr, frame_count) if draft_arr is not None else None
            tmp_state = SegmentationState()
            tmp_state.load_prompts_json(payload.get("prompts", {}), base_shape=frame_shape)
            propagation_completed = bool(ev_spec.get("propagation_completed", True))
            use_draft = False
            if draft and not propagation_completed:
                use_draft = bool(choose_resume_draft(event_id))
            event_records[event_id] = EventRecord(
                metadata=EventMetadata(
                    event_id=event_id,
                    label=str(ev_spec.get("label", event_id)),
                    start_idx=int(ev_spec.get("frame_start", 0)),
                    end_idx=int(ev_spec.get("frame_end", max(0, frame_count - 1))),
                    propagation_completed=propagation_completed,
                    analysis_output_dir=ev_spec.get("analysis_output_dir"),
                ),
                analysis=EventAnalysisState(
                    points=self.copy_points_dict(tmp_state.points),
                    boxes=self.copy_boxes_dict(tmp_state.boxes),
                    persistent_regions=self.copy_persistent_regions(tmp_state.persistent_regions),
                    paint_layers=self.copy_paint_layers(tmp_state.paint_layers),
                    masks_committed=committed,
                    masks_draft=draft,
                    use_draft=use_draft,
                    ground_truth_frames={
                        int(f) for f in tmp_state.ground_truth_frames if int(f) in committed
                    },
                ),
            )
        if not event_records:
            event_records["event_001"] = self._default_event_record("event_001", frame_count)
        if active_id not in event_records:
            active_id = next(iter(event_records.keys()))

        global_state = state.get("global", {})
        roi_points = []
        roi_polygons = []
        roi_mask = None
        return LoadedSessionActions(
            active_event_id=active_id,
            event_records=event_records,
            scale_px_per_mm=global_state.get("scale_px_per_mm"),
            scale_points=list(global_state.get("scale_points", [])) if isinstance(global_state.get("scale_points"), list) else [],
            scale_axis_lock=bool(global_state.get("scale_axis_lock", True)),
            scale_image_path=str(global_state.get("scale_image_path", "") or ""),
            roi_points=roi_points,
            roi_polygons=roi_polygons,
            roi_mask=roi_mask,
            baseline_frame_count=int(global_state.get("baseline_frame_count", 30)),
        )

    def on_propagation_status(
        self,
        *,
        status: str,
        prop_start: int,
        prop_end: int,
        active_event_id: str,
        event_records: dict[str, EventRecord],
        current_masks: dict[int, np.ndarray],
        committed_snapshot: dict[int, np.ndarray] | None,
    ) -> PropagationTransition:
        record = self.ensure_event_record(active_event_id, max(int(prop_end) + 1, 1), event_records)
        restored = None
        if status == "started":
            record.analysis.masks_committed = self.copy_masks_dict(current_masks)
            record.metadata.propagation_completed = False
            record.metadata.start_idx = int(prop_start)
            record.metadata.end_idx = int(prop_end)
        elif status == "complete":
            record.analysis.masks_committed = self.copy_masks_dict(current_masks)
            record.analysis.masks_draft = None
            record.analysis.use_draft = False
            record.metadata.propagation_completed = True
        elif status == "stopped_preserve":
            record.analysis.masks_committed = self.copy_masks_dict(current_masks)
            record.analysis.masks_draft = None
            record.analysis.use_draft = False
            record.metadata.propagation_completed = False
            record.metadata.start_idx = int(prop_start)
            record.metadata.end_idx = int(prop_end)
        elif status in ("stopped", "failed"):
            record.analysis.masks_draft = self.copy_masks_dict(current_masks)
            record.analysis.use_draft = False
            record.metadata.propagation_completed = False
            if committed_snapshot is not None:
                restored = self.copy_masks_dict(committed_snapshot)
        return PropagationTransition(event_record=record, restored_masks=restored)
