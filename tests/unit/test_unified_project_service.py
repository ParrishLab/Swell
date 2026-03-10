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


def test_unified_service_sd_set_crud_and_event_isolation() -> None:
    service = UnifiedProjectService()
    first = service.create_sd_set(_stack_ref("a"))
    service.upsert_event(first, EventMeta(event_id="event_0001", label="A", start_idx=1, end_idx=4, flags={}))
    service.select_sd_set(first)
    service.set_active_event("event_0001", first)

    second = service.create_sd_set(_stack_ref("b"))
    service.upsert_event(second, EventMeta(event_id="event_0001", label="B", start_idx=2, end_idx=5, flags={}))
    service.set_active_event("event_0001", second)

    events_first = service.list_events(first)
    events_second = service.list_events(second)
    assert len(events_first) == 1
    assert len(events_second) == 1
    assert events_first[0].label == "A"
    assert events_second[0].label == "B"

    assert service.delete_sd_set(second) is True
    assert service.get_active_sd_set_id() == first


def test_unified_service_analysis_updates_and_subscribe() -> None:
    service = UnifiedProjectService()
    set_id = service.create_sd_set(_stack_ref("set"))
    service.upsert_event(set_id, EventMeta(event_id="event_0001", label="E", start_idx=0, end_idx=3, flags={}))
    updates: list[tuple[str, dict]] = []
    service.subscribe(lambda event, payload: updates.append((event, payload)))

    service.update_event_analysis(
        set_id,
        "event_0001",
        {
            "prompts": {"points": []},
            "masks_committed": np.zeros((4, 32, 32), dtype=np.uint8),
            "propagation_completed": True,
        },
    )
    analysis = service.get_event_analysis(set_id, "event_0001")
    assert analysis is not None
    assert analysis.prompts == {"points": []}
    assert analysis.masks_committed is not None
    assert analysis.masks_committed.shape == (4, 32, 32)
    assert any(name == "event_analysis_updated" for name, _ in updates)
