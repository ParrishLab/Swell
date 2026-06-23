from __future__ import annotations

from pathlib import Path

import numpy as np

from swell.host.browser_controller import BrowserController
from swell.host.config import FrameRef


class _FakeReader:
    def __init__(self, h: int = 8, w: int = 9, n: int = 6, prefix: str = "a") -> None:
        self._frames = [np.zeros((h, w), dtype=np.uint8) for _ in range(n)]
        self._refs = [
            FrameRef(i, source_path=Path(f"/tmp/{prefix}_{i}.tif"), page_index=None, source_ext=".tif", frame_name=f"{prefix}_{i}.tif")
            for i in range(n)
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
    def __init__(self, input_dir: str) -> None:
        self.input_dir = input_dir
        self.frame_count = 6
        self.frame_height = 8
        self.frame_width = 9
        self.dtype = "uint8"


def test_single_stack_event_lifecycle() -> None:
    c = BrowserController()
    c.on_stack_loaded(_FakeReader(prefix="stack"), _FakeStackInfo("/tmp/in_stack"))

    e1 = c.create_event(start_idx=0, end_idx=1, frame_count=6)
    e2 = c.create_event(start_idx=2, end_idx=4, frame_count=6)
    c.set_active_event(e1.event_id)

    events = c.list_events()
    assert [e.event_id for e in events] == [e1.event_id, e2.event_id]
    assert c.get_active_event_id() == e1.event_id

    removed = c.delete_events([e1.event_id])
    assert removed == 1
    remaining = c.list_events()
    assert [e.event_id for e in remaining] == [e2.event_id]


def test_handoff_tracks_active_event_context() -> None:
    c = BrowserController()
    c.on_stack_loaded(_FakeReader(prefix="stack"), _FakeStackInfo("/tmp/in_stack"))

    e1 = c.create_event(start_idx=0, end_idx=1, frame_count=6)
    e2 = c.create_event(start_idx=2, end_idx=4, frame_count=6)

    c.set_active_event(e1.event_id)
    handoff_first = c.handoff.selected_event_payload()
    assert handoff_first is not None
    assert handoff_first["event"]["event_id"] == e1.event_id

    c.set_active_event(e2.event_id)
    handoff_second = c.handoff.selected_event_payload()
    assert handoff_second is not None
    assert handoff_second["event"]["event_id"] == e2.event_id
    assert handoff_second["stack"]["stack_id"] == handoff_first["stack"]["stack_id"]
