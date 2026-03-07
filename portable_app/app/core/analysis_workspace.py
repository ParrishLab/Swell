from __future__ import annotations

"""Event-scoped analysis workspace orchestration."""

from dataclasses import dataclass
from typing import Callable, Any

from app.core.frame_source import FrameSource
from app.core.host_handoff import intake_host_handoff_payload
from app.core.project_session import ProjectSessionService, SessionSnapshot
from app.core.seg_state import SegmentationState
from app.core.session_state import SessionState


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
    roi_points: list
    roi_mask: object
    created_at: str


class AnalysisWorkspaceController:
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

    def bind_frame_source(self, frame_source: FrameSource | None) -> None:
        self.frame_source = frame_source

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
        masks_shape = [int(v) for v in self.frame_source.frame_shape]
        frame_count = int(self.frame_source.frame_count)
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

    def build_session_snapshot(self, ui_state: WorkspaceUiState) -> SessionSnapshot:
        if self.frame_source is None:
            raise RuntimeError("No frame source bound to analysis workspace.")
        self.sync_active_event()
        return SessionSnapshot(
            frame_count=self.frame_source.frame_count,
            frame_shape=self.frame_source.frame_shape,
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
            roi_points=list(ui_state.roi_points) if ui_state.roi_points else [],
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
