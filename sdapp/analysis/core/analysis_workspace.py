from __future__ import annotations

"""Event-scoped analysis workspace orchestration."""

from dataclasses import dataclass
from typing import Callable, Any

import numpy as np

from sdapp.analysis.core.host_handoff import intake_host_handoff_payload
from sdapp.analysis.core.project_session import ProjectSessionService, SessionSnapshot
from sdapp.analysis.core.seg_state import SegmentationState
from sdapp.analysis.core.session_state import SessionState
from sdapp.shared.frame_source.protocols import FrameSource


@dataclass
class WorkspaceUiState:
    current_frame_idx: int
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
    scale_px_per_mm: object
    scale_points: list
    scale_axis_lock: bool
    scale_image_path: str
    roi_points: list
    roi_polygons: list
    roi_mask: object
    created_at: str


class AnalysisWorkspaceController:
    _FRAME_ORIGIN_SCOPE_LOCAL = "analysis_scope_local"
    _FRAME_ORIGIN_EVENT_LOCAL = "event_local"
    _FRAME_ORIGIN_GLOBAL = "global"

    def __init__(
        self,
        *,
        session_service: ProjectSessionService,
        session_state: SessionState,
        seg_state: SegmentationState,
        on_event_opened: Callable[[str], None] | None = None,
    ):
        self.session_service = session_service
        self.session_state = session_state
        self.seg_state = seg_state
        self.frame_source: FrameSource | None = None
        self._on_event_opened = on_event_opened
        self._host_context: dict[str, Any] | None = None
        self._sync_emitter: Callable[[dict[str, Any]], None] | None = None
        self._resolved_frame_dims_cache: tuple[int, tuple[int, int]] | None = None

    def _resolved_frame_count_and_shape(self) -> tuple[int, tuple[int, int]]:
        if self._resolved_frame_dims_cache is not None:
            return self._resolved_frame_dims_cache
        if self.frame_source is None:
            return 0, (0, 0)
        frame_count = int(getattr(self.frame_source, "frame_count", 0) or 0)
        frame_shape = tuple(int(v) for v in tuple(getattr(self.frame_source, "frame_shape", (0, 0)))[:2])
        if frame_count > 0:
            get_raw_frame = getattr(self.frame_source, "get_raw_frame", None)
            if callable(get_raw_frame):
                try:
                    sampled = np.asarray(get_raw_frame(0))
                except Exception:
                    sampled = None
                if sampled is not None:
                    sampled_shape = tuple(int(v) for v in tuple(sampled.shape[:2]))
                    if len(sampled_shape) == 2 and sampled_shape[0] > 0 and sampled_shape[1] > 0:
                        if tuple(frame_shape) != tuple(sampled_shape):
                            frame_shape = sampled_shape
        resolved = int(frame_count), (int(frame_shape[0]), int(frame_shape[1]))
        self._resolved_frame_dims_cache = resolved
        return resolved

    @staticmethod
    def _normalize_frame_idx_to_local(
        idx: int,
        *,
        frame_count: int,
        scope_start: int | None,
        scope_end: int | None,
        local_event_start: int | None = None,
        local_event_end: int | None = None,
        origin_hint: object = None,
    ) -> int | None:
        raw = int(idx)
        total_frames = int(frame_count)
        if total_frames <= 0:
            return None
        normalized_origin = str(origin_hint or "").strip().lower()
        event_span_len = None
        if local_event_start is not None and local_event_end is not None:
            try:
                start_idx = int(local_event_start)
                end_idx = int(local_event_end)
                if end_idx >= start_idx:
                    event_span_len = int(end_idx - start_idx + 1)
            except (TypeError, ValueError):
                event_span_len = None

        def _from_scope_local(value: int) -> int | None:
            if 0 <= int(value) < total_frames:
                return int(value)
            return None

        def _from_global(value: int) -> int | None:
            if scope_start is None or scope_end is None:
                return None
            if int(scope_start) <= int(value) <= int(scope_end):
                local = int(value) - int(scope_start)
                if 0 <= local < total_frames:
                    return local
            return None

        def _from_event_local(value: int) -> int | None:
            if local_event_start is None or event_span_len is None:
                return None
            if 0 <= int(value) < int(event_span_len):
                local = int(local_event_start) + int(value)
                if 0 <= local < total_frames:
                    return local
            return None

        if normalized_origin == "analysis_scope_local":
            return _from_scope_local(raw) or _from_global(raw)
        if normalized_origin == "event_local":
            return _from_event_local(raw) or _from_global(raw) or _from_scope_local(raw)
        if normalized_origin == "global":
            return _from_global(raw)

        # Heuristic fallback for legacy payloads without origin metadata.
        from_global = _from_global(raw)
        if from_global is not None:
            return from_global
        if 0 <= raw < total_frames:
            if event_span_len is not None and local_event_start is not None and int(local_event_start) > 0 and raw < int(event_span_len):
                inferred_event_local = _from_event_local(raw)
                if inferred_event_local is not None and raw < int(local_event_start):
                    return inferred_event_local
            return raw
        return None

    def _normalize_prompts_to_local(
        self,
        prompts_payload: dict[str, Any],
        *,
        frame_count: int,
        frame_shape: tuple[int, int],
        scope_start: int | None,
        scope_end: int | None,
        local_event_start: int | None = None,
        local_event_end: int | None = None,
        origin_hint: object = None,
    ) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[float]], list[dict], dict[int, dict[str, np.ndarray]]]:
        tmp = SegmentationState()
        tmp.load_prompts_json(prompts_payload, base_shape=frame_shape)
        points: dict[int, list[dict[str, Any]]] = {}
        boxes: dict[int, list[float]] = {}
        persistent_regions: list[dict] = []
        paint_layers: dict[int, dict[str, np.ndarray]] = {}
        for frame_idx, point_list in tmp.points.items():
            local = self._normalize_frame_idx_to_local(
                int(frame_idx),
                frame_count=frame_count,
                scope_start=scope_start,
                scope_end=scope_end,
                local_event_start=local_event_start,
                local_event_end=local_event_end,
                origin_hint=origin_hint,
            )
            if local is None:
                continue
            points.setdefault(local, []).extend([dict(p) for p in list(point_list or [])])
        for frame_idx, box in tmp.boxes.items():
            local = self._normalize_frame_idx_to_local(
                int(frame_idx),
                frame_count=frame_count,
                scope_start=scope_start,
                scope_end=scope_end,
                local_event_start=local_event_start,
                local_event_end=local_event_end,
                origin_hint=origin_hint,
            )
            if local is None:
                continue
            normalized = SegmentationState._normalize_box(box)
            if normalized is not None:
                boxes[local] = normalized
        for region in tmp.persistent_regions:
            normalized = tmp._normalize_persistent_region(region)
            if normalized is None:
                continue
            start = self._normalize_frame_idx_to_local(
                int(normalized["frame_start"]),
                frame_count=frame_count,
                scope_start=scope_start,
                scope_end=scope_end,
                local_event_start=local_event_start,
                local_event_end=local_event_end,
                origin_hint=origin_hint,
            )
            end = self._normalize_frame_idx_to_local(
                int(normalized["frame_end"]),
                frame_count=frame_count,
                scope_start=scope_start,
                scope_end=scope_end,
                local_event_start=local_event_start,
                local_event_end=local_event_end,
                origin_hint=origin_hint,
            )
            if start is None or end is None:
                continue
            normalized["frame_start"] = min(start, end)
            normalized["frame_end"] = max(start, end)
            persistent_regions.append(normalized)
        for frame_idx, layer in tmp.paint_layers.items():
            local = self._normalize_frame_idx_to_local(
                int(frame_idx),
                frame_count=frame_count,
                scope_start=scope_start,
                scope_end=scope_end,
                local_event_start=local_event_start,
                local_event_end=local_event_end,
                origin_hint=origin_hint,
            )
            if local is None:
                continue
            plus = np.asarray(layer.get("plus"), dtype=bool)
            minus = np.asarray(layer.get("minus"), dtype=bool)
            if plus.shape != frame_shape or minus.shape != frame_shape:
                continue
            existing = paint_layers.get(local)
            if existing is None:
                paint_layers[local] = {"plus": plus.copy(), "minus": minus.copy()}
            else:
                existing["plus"] = np.logical_or(existing["plus"], plus)
                existing["minus"] = np.logical_or(existing["minus"], minus)
        return points, boxes, persistent_regions, paint_layers

    def _normalize_masks_to_local(
        self,
        masks_payload: Any,
        *,
        frame_count: int,
        scope_start: int | None,
        scope_end: int | None,
        frame_shape: tuple[int, int] | None = None,
        local_event_start: int | None = None,
        local_event_end: int | None = None,
        origin_hint: object = None,
    ) -> dict[int, np.ndarray]:
        def _coerce_2d_mask(mask_payload: Any) -> np.ndarray | None:
            try:
                arr = np.asarray(mask_payload, dtype=bool)
            except Exception:
                return None
            squeezed = np.squeeze(arr)
            if squeezed.ndim != 2:
                return None
            if frame_shape is not None:
                expected = (int(frame_shape[0]), int(frame_shape[1]))
                if tuple(squeezed.shape) != expected:
                    return None
            return np.asarray(squeezed, dtype=bool).copy()

        def _array_to_masks_dict(mask_array: np.ndarray) -> dict[int, np.ndarray]:
            out: dict[int, np.ndarray] = {}
            if mask_array.ndim != 3:
                return out
            if mask_array.shape[0] <= 0:
                return out
            for idx in range(min(int(frame_count), int(mask_array.shape[0]))):
                mask_2d = _coerce_2d_mask(mask_array[idx])
                if mask_2d is not None and np.any(mask_2d):
                    out[int(idx)] = mask_2d
            return out

        event_span_len: int | None = None
        if local_event_start is not None and local_event_end is not None:
            try:
                start_idx = int(local_event_start)
                end_idx = int(local_event_end)
                if end_idx >= start_idx:
                    event_span_len = int(end_idx - start_idx + 1)
            except (TypeError, ValueError):
                event_span_len = None

        if masks_payload is None:
            return {}
        if isinstance(masks_payload, np.ndarray) and masks_payload.ndim == 0 and masks_payload.dtype == object:
            try:
                masks_payload = masks_payload.item()
            except Exception:
                pass
        if isinstance(masks_payload, dict):
            out: dict[int, np.ndarray] = {}
            for frame_idx, mask in masks_payload.items():
                try:
                    frame_idx_int = int(frame_idx)
                except (TypeError, ValueError):
                    continue
                local = self._normalize_frame_idx_to_local(
                    frame_idx_int,
                    frame_count=frame_count,
                    scope_start=scope_start,
                    scope_end=scope_end,
                    local_event_start=local_event_start,
                    local_event_end=local_event_end,
                    origin_hint=origin_hint,
                )
                if local is None:
                    continue
                mask_2d = _coerce_2d_mask(mask)
                if mask_2d is not None and np.any(mask_2d):
                    out[local] = mask_2d
            return out

        arr = np.asarray(masks_payload)
        if arr.ndim == 4 and arr.shape[-1] == 1:
            arr = np.squeeze(arr, axis=-1)
        elif arr.ndim == 4 and arr.shape[1] == 1:
            arr = np.squeeze(arr, axis=1)
        if arr.ndim != 3:
            return {}
        if frame_shape is not None:
            expected = (int(frame_shape[0]), int(frame_shape[1]))
            if tuple(arr.shape[1:]) != expected:
                return {}
        normalized_origin = str(origin_hint or "").strip().lower()
        if normalized_origin == "analysis_scope_local" and arr.shape[0] == frame_count:
            return _array_to_masks_dict(arr)
        if normalized_origin == "global":
            if scope_start is not None and scope_end is not None and arr.shape[0] > int(scope_end):
                scoped = arr[int(scope_start) : int(scope_end) + 1]
                if scoped.shape[0] == frame_count:
                    return _array_to_masks_dict(scoped)
            return {}
        if (
            normalized_origin == "event_local"
            and event_span_len is not None
            and local_event_start is not None
            and arr.shape[0] == int(event_span_len)
            and 0 <= int(local_event_start) < frame_count
        ):
            out: dict[int, np.ndarray] = {}
            base = int(local_event_start)
            for idx in range(arr.shape[0]):
                local_idx = base + int(idx)
                if local_idx >= frame_count:
                    break
                mask_2d = _coerce_2d_mask(arr[idx])
                if mask_2d is not None and np.any(mask_2d):
                    out[local_idx] = mask_2d
            return out
        if arr.shape[0] == frame_count:
            return _array_to_masks_dict(arr)
        if scope_start is not None and scope_end is not None and arr.shape[0] > int(scope_end):
            scoped = arr[int(scope_start) : int(scope_end) + 1]
            if scoped.shape[0] == frame_count:
                return _array_to_masks_dict(scoped)
        if (
            event_span_len is not None
            and local_event_start is not None
            and arr.shape[0] == int(event_span_len)
            and 0 <= int(local_event_start) < frame_count
        ):
            out: dict[int, np.ndarray] = {}
            base = int(local_event_start)
            for idx in range(arr.shape[0]):
                local_idx = base + int(idx)
                if local_idx >= frame_count:
                    break
                mask_2d = _coerce_2d_mask(arr[idx])
                if mask_2d is not None and np.any(mask_2d):
                    out[local_idx] = mask_2d
            return out
        return _array_to_masks_dict(arr)

    def bind_frame_source(self, frame_source: FrameSource | None) -> None:
        self.frame_source = frame_source
        self._resolved_frame_dims_cache = None

    def open_from_handoff_payload(
        self,
        payload: dict[str, Any],
        *,
        frame_source: FrameSource | None = None,
        sync_emitter: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Host-driven open path for validated event-scoped analysis workspaces."""
        intake = intake_host_handoff_payload(payload)
        if not bool(intake.get("ok")):
            return intake

        normalized = intake["normalized"]
        if frame_source is not None:
            self.bind_frame_source(frame_source)
        if self.frame_source is None:
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "Host-driven open requires a bound frame source.",
            }
        self._sync_emitter = sync_emitter
        self._host_context = normalized

        event = dict(normalized["event"])
        event_id = str(event["event_id"])
        flags = dict(event.get("flags", {}))
        local_start = int(flags.get("analysis_local_event_start_idx", event["start_idx"]))
        local_end = int(flags.get("analysis_local_event_end_idx", event["end_idx"]))
        frame_count = int(self.frame_source.frame_count)
        records = self.session_state.event_records
        self.session_service.ensure_event_record(event_id, frame_count, records)
        self.session_service.update_event_metadata(
            event_id=event_id,
            event_records=records,
            label=str(event["label"]),
            start_idx=local_start,
            end_idx=local_end,
        )
        self.open_event(event_id)
        return {"ok": True, "normalized": normalized}

    def open_from_host_event_context(
        self,
        context: dict[str, Any],
        *,
        frame_source: FrameSource | None = None,
        sync_emitter: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if frame_source is not None:
            self.bind_frame_source(frame_source)
        if self.frame_source is None:
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "Host direct open requires a bound frame source.",
            }
        event = dict(context.get("event", {}))
        event_id = str(event.get("event_id", "")).strip()
        if not event_id:
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": "Missing event_id in host context."}

        self._host_context = {
            "contract_version": 1,
            "session": {"session_id": str(context.get("session_id", ""))},
            "stack": {"stack_id": str(context.get("stack_id", ""))},
            "event": event,
            "analysis_state_ref": {"storage": "host_session", "ref_id": f"{context.get('session_id', '')}:{event_id}"},
        }
        self._sync_emitter = sync_emitter

        flags = dict(event.get("flags", {})) if isinstance(event.get("flags"), dict) else {}
        scope_start_raw = flags.get("analysis_scope_start_idx", event.get("start_idx", 0))
        scope_end_raw = flags.get("analysis_scope_end_idx", event.get("end_idx", scope_start_raw))
        scope_start = int(scope_start_raw) if scope_start_raw is not None else None
        scope_end = int(scope_end_raw) if scope_end_raw is not None else None
        local_start = int(flags.get("analysis_local_event_start_idx", event.get("start_idx", 0)))
        local_end = int(flags.get("analysis_local_event_end_idx", event.get("end_idx", local_start)))
        frame_count, frame_shape = self._resolved_frame_count_and_shape()
        records = self.session_state.event_records
        self.session_service.ensure_event_record(event_id, frame_count, records)
        self.session_service.update_event_metadata(
            event_id=event_id,
            event_records=records,
            label=str(event.get("label", event_id)),
            start_idx=local_start,
            end_idx=local_end,
        )
        initial_state = context.get("analysis_state")
        if isinstance(initial_state, dict):
            record = records.get(event_id)
            if record is not None:
                prompts = initial_state.get("prompts")
                if isinstance(prompts, dict):
                    points, boxes, persistent_regions, paint_layers = self._normalize_prompts_to_local(
                        prompts,
                        frame_count=frame_count,
                        frame_shape=frame_shape,
                        scope_start=scope_start,
                        scope_end=scope_end,
                        local_event_start=local_start,
                        local_event_end=local_end,
                        origin_hint=initial_state.get("prompts_frame_origin"),
                    )
                    record.analysis.points = self.session_service.copy_points_dict(points)
                    record.analysis.boxes = self.session_service.copy_boxes_dict(boxes)
                    record.analysis.persistent_regions = self.session_service.copy_persistent_regions(persistent_regions)
                    record.analysis.paint_layers = self.session_service.copy_paint_layers(paint_layers)
                masks_committed = initial_state.get("masks_committed")
                if masks_committed is not None:
                    try:
                        record.analysis.masks_committed = self._normalize_masks_to_local(
                            masks_committed,
                            frame_count=frame_count,
                            scope_start=scope_start,
                            scope_end=scope_end,
                            frame_shape=frame_shape,
                            local_event_start=local_start,
                            local_event_end=local_end,
                            origin_hint=initial_state.get("masks_committed_frame_origin"),
                        )
                    except Exception:
                        pass
        self.open_event(event_id)
        return {"ok": True, "normalized": dict(context)}

    def reset_workspace_for_new_stack(self) -> None:
        frame_count = self.frame_source.frame_count if self.frame_source is not None else 0
        self.session_state.active_event_id = "sd_event_001"
        self.session_state.event_records = self.session_service.coerce_event_records({}, frame_count)

    def open_event(self, event_id: str) -> None:
        frame_count = self.frame_source.frame_count if self.frame_source is not None else 1
        event_id = str(event_id or "sd_event_001")
        self.session_service.ensure_event_record(event_id, frame_count, self.session_state.event_records)
        self.session_service.load_event_into_workspace(
            event_id=event_id,
            event_records=self.session_state.event_records,
            seg_state=self.seg_state,
        )
        self.session_state.active_event_id = event_id
        if self._on_event_opened is not None:
            self._on_event_opened(event_id)

    def sync_active_event(self) -> dict[str, object]:
        frame_count = self.frame_source.frame_count if self.frame_source is not None else 1
        return self.session_service.sync_workspace_into_event(
            frame_count=frame_count,
            event_id=self.session_state.active_event_id,
            seg_state=self.seg_state,
            event_records=self.session_state.event_records,
        )

    def build_host_sync_payload(self, *, ui_hints: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if self._host_context is None or self.frame_source is None:
            return None
        self.sync_active_event()
        event_id = str(self.session_state.active_event_id or self._host_context["event"]["event_id"])
        record = self.session_state.event_records.get(event_id)
        if record is None:
            return None
        frame_count, resolved_shape = self._resolved_frame_count_and_shape()
        masks_shape = [int(v) for v in resolved_shape]
        return {
            "contract_version": int(self._host_context["contract_version"]),
            "session_id": str(self._host_context["session"]["session_id"]),
            "stack_id": str(self._host_context["stack"]["stack_id"]),
            "event_id": event_id,
            "analysis_state_ref": dict(self._host_context["analysis_state_ref"]),
            "analysis": {
                "masks_committed": {
                    "encoding": "npz_uint8_3d",
                    "frame_count": frame_count,
                    "shape": masks_shape,
                    "blob_ref": f"in_memory://{event_id}/masks_committed",
                },
                "masks_draft": (
                    {
                        "encoding": "npz_uint8_3d",
                        "frame_count": frame_count,
                        "shape": masks_shape,
                        "blob_ref": f"in_memory://{event_id}/masks_draft",
                    }
                    if record.analysis.masks_draft is not None
                    else None
                ),
                "prompts": {
                    "encoding": "portable_prompts_json",
                    "blob_ref": f"in_memory://{event_id}/prompts",
                },
                "propagation_completed": bool(record.metadata.propagation_completed),
                "analysis_output_dir": record.metadata.analysis_output_dir,
            },
            "ui_hints": dict(ui_hints or {}),
        }

    def emit_host_sync(self, *, ui_hints: dict[str, Any] | None = None) -> dict[str, Any] | None:
        payload = self.build_host_sync_payload(ui_hints=ui_hints)
        if payload is None:
            return None
        if self._sync_emitter is not None:
            self._sync_emitter(payload)
        return payload

    def export_active_event_analysis_payload(self) -> dict[str, Any] | None:
        if self.frame_source is None:
            return None
        self.sync_active_event()
        event_id = str(self.session_state.active_event_id or "")
        if not event_id:
            return None
        record = self.session_state.event_records.get(event_id)
        if record is None:
            return None
        frame_count, frame_shape = self._resolved_frame_count_and_shape()
        prompts_state = SegmentationState()
        prompts_state.points = self.session_service.copy_points_dict(record.analysis.points)
        prompts_state.boxes = self.session_service.copy_boxes_dict(record.analysis.boxes)
        prompts_state.persistent_regions = self.session_service.copy_persistent_regions(record.analysis.persistent_regions)
        prompts_state.paint_layers = self.session_service.copy_paint_layers(record.analysis.paint_layers)
        prompts_state.ground_truth_frames = set(record.analysis.ground_truth_frames)
        return {
            "event_id": event_id,
            "prompts": prompts_state.to_prompts_json(event_id),
            "masks_committed": self.session_service.masks_dict_to_array(
                self.session_service.copy_masks_dict(record.analysis.masks_committed),
                frame_count,
                frame_shape,
            ),
            "masks_draft": (
                self.session_service.masks_dict_to_array(
                    self.session_service.copy_masks_dict(record.analysis.masks_draft or {}),
                    frame_count,
                    frame_shape,
                )
                if record.analysis.masks_draft is not None
                else None
            ),
            "propagation_completed": bool(record.metadata.propagation_completed),
            "analysis_output_dir": record.metadata.analysis_output_dir,
        }

    def build_session_snapshot(self, ui_state: WorkspaceUiState) -> SessionSnapshot:
        if self.frame_source is None:
            raise RuntimeError("No frame source bound to analysis workspace.")
        self.sync_active_event()
        frame_count, frame_shape = self._resolved_frame_count_and_shape()
        return SessionSnapshot(
            frame_count=frame_count,
            frame_shape=frame_shape,
            current_frame_idx=int(ui_state.current_frame_idx),
            active_event_id=str(self.session_state.active_event_id or "sd_event_001"),
            tool_mode=str(ui_state.tool_mode),
            display_ratio=float(ui_state.display_ratio),
            img_offset_x=int(ui_state.img_offset_x),
            img_offset_y=int(ui_state.img_offset_y),
            analysis_start=int(ui_state.analysis_start),
            analysis_end=int(ui_state.analysis_end),
            prop_start=int(ui_state.prop_start),
            prop_end=int(ui_state.prop_end),
            export_start=int(ui_state.export_start),
            export_end=int(ui_state.export_end),
            baseline_frame_count=int(ui_state.baseline_frame_count),
            scale_px_per_mm=ui_state.scale_px_per_mm,
            scale_points=list(ui_state.scale_points) if ui_state.scale_points else [],
            scale_axis_lock=bool(ui_state.scale_axis_lock),
            scale_image_path=str(ui_state.scale_image_path or ""),
            roi_points=list(ui_state.roi_points) if ui_state.roi_points else [],
            roi_polygons=list(ui_state.roi_polygons) if ui_state.roi_polygons else [],
            roi_mask=ui_state.roi_mask,
            created_at=str(ui_state.created_at),
            current_image_source_paths=list(self.frame_source.source_paths),
            event_records=dict(self.session_state.event_records),
        )

    def on_propagation_status(self, status: str, prop_start: int, prop_end: int, committed_snapshot):
        frame_count = self.frame_source.frame_count if self.frame_source is not None else max(int(prop_end) + 1, 1)
        return self.session_service.on_propagation_status(
            status=str(status),
            prop_start=int(prop_start),
            prop_end=int(prop_end),
            active_event_id=str(self.session_state.active_event_id or "sd_event_001"),
            event_records=self.session_state.event_records,
            current_masks=self.seg_state.masks_cache,
            committed_snapshot=committed_snapshot,
        )
