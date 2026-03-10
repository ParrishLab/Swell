from __future__ import annotations

from pathlib import Path

import numpy as np

from sdapp.host.browser_controller import BrowserController
from sdapp.host.config import FrameRef


class _FakeReader:
    def __init__(self, h: int = 8, w: int = 9, n: int = 4, prefix: str = "a") -> None:
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
        self.frame_count = 4
        self.frame_height = 8
        self.frame_width = 9
        self.dtype = "uint8"


def test_sd_set_create_select_and_event_isolation() -> None:
    c = BrowserController()
    c.on_stack_loaded(_FakeReader(prefix="set1"), _FakeStackInfo("/tmp/in_set1"))
    first_set = c.session.state().active_sd_set_id
    e1 = c.create_event(start_idx=0, end_idx=1, frame_count=4)
    c.set_active_event(e1.event_id)

    c.on_stack_loaded(_FakeReader(prefix="set2"), _FakeStackInfo("/tmp/in_set2"))
    second_set = c.session.state().active_sd_set_id
    assert second_set != first_set
    e2 = c.create_event(start_idx=1, end_idx=2, frame_count=4)
    c.set_active_event(e2.event_id)

    assert c.select_sd_set(first_set) is True
    events_first = c.list_events()
    assert len(events_first) == 1
    assert events_first[0].event_id == e1.event_id

    assert c.select_sd_set(second_set) is True
    events_second = c.list_events()
    assert len(events_second) == 1
    assert events_second[0].event_id == e2.event_id


def test_handoff_uses_active_set_context() -> None:
    c = BrowserController()
    c.on_stack_loaded(_FakeReader(prefix="set1"), _FakeStackInfo("/tmp/in_set1"))
    first_set = c.session.state().active_sd_set_id
    e1 = c.create_event(start_idx=0, end_idx=1, frame_count=4)
    c.set_active_event(e1.event_id)
    handoff_first = c.handoff.selected_event_payload()
    assert handoff_first["session"]["metadata"]["active_sd_set_id"] == first_set
    first_stack = handoff_first["stack"]["stack_id"]

    c.on_stack_loaded(_FakeReader(prefix="set2"), _FakeStackInfo("/tmp/in_set2"))
    second_set = c.session.state().active_sd_set_id
    e2 = c.create_event(start_idx=1, end_idx=2, frame_count=4)
    c.set_active_event(e2.event_id)
    handoff_second = c.handoff.selected_event_payload()
    assert handoff_second["session"]["metadata"]["active_sd_set_id"] == second_set
    assert handoff_second["stack"]["stack_id"] != first_stack


def test_sd_set_rename_and_delete() -> None:
    c = BrowserController()
    c.on_stack_loaded(_FakeReader(prefix="set1"), _FakeStackInfo("/tmp/in_set1"))
    first_set = c.get_active_sd_set_id()
    c.on_stack_loaded(_FakeReader(prefix="set2"), _FakeStackInfo("/tmp/in_set2"))
    second_set = c.get_active_sd_set_id()

    assert c.rename_sd_set(second_set, "Second Set")
    listed = {s.sd_set_id: s for s in c.list_sd_sets()}
    assert listed[second_set].metadata.get("display_name") == "Second Set"

    assert c.delete_sd_set(first_set) is True
    remaining = c.list_sd_sets()
    assert len(remaining) == 1
    assert remaining[0].sd_set_id == second_set
