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


def test_host_context_for_event_includes_project_path() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    event = host.create_event(start_idx=0, end_idx=1, frame_count=6)
    host.session.set_project_path("/tmp/active_project.sdproj")

    context = host.host_context_for_event(event.event_id)

    assert context["project_path"] is not None
    assert str(context["project_path"]).endswith("active_project.sdproj")


def test_host_context_preserves_dict_mask_payloads() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    event = host.create_event(start_idx=2, end_idx=4, frame_count=6)
    host.session.upsert_analysis_sidecar(
        event.event_id,
        {"masks_committed": {"3": np.ones((8, 9), dtype=np.uint8)}},
    )

    context = host.host_context_for_event(event.event_id)
    masks = dict(context["analysis_state"] or {}).get("masks_committed")

    assert isinstance(masks, dict)
    assert "3" in masks
    assert bool(np.any(np.asarray(masks["3"])))


def test_update_event_remaps_saved_analysis_sidecar_to_new_bounds() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    event = host.create_event(
        start_idx=2,
        end_idx=4,
        frame_count=6,
        flags={
            "baseline_pre_frames": 1,
            "analysis_scope_start_idx": 1,
            "analysis_scope_end_idx": 4,
            "analysis_local_event_start_idx": 1,
            "analysis_local_event_end_idx": 3,
        },
    )
    masks = np.zeros((4, 8, 9), dtype=np.uint8)
    masks[1] = 1
    host.session.upsert_analysis_sidecar(
        event.event_id,
        {
            "prompts": {"event_id": event.event_id, "frames": {"1": {"points": [{"x": 2, "y": 3, "label": 1}]}}},
            "masks_committed": masks,
        },
    )

    updated = host.update_event(
        event.event_id,
        start_idx=3,
        end_idx=5,
        label=event.label,
        frame_count=6,
    )
    context = host.host_context_for_event(updated.event_id)
    sidecar = dict(context["analysis_state"] or {})
    remapped_masks = np.asarray(sidecar["masks_committed"])

    assert int(updated.flags["analysis_scope_start_idx"]) == 2
    assert int(updated.flags["analysis_local_event_start_idx"]) == 1
    assert remapped_masks.shape == (4, 8, 9)
    assert bool(np.any(remapped_masks[0]))
    assert not bool(np.any(remapped_masks[1]))
    assert "0" in dict(sidecar["prompts"]["frames"])
    assert "1" not in dict(sidecar["prompts"]["frames"])


def test_update_event_remaps_legacy_event_local_sidecar_to_new_scope() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    event = host.create_event(
        start_idx=12,
        end_idx=15,
        frame_count=20,
        flags={
            "baseline_pre_frames": 2,
            "analysis_scope_start_idx": 10,
            "analysis_scope_end_idx": 15,
            "analysis_local_event_start_idx": 2,
            "analysis_local_event_end_idx": 5,
        },
    )
    legacy_masks = np.zeros((4, 8, 9), dtype=np.uint8)
    legacy_masks[0] = 1
    host.session.upsert_analysis_sidecar(
        event.event_id,
        {
            "prompts": {"event_id": event.event_id, "frames": {"0": {"points": [{"x": 2, "y": 3, "label": 1}]}}},
            "masks_committed": legacy_masks,
        },
    )

    updated = host.update_event(
        event.event_id,
        start_idx=13,
        end_idx=16,
        label=event.label,
        frame_count=20,
    )
    context = host.host_context_for_event(updated.event_id)
    sidecar = dict(context["analysis_state"] or {})
    remapped_masks = np.asarray(sidecar["masks_committed"])

    assert int(updated.flags["analysis_scope_start_idx"]) == 11
    assert sidecar["prompts_frame_origin"] == "analysis_scope_local"
    assert sidecar["masks_committed_frame_origin"] == "analysis_scope_local"
    assert remapped_masks.shape == (6, 8, 9)
    assert bool(np.any(remapped_masks[1]))
    assert "1" in dict(sidecar["prompts"]["frames"])


