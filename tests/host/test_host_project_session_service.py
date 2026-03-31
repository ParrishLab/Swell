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


def test_load_analysis_sidecar_preserves_dict_masks() -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a"))
    svc.set_events([EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=2, flags={})], "event_0001")
    svc.upsert_analysis_sidecar(
        "event_0001",
        {"masks_committed": {"3": np.ones((4, 5), dtype=np.uint8)}},
    )

    loaded = svc.load_analysis_sidecar("event_0001")

    assert loaded is not None
    masks = loaded.get("masks_committed")
    assert isinstance(masks, dict)
    assert "3" in masks
    assert bool(np.any(np.asarray(masks["3"])))


def test_load_analysis_sidecar_returns_defensive_copy() -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a"))
    svc.set_events([EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=2, flags={})], "event_0001")
    svc.upsert_analysis_sidecar(
        "event_0001",
        {
            "prompts": {"points": [{"frame": 1, "x": 2, "y": 3}]},
            "masks_committed": np.zeros((2, 4, 5), dtype=np.uint8),
        },
    )

    loaded = svc.load_analysis_sidecar("event_0001")

    assert loaded is not None
    loaded["prompts"]["points"][0]["frame"] = 9
    loaded["masks_committed"][0, 0, 0] = 1

    reread = svc.load_analysis_sidecar("event_0001")
    assert reread is not None
    assert reread["prompts"]["points"][0]["frame"] == 1
    assert int(reread["masks_committed"][0, 0, 0]) == 0


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


def test_global_metrics_defaults_roundtrip_and_materialization(tmp_path: Path) -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a", frame_count=10))
    svc.set_events(
        [
            EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=3, flags={}),
            EventMeta(event_id="event_0002", label="E2", start_idx=4, end_idx=7, flags={}),
        ],
        "event_0001",
    )
    roi_mask = np.zeros((4, 5), dtype=bool)
    roi_mask[1:3, 1:4] = True
    defaults = {
        "frames_per_sec": 2.5,
        "scale_px_per_mm": 6.0,
        "roi_points": [[1.0, 1.0], [3.0, 1.0], [3.0, 2.0], [1.0, 2.0]],
        "roi_mask": roi_mask,
    }
    svc.set_global_metrics_defaults(defaults)
    applied = svc.materialize_metrics_defaults_to_events()
    assert applied == 2

    out = tmp_path / "metrics_defaults.sdproj"
    svc.save_project(out)

    reopened = ProjectSessionService()
    reopened.open_project(out)
    loaded_defaults = reopened.get_global_metrics_defaults()
    assert float(loaded_defaults["frames_per_sec"]) == 2.5
    assert float(loaded_defaults["scale_px_per_mm"]) == 6.0
    assert np.array_equal(np.asarray(loaded_defaults["roi_mask"], dtype=bool), roi_mask)
    event_metrics = reopened.load_event_metrics_settings("event_0001")
    assert event_metrics is not None
    assert float(event_metrics["frames_per_sec"]) == 2.5
    assert np.array_equal(np.asarray(event_metrics["roi_mask"], dtype=bool), roi_mask)


def test_materialization_does_not_overwrite_existing_local_metrics() -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a", frame_count=10))
    svc.set_events(
        [
            EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=3, flags={}),
            EventMeta(event_id="event_0002", label="E2", start_idx=4, end_idx=7, flags={}),
        ],
        "event_0001",
    )
    global_roi = np.zeros((4, 5), dtype=bool)
    global_roi[0:2, 0:2] = True
    local_roi = np.zeros((4, 5), dtype=bool)
    local_roi[2:4, 2:5] = True
    svc.set_global_metrics_defaults(
        {
            "frames_per_sec": 3.0,
            "scale_px_per_mm": 7.5,
            "roi_points": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]],
            "roi_mask": global_roi,
        }
    )
    svc.upsert_event_metrics_settings(
        "event_0001",
        {
            "scale_px_per_mm": 12.0,
            "roi_points": [[2.0, 2.0], [4.0, 2.0], [4.0, 4.0]],
            "roi_mask": local_roi,
        },
        merge_missing_only=False,
    )

    applied = svc.materialize_metrics_defaults_to_events()
    assert applied >= 1
    event_1_metrics = svc.load_event_metrics_settings("event_0001")
    assert event_1_metrics is not None
    assert float(event_1_metrics["scale_px_per_mm"]) == 12.0
    assert float(event_1_metrics["frames_per_sec"]) == 3.0
    assert np.array_equal(np.asarray(event_1_metrics["roi_mask"], dtype=bool), local_roi)


def test_dc_trace_attachment_roundtrip(tmp_path: Path) -> None:
    svc = ProjectSessionService()
    svc.new_project(_stack_ref("/tmp/in_a", frame_count=10))
    attachment = {
        "source_type": "wavesurfer_h5",
        "source_path": "/tmp/dc_trace.h5",
        "channel_index": 1,
        "channel_name": "LFP 2",
        "sample_rate_hz": 200.0,
        "unit": "mV",
        "alignment": {
            "mode": "manual_offset",
            "video_t0_s": 0.0,
            "trace_t0_s": 0.0,
            "offset_s": 1.75,
            "drift_ppm": None,
            "notes": "",
        },
        "metadata": {"sweep_count": 2, "duration_s": 18.0},
    }
    svc.set_dc_trace_attachment(attachment)

    out = tmp_path / "dc_trace_roundtrip.sdproj"
    svc.save_project(out)

    reopened = ProjectSessionService()
    reopened.open_project(out)
    loaded = reopened.get_dc_trace_attachment()

    assert loaded is not None
    assert loaded["source_type"] == "wavesurfer_h5"
    assert loaded["channel_index"] == 1
    assert float(loaded["sample_rate_hz"]) == 200.0
    assert float(dict(loaded["alignment"])["offset_s"]) == 1.75
