from __future__ import annotations

import json
import io
import zipfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from host_models import EventMeta, StackRef
from project_session_service import ProjectSessionService


def _stack_ref(input_dir: str, frame_count: int = 10) -> StackRef:
    return StackRef(
        input_dir=input_dir,
        frame_count=frame_count,
        frame_height=4,
        frame_width=5,
        dtype="uint8",
    )


def test_project_session_roundtrip_multiset_sdproj(tmp_path: Path) -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a", frame_count=10))
    svc.upsert_event_meta(EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=3, flags={}))
    svc.set_events([EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=3, flags={})], "event_0001")
    first_set = svc.state().active_sd_set_id

    second_set = svc.create_sd_set(_stack_ref("/tmp/in_b", frame_count=8))
    assert second_set != first_set
    svc.upsert_event_meta(EventMeta(event_id="event_0001", label="E1b", start_idx=0, end_idx=2, flags={}))
    svc.set_events([EventMeta(event_id="event_0001", label="E1b", start_idx=0, end_idx=2, flags={})], "event_0001")

    out = tmp_path / "test.sdproj"
    svc.save_project(out)

    reopened = ProjectSessionService()
    state = reopened.open_project(out)
    assert state.project_path == str(out.resolve())
    assert len(state.sd_sets) == 2
    assert state.active_sd_set_id == second_set
    assert state.sd_sets[second_set].stack_ref is not None
    assert state.sd_sets[second_set].stack_ref.frame_count == 8


def test_set_lifecycle_and_selection() -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a"))
    first = svc.state().active_sd_set_id
    second = svc.create_sd_set(_stack_ref("/tmp/in_b"))
    assert svc.select_sd_set(first) is True
    assert svc.state().active_sd_set_id == first
    assert svc.delete_sd_set(second) is True
    assert len(svc.list_sd_sets()) == 1


def test_analysis_sidecar_is_set_scoped() -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a"))
    first = svc.state().active_sd_set_id
    svc.upsert_analysis_sidecar("event_0001", {"prompts": {"blob_ref": "blob://a"}})

    second = svc.create_sd_set(_stack_ref("/tmp/in_b"))
    svc.upsert_analysis_sidecar("event_0001", {"prompts": {"blob_ref": "blob://b"}})
    assert svc.load_analysis_sidecar("event_0001")["prompts"]["blob_ref"] == "blob://b"

    assert svc.select_sd_set(first) is True
    assert svc.load_analysis_sidecar("event_0001")["prompts"]["blob_ref"] == "blob://a"
    assert svc.select_sd_set(second) is True


def test_open_project_rejects_unknown_persistence_owner(tmp_path: Path) -> None:
    out = tmp_path / "bad_owner.sdproj"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "active_sd_set_id": None,
                    "metadata": {},
                    "persistence": {"owner": "unsupported_owner"},
                    "sd_sets": [],
                }
            ),
        )
    svc = ProjectSessionService()
    with pytest.raises(ValueError):
        svc.open_project(out)


def test_open_legacy_sdsession_is_migrated_and_saved_as_sdproj(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.sdsession"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stack_ref": asdict(_stack_ref("/tmp/in_legacy", frame_count=3)),
                "active_event_id": "event_0001",
                "events": [{"event_id": "event_0001", "label": "E", "start_idx": 0, "end_idx": 2, "flags": {}}],
                "metadata": {},
                "analysis_sidecar": {"event_0001": {"prompts": {"blob_ref": "blob://legacy"}}},
            }
        ),
        encoding="utf-8",
    )
    svc = ProjectSessionService()
    state = svc.open_project(legacy)
    assert len(state.sd_sets) == 1
    save_target = tmp_path / "migrated.sdsession"
    saved = svc.save_project(save_target)
    assert saved.project_path.endswith(".sdproj")
    assert Path(saved.project_path).exists()


def test_open_legacy_single_sdproj_is_migrated(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy_single.sdproj"
    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "project_state.json",
            json.dumps(
                {
                    "schema_version": 3,
                    "ui_state": {"active_event_id": "sd_event_001"},
                    "events": [
                        {
                            "id": "sd_event_001",
                            "label": "SD Event 1",
                            "frame_start": 0,
                            "frame_end": 1,
                            "masks_ref": "events/sd_event_001/masks.npz",
                            "prompts_ref": "events/sd_event_001/prompts.json",
                        }
                    ],
                }
            ),
        )
        zf.writestr("images.json", json.dumps({"images": [{"absolute_path": "/tmp/legacy/a.tif"}]}))
        arr = np.zeros((2, 4, 5), dtype=np.uint8)
        buf = io.BytesIO()
        np.savez_compressed(buf, masks=arr)
        zf.writestr("events/sd_event_001/masks.npz", buf.getvalue())
        zf.writestr("events/sd_event_001/prompts.json", json.dumps({}))

    svc = ProjectSessionService()
    state = svc.open_project(legacy)
    assert len(state.sd_sets) == 1
    active = state.sd_sets[state.active_sd_set_id]
    assert active.stack_ref is not None
    assert active.stack_ref.frame_count >= 2
    assert len(active.events) == 1
