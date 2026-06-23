from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from swell.analysis.controllers.host_mode_controller import AnalysisHostModeController
from swell.analysis.core import mask_import_workflow
from swell.analysis.core.analysis_workspace import AnalysisWorkspaceController
from swell.analysis.core.project_session import ProjectSessionService
from swell.analysis.core.seg_state import SegmentationState
from swell.analysis.core.session_state import SessionState
from swell.host.browser_controller import BrowserController
from swell.host.config import FrameRef
from swell.shared.contracts import ValidatorErrorCode
from swell.shared.frame_source import EventScopedFrameSource


class FakeReader:
    def __init__(self) -> None:
        self._frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(8)]
        self._refs = [
            FrameRef(i, source_path=Path(f"/tmp/frame_{i}.tif"), page_index=None, source_ext=".tif", frame_name=f"f{i}.tif")
            for i in range(8)
        ]

    def get_frame_count(self) -> int:
        return len(self._frames)

    def get_stack_info(self):
        class Info:
            frame_height = 64
            frame_width = 64

        return Info()

    def get_frame_name(self, idx: int) -> str:
        return self._refs[idx].frame_name

    def get_frame_ref(self, idx: int):
        return self._refs[idx]

    def read_frame(self, idx: int, use_cache: bool = True):  # noqa: ARG002
        return self._frames[idx]


class FakeStackInfo:
    def __init__(self, input_dir: str = "/tmp/in") -> None:
        self.input_dir = input_dir
        self.frame_count = 8
        self.frame_height = 64
        self.frame_width = 64
        self.dtype = "uint8"


def _analysis_controller():
    return AnalysisWorkspaceController(
        session_service=ProjectSessionService(),
        session_state=SessionState(),
        seg_state=SegmentationState(),
    )


class _DialogStub:
    def __init__(self, paths, masks, offset) -> None:
        self._paths = paths
        self._masks = masks
        self._offset = offset

    def choose_paths(self, _root):
        return list(self._paths)

    def load_external_mask_images(self, _paths):
        return list(self._masks)

    def ask_alignment(self, **_kwargs):
        return self._offset


def test_vertical_slice_event_roundtrip_no_id_drift() -> None:
    host = BrowserController()
    host.on_stack_loaded(FakeReader(), FakeStackInfo("/tmp/in_a"))
    event = host.create_event(start_idx=2, end_idx=5, frame_count=8)
    host.set_active_event(event.event_id)

    handoff = host.handoff.selected_event_payload()
    assert handoff is not None and handoff.get("ok") is not False

    emitted = []
    analysis = _analysis_controller()
    open_result = analysis.open_from_handoff_payload(
        handoff,
        frame_source=host.get_frame_source(),
        sync_emitter=emitted.append,
    )
    assert open_result["ok"] is True

    analysis.seg_state.masks_cache[3] = np.ones((64, 64), dtype=bool)
    sync_payload = analysis.emit_host_sync(ui_hints={"last_frame": 3, "active_tool": "select"})
    assert sync_payload is not None
    assert sync_payload["event_id"] == event.event_id

    apply_result = host.apply_analysis_sync(sync_payload)
    assert apply_result["ok"] is True
    assert apply_result["normalized"]["event_id"] == event.event_id
    assert host.session.state().dirty is True


def test_vertical_slice_stack_mismatch_rejected() -> None:
    host = BrowserController()
    host.on_stack_loaded(FakeReader(), FakeStackInfo("/tmp/in_a"))
    event = host.create_event(start_idx=2, end_idx=5, frame_count=8)
    host.set_active_event(event.event_id)

    handoff = host.handoff.selected_event_payload()
    analysis = _analysis_controller()
    analysis.open_from_handoff_payload(handoff, frame_source=host.get_frame_source())
    analysis.seg_state.masks_cache[3] = np.ones((64, 64), dtype=bool)
    sync_payload = analysis.build_host_sync_payload(ui_hints={"last_frame": 3, "active_tool": "select"})
    assert sync_payload is not None

    sync_payload["stack_id"] = "stack_wrong"
    rejected = host.apply_analysis_sync(sync_payload)
    assert rejected["ok"] is False
    assert rejected["code"] == ValidatorErrorCode.STACK_MISMATCH


