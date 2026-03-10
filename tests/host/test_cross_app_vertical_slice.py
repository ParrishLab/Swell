from __future__ import annotations

from pathlib import Path

import numpy as np

from sdapp.host.browser_controller import BrowserController
from sdapp.host.config import FrameRef
from seam_contract import ValidatorErrorCode


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
    from sdapp.analysis.core.analysis_workspace import AnalysisWorkspaceController
    from sdapp.analysis.core.project_session import ProjectSessionService
    from sdapp.analysis.core.seg_state import SegmentationState
    from sdapp.analysis.core.session_state import SessionState

    return AnalysisWorkspaceController(
        session_service=ProjectSessionService(),
        session_state=SessionState(),
        seg_state=SegmentationState(),
    )


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


def test_vertical_slice_rejects_payload_from_non_active_sd_set() -> None:
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
    assert rejected["code"] == ValidatorErrorCode.STACK_MISMATCH
