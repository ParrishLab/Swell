from __future__ import annotations

from pathlib import Path

import numpy as np

from sdapp.host.browser_controller import BrowserController
from sdapp.host.config import FrameRef


class _FakeReader:
    def __init__(self) -> None:
        self._frames = [np.zeros((8, 9), dtype=np.uint8) for _ in range(6)]
        self._refs = [
            FrameRef(i, source_path=Path(f"/tmp/f_{i}.tif"), page_index=None, source_ext=".tif", frame_name=f"f_{i}.tif")
            for i in range(6)
        ]

    def get_frame_count(self) -> int:
        return len(self._frames)

    def get_stack_info(self):
        class _Info:
            frame_height = 8
            frame_width = 9

        return _Info()

    def get_frame_name(self, idx: int) -> str:
        return self._refs[idx].frame_name

    def get_frame_ref(self, idx: int):
        return self._refs[idx]

    def read_frame(self, idx: int, use_cache: bool = True):  # noqa: ARG002
        return self._frames[idx]


class _FakeStackInfo:
    def __init__(self, input_dir: str = "/tmp/in") -> None:
        self.input_dir = input_dir
        self.frame_count = 6
        self.frame_height = 8
        self.frame_width = 9
        self.dtype = "uint8"


def test_apply_direct_analysis_update_routes_by_payload_event_id() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    e1 = host.create_event(start_idx=0, end_idx=1, frame_count=6)
    e2 = host.create_event(start_idx=2, end_idx=4, frame_count=6)

    result = host.apply_direct_analysis_update(
        {
            "event_id": e2.event_id,
            "analysis": {"prompts": {"points": [{"frame": 3, "x": 1, "y": 2}]}},
        }
    )
    assert result["ok"] is True
    state = host.session.state()
    assert e2.event_id in state.analysis_sidecar
    assert e1.event_id not in state.analysis_sidecar


def test_apply_direct_analysis_update_rejects_missing_event_id() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    host.create_event(start_idx=0, end_idx=1, frame_count=6)

    result = host.apply_direct_analysis_update({"analysis": {"prompts": {}}})
    assert result["ok"] is False
    assert result["code"] == "PAYLOAD_INVALID"