def test_vertical_slice_rejects_payload_from_previous_project_context() -> None:
    host = BrowserController()
    host.on_stack_loaded(FakeReader(), FakeStackInfo("/tmp/in_a"))
    event_a = host.create_event(start_idx=2, end_idx=5, frame_count=8)
    host.set_active_event(event_a.event_id)
    handoff_a = host.handoff.selected_event_payload()

    host.on_stack_loaded(FakeReader(), FakeStackInfo("/tmp/in_b"))
    event_b = host.create_event(start_idx=1, end_idx=4, frame_count=8)
    host.set_active_event(event_b.event_id)
    handoff_b = host.handoff.selected_event_payload()
    assert handoff_a["stack"]["stack_id"] != handoff_b["stack"]["stack_id"]

    analysis = _analysis_controller()
    analysis.open_from_handoff_payload(handoff_a, frame_source=host.get_frame_source())
    analysis.seg_state.masks_cache[3] = np.ones((64, 64), dtype=bool)
    sync_payload = analysis.build_host_sync_payload(ui_hints={"last_frame": 3, "active_tool": "select"})
    assert sync_payload is not None

    rejected = host.apply_analysis_sync(sync_payload)
    assert rejected["ok"] is False
    assert rejected["code"] == ValidatorErrorCode.SESSION_MISMATCH


def test_import_workflow_updates_host_analysis_sidecar_immediately() -> None:
    host = BrowserController()
    host.on_stack_loaded(FakeReader(), FakeStackInfo("/tmp/in_a"))
    event = host.create_event(start_idx=2, end_idx=5, frame_count=8)
    host.set_active_event(event.event_id)

    context = host.host_context_for_event(event.event_id)
    context["event"]["flags"] = {
        "analysis_scope_start_idx": 2,
        "analysis_scope_end_idx": 5,
        "analysis_local_event_start_idx": 0,
        "analysis_local_event_end_idx": 3,
    }

    scoped_source = EventScopedFrameSource(host.get_frame_source(), 2, 5)
    analysis_workspace = AnalysisWorkspaceController(
        session_service=ProjectSessionService(),
        session_state=SessionState(),
        seg_state=SegmentationState(),
    )
    analysis_workspace.bind_frame_source(scoped_source)
    open_result = analysis_workspace.open_from_host_event_context(context, frame_source=scoped_source)
    assert open_result["ok"] is True

    class _App:
        def __init__(self) -> None:
            self.root = object()
            self.frames_raw = [np.zeros((64, 64), dtype=np.uint8) for _ in range(4)]
            self.frames_sub_viz = list(self.frames_raw)
            self.mask_import_dialog = _DialogStub(
                paths=["mask_a.tif", "mask_b.tif"],
                masks=[np.ones((64, 64), dtype=bool), np.ones((64, 64), dtype=bool)],
                offset=1,
            )
            self.project_session_service = analysis_workspace.session_service
            self.analysis_workspace = analysis_workspace
            self.event_records = analysis_workspace.session_state.event_records
            self.active_event_id = event.event_id
            self.seg_state = analysis_workspace.seg_state
            self._host_mode = True
            self._host_analysis_updater = host.apply_direct_analysis_update
            self._host_sync_result_notifier = None
            self.lbl_status = None
            self.project_dirty = False
            self.sync_reasons = []
            self.host_mode_controller = AnalysisHostModeController(self)

        def _get_frame_count(self):
            return len(self.frames_raw)

        def _get_frame_shape(self):
            return tuple(np.asarray(self.frames_raw[0]).shape[:2]) if self.frames_raw else (0, 0)

        def _get_raw_frame(self, idx):
            return self.frames_raw[int(idx)]

        def _get_visual_frame(self, idx):
            return self.frames_sub_viz[int(idx)]

        def _collect_nonempty_final_mask_frames(self):
            return {1, 2}

        def _set_propagated_frames(self, *_args, **_kwargs):
            return None

        def update_display(self):
            return None

        def _mark_project_dirty(self, reason=""):
            self.project_dirty = True

        def _emit_host_sync(self, reason):
            self.sync_reasons.append(str(reason))
            return self.host_mode_controller.emit_host_sync(reason)

        def _collect_current_metrics_settings(self):
            return {}

        def log_debug(self, *_args, **_kwargs):
            return None

        def log_warn(self, *_args, **_kwargs):
            return None

    app = _App()

    with (
        patch("swell.analysis.core.mask_import_workflow.messagebox.showinfo"),
        patch("swell.analysis.core.mask_import_workflow.messagebox.showwarning"),
    ):
        mask_import_workflow.import_external_masks(app)

    assert app.sync_reasons == ["import_external_masks"]
    sidecar = host.session.load_analysis_sidecar(event.event_id)
    assert sidecar is not None
    assert sidecar["masks_committed"].shape == (4, 64, 64)
    assert bool(np.any(sidecar["masks_committed"][1]))
    assert bool(np.any(sidecar["masks_committed"][2]))
