from __future__ import annotations

import io
import json
import zipfile

import numpy as np

from sdapp.shared.models import EventMeta, StackRef, UnifiedProjectState
from sdapp.shared.persistence import UnifiedProjectStore


def _state() -> UnifiedProjectState:
    return UnifiedProjectState(
        stack_ref=StackRef(
            input_dir="/tmp/in",
            frame_count=5,
            frame_height=16,
            frame_width=16,
            dtype="uint8",
        ),
        events=[EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=3, flags={})],
        active_event_id="event_0001",
        analysis_sidecar={
            "event_0001": {
                "prompts": {"points": []},
                "masks_committed": np.zeros((3, 16, 16), dtype=np.uint8),
            }
        },
        metadata={"session_id": "session_abc"},
    )


def test_canonical_sdproj_layout_is_single_stack(tmp_path) -> None:
    store = UnifiedProjectStore()
    out = tmp_path / "single_stack.sdproj"
    store.save(out, _state())

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "stack.json" in names
        assert "events.json" in names
        assert "analysis_sidecar.json" in names
        assert "events/event_0001/prompts.json" in names
        assert "events/event_0001/masks.npz" in names
        assert all(not name.startswith("sd_sets/") for name in names)

        events = json.loads(zf.read("events.json").decode("utf-8"))
        assert events[0]["global_start_idx"] == 1
        assert events[0]["global_end_idx"] == 3


def test_canonical_store_roundtrip_preserves_analysis_payload(tmp_path) -> None:
    store = UnifiedProjectStore()
    out = tmp_path / "roundtrip.sdproj"
    store.save(out, _state())

    loaded = store.load(out)
    assert loaded.stack_ref is not None
    assert loaded.stack_ref.frame_count == 5
    assert loaded.active_event_id == "event_0001"
    assert len(loaded.events) == 1
    payload = loaded.analysis_sidecar["event_0001"]
    assert payload["prompts"] == {"points": []}
    assert payload["masks_committed"].shape == (3, 16, 16)
