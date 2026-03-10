from __future__ import annotations

import io
import json
import zipfile

import numpy as np

from sdapp.shared.persistence import UnifiedProjectStore


def test_legacy_sdsession_migrates_to_multi_sd_state(tmp_path) -> None:
    payload = {
        "stack_ref": {
            "input_dir": "/tmp/in",
            "frame_count": 5,
            "frame_height": 16,
            "frame_width": 16,
            "dtype": "uint8",
        },
        "events": [
            {"event_id": "event_0001", "label": "E1", "start_idx": 1, "end_idx": 3, "flags": {}},
        ],
        "active_event_id": "event_0001",
        "analysis_sidecar": {"event_0001": {"prompts": {"points": []}}},
        "metadata": {"session_id": "session_abc"},
    }
    src = tmp_path / "legacy.sdsession"
    src.write_text(json.dumps(payload), encoding="utf-8")
    store = UnifiedProjectStore()
    state = store.load_legacy_sdsession(src)
    assert state.active_sd_set_id == "sd_set_0001"
    assert "sd_set_0001" in state.sd_sets
    assert state.sd_sets["sd_set_0001"].active_event_id == "event_0001"


def test_legacy_portable_sdproj_migrates(tmp_path) -> None:
    src = tmp_path / "legacy_portable.sdproj"
    masks = np.zeros((4, 8, 8), dtype=np.uint8)
    state = {
        "events": [
            {
                "id": "sd_event_001",
                "label": "Event 1",
                "frame_start": 0,
                "frame_end": 3,
                "masks_ref": "events/sd_event_001/masks.npz",
            }
        ],
        "ui_state": {"active_event_id": "sd_event_001"},
    }
    images = {"images": [{"id": "image_1", "absolute_path": "/tmp/frame_0001.tif"}]}
    mem = io.BytesIO()
    np.savez_compressed(mem, masks=masks)
    with zipfile.ZipFile(src, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project_state.json", json.dumps(state))
        zf.writestr("images.json", json.dumps(images))
        zf.writestr("events/sd_event_001/masks.npz", mem.getvalue())

    store = UnifiedProjectStore()
    migrated = store.load_legacy_portable_sdproj(src)
    assert migrated.active_sd_set_id == "sd_set_0001"
    sd_set = migrated.sd_sets["sd_set_0001"]
    assert sd_set.stack_ref is not None
    assert sd_set.stack_ref.frame_count == 4
    assert sd_set.active_event_id == "sd_event_001"
