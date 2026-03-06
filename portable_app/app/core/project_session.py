from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.core.project_fingerprint import compute_file_fingerprint
from app.core.project_schema import default_project_state, utc_now_iso
from app.core.seg_state import SegmentationState


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
    roi_points: list
    roi_mask: np.ndarray | None
    created_at: str
    current_image_source_paths: list[str]
    event_states: dict[str, dict]


@dataclass
class LoadedSessionActions:
    active_event_id: str
    event_states: dict[str, dict]
    scale_px_per_mm: Any
    roi_points: list
    roi_mask: np.ndarray | None
    baseline_frame_count: int


@dataclass
class PropagationTransition:
    event_state: dict
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

    def copy_masks_dict(self, masks: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
        return {int(idx): np.asarray(mask, dtype=bool).copy() for idx, mask in masks.items() if mask is not None}

    def copy_paint_layers(self, layers: dict[int, dict[str, np.ndarray]]) -> dict[int, dict[str, np.ndarray]]:
        out = {}
        for frame_idx, layer in layers.items():
            plus = np.asarray(layer.get("plus"), dtype=bool).copy()
            minus = np.asarray(layer.get("minus"), dtype=bool).copy()
            out[int(frame_idx)] = {"plus": plus, "minus": minus}
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
                arr[idx] = np.asarray(mask, dtype=np.uint8)
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

    def sync_active_event_state(
        self,
        *,
        frame_count: int,
        active_event_id: str,
        seg_state: SegmentationState,
        event_states: dict[str, dict],
    ) -> dict[str, dict]:
        event_id = str(active_event_id or "sd_event_001")
        state = event_states.get(event_id, {})
        state["id"] = event_id
        state["label"] = str(state.get("label", event_id))
        state["points"] = self.copy_points_dict(seg_state.points)
        state["paint_layers"] = self.copy_paint_layers(seg_state.paint_layers)
        if bool(state.get("use_draft")) and not bool(state.get("propagation_completed", True)):
            state["masks_draft"] = self.copy_masks_dict(seg_state.masks_cache)
            state["masks_committed"] = self.copy_masks_dict(state.get("masks_committed", {}))
        else:
            state["masks_committed"] = self.copy_masks_dict(seg_state.masks_cache)
            if bool(state.get("propagation_completed", True)):
                state["masks_draft"] = None
            state["use_draft"] = False
        start_idx, end_idx = self.event_mask_bounds(state["masks_committed"], frame_count)
        state["frame_start"] = int(state.get("frame_start", start_idx))
        state["frame_end"] = int(state.get("frame_end", end_idx))
        state["propagation_completed"] = bool(state.get("propagation_completed", True))
        state["analysis_output_dir"] = state.get("analysis_output_dir")
        event_states[event_id] = state
        return event_states

    def load_event_into_seg_state(self, *, event_id: str, event_states: dict[str, dict], seg_state: SegmentationState) -> None:
        state = event_states.get(event_id)
        if state is None:
            return
        seg_state.points.clear()
        for frame_idx, pt_list in state.get("points", {}).items():
            seg_state.points[int(frame_idx)] = [
                {"x": float(pt["x"]), "y": float(pt["y"]), "label": int(pt["label"])} for pt in pt_list
            ]

        seg_state.paint_layers.clear()
        for frame_idx, layer in state.get("paint_layers", {}).items():
            seg_state.paint_layers[int(frame_idx)] = {
                "plus": np.asarray(layer.get("plus"), dtype=bool).copy(),
                "minus": np.asarray(layer.get("minus"), dtype=bool).copy(),
            }

        source_masks = state.get("masks_committed", {})
        if bool(state.get("use_draft")) and state.get("masks_draft") is not None:
            source_masks = state.get("masks_draft", {})
        seg_state.masks_cache.clear()
        for frame_idx, mask in source_masks.items():
            seg_state.masks_cache[int(frame_idx)] = np.asarray(mask, dtype=bool).copy()

        seg_state.invalidate_user_frames()
        seg_state.invalidate_final_mask_frames()

    def build_payload(self, snapshot: SessionSnapshot) -> tuple[dict, dict, dict, dict]:
        event_states = dict(snapshot.event_states or {})
        if not event_states:
            event_states["sd_event_001"] = {
                "id": "sd_event_001",
                "label": "SD Event 1",
                "points": {},
                "paint_layers": {},
                "masks_committed": {},
                "masks_draft": None,
                "use_draft": False,
                "frame_start": 0,
                "frame_end": max(0, snapshot.frame_count - 1),
                "propagation_completed": True,
                "analysis_output_dir": None,
            }

        state = default_project_state(app_version="1.3.0")
        state["created_at"] = snapshot.created_at
        state["last_saved"] = utc_now_iso()
        state["ui_state"] = {
            "last_frame": int(snapshot.current_frame_idx),
            "active_event_id": str(snapshot.active_event_id or "sd_event_001"),
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
            "roi": {"ref": "roi.json"},
            "baseline_frame_count": int(snapshot.baseline_frame_count),
        }
        state["events"] = []
        state["image_manifest"] = {"ref": "images.json"}

        roi_data = {
            "roi_points": list(snapshot.roi_points) if snapshot.roi_points else [],
            "roi_mask_shape": list(snapshot.roi_mask.shape) if snapshot.roi_mask is not None else None,
            "roi_mask_rle": SegmentationState._encode_rle(snapshot.roi_mask.astype(bool)) if snapshot.roi_mask is not None else None,
        }
        images_manifest = self.build_image_manifest(snapshot.current_image_source_paths)
        event_payloads = {}
        for event_id, ev_state in event_states.items():
            event_id = str(event_id)
            prompts_state = SegmentationState()
            prompts_state.points = self.copy_points_dict(ev_state.get("points", {}))
            prompts_state.paint_layers = self.copy_paint_layers(ev_state.get("paint_layers", {}))
            prompts = prompts_state.to_prompts_json(event_id)
            committed = self.copy_masks_dict(ev_state.get("masks_committed", {}))
            draft = ev_state.get("masks_draft")
            frame_start, frame_end = self.event_mask_bounds(committed, snapshot.frame_count)
            frame_start = int(ev_state.get("frame_start", frame_start))
            frame_end = int(ev_state.get("frame_end", frame_end))
            propagation_completed = bool(ev_state.get("propagation_completed", True))
            masks_draft_ref = f"events/{event_id}/masks_draft.npz" if (draft is not None and not propagation_completed) else None
            state["events"].append(
                {
                    "id": event_id,
                    "label": str(ev_state.get("label", event_id)),
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                    "masks_ref": f"events/{event_id}/masks.npz",
                    "prompts_ref": f"events/{event_id}/prompts.json",
                    "masks_draft_ref": masks_draft_ref,
                    "propagation_completed": propagation_completed,
                    "analysis_output_dir": ev_state.get("analysis_output_dir"),
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
        event_states: dict[str, dict] = {}
        active_id = str(state.get("ui_state", {}).get("active_event_id", "sd_event_001"))
        for ev_spec in state.get("events", []):
            event_id = str(ev_spec.get("id", "sd_event_001"))
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
            event_states[event_id] = {
                "id": event_id,
                "label": str(ev_spec.get("label", event_id)),
                "points": self.copy_points_dict(tmp_state.points),
                "paint_layers": self.copy_paint_layers(tmp_state.paint_layers),
                "masks_committed": committed,
                "masks_draft": draft,
                "use_draft": use_draft,
                "frame_start": int(ev_spec.get("frame_start", 0)),
                "frame_end": int(ev_spec.get("frame_end", max(0, frame_count - 1))),
                "propagation_completed": propagation_completed,
                "analysis_output_dir": ev_spec.get("analysis_output_dir"),
            }
        if not event_states:
            event_states["sd_event_001"] = {
                "id": "sd_event_001",
                "label": "SD Event 1",
                "points": {},
                "paint_layers": {},
                "masks_committed": {},
                "masks_draft": None,
                "use_draft": False,
                "frame_start": 0,
                "frame_end": max(0, frame_count - 1),
                "propagation_completed": True,
                "analysis_output_dir": None,
            }
        if active_id not in event_states:
            active_id = next(iter(event_states.keys()))

        global_state = state.get("global", {})
        roi_points = []
        roi_mask = None
        return LoadedSessionActions(
            active_event_id=active_id,
            event_states=event_states,
            scale_px_per_mm=global_state.get("scale_px_per_mm"),
            roi_points=roi_points,
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
        event_states: dict[str, dict],
        current_masks: dict[int, np.ndarray],
        committed_snapshot: dict[int, np.ndarray] | None,
    ) -> PropagationTransition:
        event_id = str(active_event_id or "sd_event_001")
        if event_id not in event_states:
            event_states[event_id] = {
                "id": event_id,
                "label": event_id,
                "points": {},
                "paint_layers": {},
                "masks_committed": {},
                "masks_draft": None,
                "use_draft": False,
                "frame_start": int(prop_start),
                "frame_end": int(prop_end),
                "propagation_completed": True,
                "analysis_output_dir": None,
            }
        state = event_states[event_id]
        restored = None
        if status == "started":
            state["masks_committed"] = self.copy_masks_dict(current_masks)
            state["propagation_completed"] = False
            state["frame_start"] = int(prop_start)
            state["frame_end"] = int(prop_end)
        elif status == "complete":
            state["masks_committed"] = self.copy_masks_dict(current_masks)
            state["masks_draft"] = None
            state["use_draft"] = False
            state["propagation_completed"] = True
        elif status in ("stopped", "failed"):
            state["masks_draft"] = self.copy_masks_dict(current_masks)
            state["use_draft"] = False
            state["propagation_completed"] = False
            if committed_snapshot is not None:
                restored = self.copy_masks_dict(committed_snapshot)
        return PropagationTransition(event_state=state, restored_masks=restored)
