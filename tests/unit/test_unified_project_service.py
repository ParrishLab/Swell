from __future__ import annotations

from pathlib import Path

import numpy as np

from swell.shared.models import EventMeta, StackRef, UnifiedProjectState
from swell.shared.services import UnifiedProjectService


def _stack_ref(tag: str) -> StackRef:
    return StackRef(
        input_dir=f"/tmp/{tag}",
        frame_count=10,
        frame_height=32,
        frame_width=32,
        dtype="uint8",
    )


def test_unified_service_event_crud_single_stack() -> None:
    service = UnifiedProjectService()
    service.new_project(_stack_ref("project"))

    service.upsert_event(EventMeta(event_id="event_0001", label="A", start_idx=1, end_idx=4, flags={}))
    service.upsert_event(EventMeta(event_id="event_0002", label="B", start_idx=2, end_idx=5, flags={}))
    service.set_active_event("event_0002")

    events = service.list_events()
    assert [e.event_id for e in events] == ["event_0001", "event_0002"]
    assert service.state().active_event_id == "event_0002"

    service.delete_event("event_0001")
    remaining = service.list_events()
    assert [e.event_id for e in remaining] == ["event_0002"]


def test_unified_service_orders_events_chronologically() -> None:
    service = UnifiedProjectService()
    service.new_project(_stack_ref("project"))

    service.upsert_event(EventMeta(event_id="event_0002", label="B", start_idx=8, end_idx=9, flags={}))
    service.upsert_event(EventMeta(event_id="event_0001", label="A", start_idx=2, end_idx=5, flags={}))
    service.upsert_event(EventMeta(event_id="event_0003", label="C", start_idx=6, end_idx=7, flags={}))

    assert [event.event_id for event in service.list_events()] == ["event_0001", "event_0003", "event_0002"]

    service.upsert_event(EventMeta(event_id="event_0002", label="B", start_idx=0, end_idx=1, flags={}))

    assert [event.event_id for event in service.list_events()] == ["event_0002", "event_0001", "event_0003"]


def test_unified_service_defaults_active_event_to_first_chronological_event() -> None:
    service = UnifiedProjectService()
    service.replace_state(
        UnifiedProjectState(
            stack_ref=_stack_ref("project"),
            events=[
                EventMeta(event_id="event_0002", label="B", start_idx=8, end_idx=9, flags={}),
                EventMeta(event_id="event_0001", label="A", start_idx=2, end_idx=5, flags={}),
            ],
            active_event_id=None,
            analysis_sidecar={},
            metadata={},
        ),
        mark_dirty=False,
    )

    assert [event.event_id for event in service.list_events()] == ["event_0001", "event_0002"]
    assert service.state().active_event_id == "event_0001"


def test_unified_service_analysis_updates_and_subscribe() -> None:
    service = UnifiedProjectService()
    service.new_project(_stack_ref("set"))
    service.upsert_event(EventMeta(event_id="event_0001", label="E", start_idx=0, end_idx=3, flags={}))

    updates: list[tuple[str, dict]] = []
    service.subscribe(lambda event, payload: updates.append((event, payload)))

    service.update_event_analysis(
        "event_0001",
        {
            "prompts": {"points": []},
            "masks_committed": np.zeros((4, 32, 32), dtype=np.uint8),
            "propagation_completed": True,
        },
    )
    analysis = service.get_event_analysis("event_0001")
    assert analysis is not None
    assert analysis.prompts == {"points": []}
    assert analysis.masks_committed is not None
    assert analysis.masks_committed.shape == (4, 32, 32)
    assert any(name == "event_analysis_updated" for name, _ in updates)


def test_unified_service_analysis_update_copies_mutable_inputs() -> None:
    service = UnifiedProjectService()
    service.new_project(_stack_ref("set"))
    service.upsert_event(EventMeta(event_id="event_0001", label="E", start_idx=0, end_idx=3, flags={}))

    prompts = {"points": [{"frame": 0, "x": 1, "y": 2}]}
    masks = np.zeros((4, 32, 32), dtype=np.uint8)
    service.update_event_analysis(
        "event_0001",
        {
            "prompts": prompts,
            "masks_committed": masks,
        },
    )

    prompts["points"][0]["frame"] = 99
    masks[0, 0, 0] = 1

    analysis = service.get_event_analysis("event_0001")
    assert analysis is not None
    assert analysis.prompts["points"][0]["frame"] == 0
    assert int(analysis.masks_committed[0, 0, 0]) == 0


def test_unified_service_analysis_reads_return_defensive_copies() -> None:
    service = UnifiedProjectService()
    service.new_project(_stack_ref("set"))
    service.upsert_event(EventMeta(event_id="event_0001", label="E", start_idx=0, end_idx=3, flags={}))
    service.update_event_analysis(
        "event_0001",
        {
            "prompts": {"points": [{"frame": 1, "x": 2, "y": 3}]},
            "masks_committed": np.zeros((4, 32, 32), dtype=np.uint8),
        },
    )

    analysis = service.get_event_analysis("event_0001")
    assert analysis is not None
    analysis.prompts["points"][0]["frame"] = 12
    analysis.masks_committed[0, 0, 0] = 1

    reread = service.get_event_analysis("event_0001")
    assert reread is not None
    assert reread.prompts["points"][0]["frame"] == 1
    assert int(reread.masks_committed[0, 0, 0]) == 0


def test_unified_service_save_project_defaults_to_input_folder_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    service = UnifiedProjectService()
    service.new_project(_stack_ref("input_folder"))

    state = service.save_project()

    assert state.project_path == "input_folder.swell"
    assert (tmp_path / "input_folder.swell").exists()


def test_unified_service_normal_save_rejects_missing_existing_project(tmp_path: Path) -> None:
    service = UnifiedProjectService()
    service.new_project(_stack_ref("input_folder"))
    original = tmp_path / "original.swell"
    renamed = tmp_path / "renamed.swell"
    service.save_project(str(original))
    original.rename(renamed)

    try:
        service.save_project()
    except FileNotFoundError as exc:
        assert "no longer exists" in str(exc)
    else:
        raise AssertionError("expected missing project path to be rejected")

    assert renamed.exists()
    assert not original.exists()


def test_unified_service_preserves_analysis_frame_origins_on_save_load(tmp_path: Path) -> None:
    service = UnifiedProjectService()
    service.new_project(_stack_ref("set"))
    service.upsert_event(EventMeta(event_id="event_0001", label="E", start_idx=2, end_idx=4, flags={}))
    service.update_event_analysis(
        "event_0001",
        {
            "prompts": {"event_id": "event_0001", "frames": {}, "persistent_regions": []},
            "prompts_frame_origin": "analysis_scope_local",
            "masks_committed": np.zeros((4, 32, 32), dtype=np.uint8),
            "masks_committed_frame_origin": "analysis_scope_local",
            "masks_draft": np.zeros((4, 32, 32), dtype=np.uint8),
            "masks_draft_frame_origin": "analysis_scope_local",
        },
    )
    path = tmp_path / "origins.swell"

    service.save_project(str(path))
    loaded = UnifiedProjectService()
    loaded.open_project(str(path))
    payload = loaded.get_event_analysis_payload("event_0001")

    assert payload is not None
    assert payload["prompts_frame_origin"] == "analysis_scope_local"
    assert payload["masks_committed_frame_origin"] == "analysis_scope_local"
    assert payload["masks_draft_frame_origin"] == "analysis_scope_local"