def test_create_event_materializes_global_metrics_defaults() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    host.set_global_metrics_defaults(
        {
            "frames_per_sec": 2.0,
            "scale_px_per_mm": 5.0,
            "roi_points": [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0], [1.0, 3.0]],
        }
    )

    event = host.create_event(start_idx=0, end_idx=1, frame_count=6)
    local = host.load_event_metrics_settings(event.event_id)

    assert local is not None
    assert float(local["frames_per_sec"]) == 2.0
    assert float(local["scale_px_per_mm"]) == 5.0
    assert len(local["roi_points"]) == 4


def test_host_context_for_event_prefers_local_metrics_over_global_defaults() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    host.set_global_metrics_defaults({"frames_per_sec": 1.0, "scale_px_per_mm": 4.0})
    event = host.create_event(start_idx=0, end_idx=1, frame_count=6)
    host.upsert_event_metrics_settings(event.event_id, {"scale_px_per_mm": 11.0}, merge_missing_only=False)

    context = host.host_context_for_event(event.event_id)
    metrics = context["metrics_settings"]
    local_metrics = context["local_metrics_settings"]

    assert float(metrics["frames_per_sec"]) == 1.0
    assert float(metrics["scale_px_per_mm"]) == 11.0
    assert float(local_metrics["scale_px_per_mm"]) == 11.0


def test_export_candidates_after_reopen_uses_field_mapping(tmp_path: Path) -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    created = host.create_event(start_idx=2, end_idx=4, frame_count=6)
    project_path = tmp_path / "export_after_reopen.sdproj"
    host.save_session(project_path)
    host.open_session(str(project_path))

    candidates = host.export_candidates([created.event_id])

    assert len(candidates) == 1
    assert candidates[0].event_id == created.event_id
    assert candidates[0].start_idx == 2
    assert candidates[0].end_idx == 4


def test_ensure_full_stack_analysis_event_creates_and_reuses_flagged_event() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())

    created = host.ensure_full_stack_analysis_event(frame_count=6)
    reused = host.ensure_full_stack_analysis_event(frame_count=6)

    assert created.event_id == reused.event_id
    assert created.event_id == "event_full_stack"
    assert created.label == "Full Stack Analysis"
    assert created.start_idx == 0
    assert created.end_idx == 5
    assert bool(created.flags.get("host_full_stack_event")) is True
    assert host.get_active_event_id() == created.event_id
    assert len(host.list_events()) == 1


def test_export_candidates_include_event_flags() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    event = host.create_event(
        start_idx=1,
        end_idx=3,
        frame_count=6,
        flags={"baseline_pre_frames": 2, "analysis_processing": {"smoothing": False}},
    )

    candidates = host.export_candidates([event.event_id])

    assert len(candidates) == 1
    assert int(candidates[0].flags["baseline_pre_frames"]) == 2
    assert bool(candidates[0].flags["analysis_processing"]["smoothing"]) is False


def test_export_candidates_include_visible_label() -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    event = host.create_event(start_idx=1, end_idx=3, frame_count=6, label="Visible Event")

    candidates = host.export_candidates([event.event_id])

    assert len(candidates) == 1
    assert candidates[0].event_id == event.event_id
    assert candidates[0].label == "Visible Event"


def test_full_stack_event_persists_after_save_reopen_and_can_export(tmp_path: Path) -> None:
    host = BrowserController()
    host.on_stack_loaded(_FakeReader(), _FakeStackInfo())

    created = host.ensure_full_stack_analysis_event(frame_count=6)
    project_path = tmp_path / "full_stack_export.sdproj"
    host.save_session(project_path)
    host.open_session(str(project_path))

    reopened = host.get_event("event_full_stack")
    candidates = host.export_candidates(["event_full_stack"])

    assert reopened is not None
    assert reopened.event_id == "event_full_stack"
    assert reopened.start_idx == 0
    assert reopened.end_idx == 5
    assert len(candidates) == 1
    assert candidates[0].event_id == "event_full_stack"
    assert candidates[0].start_idx == 0
    assert candidates[0].end_idx == 5
