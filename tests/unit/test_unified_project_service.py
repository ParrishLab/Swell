from __future__ import annotations

import numpy as np

from sdapp.shared.models import EventMeta, StackRef
from sdapp.shared.services import UnifiedProjectService


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
