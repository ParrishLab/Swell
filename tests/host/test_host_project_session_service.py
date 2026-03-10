from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from sdapp.host.host_models import EventMeta, StackRef
from sdapp.host.project_session_service import ProjectSessionService


def _stack_ref(input_dir: str, frame_count: int = 10) -> StackRef:
    return StackRef(
        input_dir=input_dir,
        frame_count=frame_count,
        frame_height=4,
        frame_width=5,
        dtype="uint8",
    )


def test_project_session_roundtrip_single_stack_sdproj(tmp_path: Path) -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a", frame_count=10))
    svc.set_events(
        [
            EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=3, flags={}),
            EventMeta(event_id="event_0002", label="E2", start_idx=4, end_idx=7, flags={}),
        ],
        "event_0002",
    )
    svc.upsert_analysis_sidecar(
        "event_0002",
        {
            "prompts": {"points": [{"frame": 5, "x": 2, "y": 3}]},
            "masks_committed": np.zeros((4, 4, 5), dtype=np.uint8),
        },
    )

    out = tmp_path / "test.sdproj"
    svc.save_project(out)

    reopened = ProjectSessionService()
    state = reopened.open_project(out)
    assert state.project_path == str(out.resolve())
    assert state.stack_ref is not None
    assert state.stack_ref.frame_count == 10
    assert [e.event_id for e in state.events] == ["event_0001", "event_0002"]
    assert state.active_event_id == "event_0002"
    assert state.analysis_sidecar["event_0002"]["prompts"]["points"][0]["frame"] == 5


def test_analysis_sidecar_is_event_scoped() -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a"))
    svc.set_events(
        [
            EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=2, flags={}),
            EventMeta(event_id="event_0002", label="E2", start_idx=3, end_idx=4, flags={}),
        ],
        "event_0001",
    )
    svc.upsert_analysis_sidecar("event_0001", {"prompts": {"blob_ref": "blob://a"}})
    svc.upsert_analysis_sidecar("event_0002", {"prompts": {"blob_ref": "blob://b"}})

    assert svc.load_analysis_sidecar("event_0001")["prompts"]["blob_ref"] == "blob://a"
    assert svc.load_analysis_sidecar("event_0002")["prompts"]["blob_ref"] == "blob://b"


def test_open_project_rejects_unknown_persistence_owner(tmp_path: Path) -> None:
    out = tmp_path / "bad_owner.sdproj"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 2,
                    "active_event_id": None,
                    "metadata": {},
                    "persistence": {"owner": "unsupported_owner"},
                }
            ),
        )
    svc = ProjectSessionService()
    with pytest.raises(ValueError):
        svc.open_project(out)
