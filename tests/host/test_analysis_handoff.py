from __future__ import annotations

import numpy as np
from pathlib import Path

from sdapp.host.browser_controller import BrowserController
from sdapp.host.config import FrameRef
from seam_contract import load_contract_fixture, validate_handoff_payload


class FakeReader:
    def __init__(self) -> None:
        self._frames = [np.zeros((4, 5), dtype=np.uint8), np.ones((4, 5), dtype=np.uint8)]
        self._refs = [
            FrameRef(0, source_path=Path("/tmp/a.tif"), page_index=None, source_ext=".tif", frame_name="a.tif"),
            FrameRef(1, source_path=Path("/tmp/b.tif"), page_index=None, source_ext=".tif", frame_name="b.tif"),
        ]

    def get_frame_count(self) -> int:
        return len(self._frames)

    def get_stack_info(self):
        class Info:
            frame_height = 4
            frame_width = 5

        return Info()

    def get_frame_name(self, idx: int) -> str:
        return self._refs[idx].frame_name

    def get_frame_ref(self, idx: int):
        return self._refs[idx]

    def read_frame(self, idx: int, use_cache: bool = True):  # noqa: ARG002
        return self._frames[idx]


class FakeStackInfo:
    input_dir = "/tmp/in"
    frame_count = 2
    frame_height = 4
    frame_width = 5
    dtype = "uint8"


def test_analysis_handoff_payload_contains_event_and_stack_context() -> None:
    c = BrowserController()
    c.on_stack_loaded(FakeReader(), FakeStackInfo())
    ev = c.create_event(start_idx=0, end_idx=1, frame_count=2)
    c.set_active_event(ev.event_id)

    payload = c.handoff.selected_event_payload()
    assert payload is not None
    assert payload["contract_version"] == 1
    assert payload["event"]["event_id"] == ev.event_id
    assert payload["event"]["start_idx"] == 0
    assert payload["stack"]["frame_count"] == 2
    assert payload["stack"]["capabilities"]["raw"] is True
    assert payload["stack"]["capabilities"]["subtracted"] is False
    assert payload["stack"]["capabilities"]["visual"] is False
    assert payload["session"]["active_event_id"] == ev.event_id
    assert payload["analysis_state_ref"]["storage"] == "host_session"


def test_contract_fixture_valid_handoff_passes() -> None:
    payload = load_contract_fixture("valid_handoff")
    result = validate_handoff_payload(payload)
    assert result["ok"] is True
