from __future__ import annotations

import pytest

from sdapp.host.event_catalog_service import EventCatalogService


def test_event_catalog_crud_and_active_selection() -> None:
    svc = EventCatalogService()

    ev1 = svc.create_event(start_idx=10, end_idx=20, frame_count=100)
    ev2 = svc.create_event(start_idx=30, end_idx=40, frame_count=100)
    assert ev1.event_id == "event_0001"
    assert ev2.event_id == "event_0002"
    assert svc.get_active_event_id() == "event_0002"

    svc.set_active_event(ev1.event_id)
    assert svc.get_active_event_id() == "event_0001"

    updated = svc.update_event(ev1.event_id, start_idx=25, end_idx=15, label="A", frame_count=100)
    assert updated.start_idx == 15
    assert updated.end_idx == 25
    assert updated.label == "A"

    deleted = svc.delete_many([ev1.event_id, "missing"])
    assert deleted == 1
    assert svc.get_event(ev1.event_id) is None


def test_event_catalog_normalization_and_clamp() -> None:
    svc = EventCatalogService()
    start, end = svc.normalize_bounds(-5, 1000, 50)
    assert (start, end) == (0, 49)

    with pytest.raises(ValueError):
        svc.normalize_bounds(0, 1, 0)


def test_event_catalog_create_event_preserves_flags() -> None:
    svc = EventCatalogService()

    event = svc.create_event(
        start_idx=0,
        end_idx=4,
        frame_count=10,
        flags={"host_full_stack_event": True},
    )

    assert bool(event.flags.get("host_full_stack_event")) is True


def test_event_catalog_update_event_can_replace_flags() -> None:
    svc = EventCatalogService()
    created = svc.create_event(start_idx=1, end_idx=4, frame_count=10, flags={"old": True})

    updated = svc.update_event(
        created.event_id,
        start_idx=None,
        end_idx=None,
        label=None,
        frame_count=10,
        flags={"analysis_processing": {"smoothing": False}},
    )

    assert updated.flags == {"analysis_processing": {"smoothing": False}}
