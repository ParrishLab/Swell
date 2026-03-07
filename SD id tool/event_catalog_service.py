from __future__ import annotations

from dataclasses import replace

from host_models import EventMeta


class EventCatalogService:
    def __init__(self) -> None:
        self._events: dict[str, EventMeta] = {}
        self._active_event_id: str | None = None
        self._next_event_number = 1

    def reset(self, events: list[EventMeta] | None = None, active_event_id: str | None = None) -> None:
        self._events.clear()
        self._next_event_number = 1
        for event in list(events or []):
            self._events[str(event.event_id)] = replace(event)
            self._bump_next_number_from_event_id(event.event_id)
        self._active_event_id = None
        if active_event_id is not None and str(active_event_id) in self._events:
            self._active_event_id = str(active_event_id)

    def list_events(self) -> list[EventMeta]:
        return [replace(event) for event in self._events.values()]

    def get_event(self, event_id: str | None) -> EventMeta | None:
        if event_id is None:
            return None
        event = self._events.get(str(event_id))
        return replace(event) if event is not None else None

    def create_event(
        self,
        *,
        start_idx: int,
        end_idx: int,
        label: str | None = None,
        frame_count: int,
    ) -> EventMeta:
        start_idx, end_idx = self.normalize_bounds(start_idx, end_idx, frame_count)
        event_id = self._allocate_event_id()
        event = EventMeta(
            event_id=event_id,
            label=str(label if label is not None else event_id),
            start_idx=int(start_idx),
            end_idx=int(end_idx),
            flags={},
        )
        self._events[event_id] = event
        self._active_event_id = event_id
        return replace(event)

    def update_event(
        self,
        event_id: str,
        *,
        start_idx: int | None = None,
        end_idx: int | None = None,
        label: str | None = None,
        frame_count: int,
    ) -> EventMeta:
        key = str(event_id)
        event = self._events.get(key)
        if event is None:
            raise KeyError(f"Event not found: {event_id}")
        next_start = int(event.start_idx if start_idx is None else start_idx)
        next_end = int(event.end_idx if end_idx is None else end_idx)
        next_start, next_end = self.normalize_bounds(next_start, next_end, frame_count)
        next_label = str(event.label if label is None else label)
        updated = replace(event, start_idx=next_start, end_idx=next_end, label=next_label)
        self._events[key] = updated
        return replace(updated)

    def delete_event(self, event_id: str) -> None:
        key = str(event_id)
        self._events.pop(key, None)
        if self._active_event_id == key:
            self._active_event_id = None

    def delete_many(self, event_ids: list[str]) -> int:
        count = 0
        for event_id in list(event_ids):
            if str(event_id) in self._events:
                self.delete_event(str(event_id))
                count += 1
        return count

    def set_active_event(self, event_id: str | None) -> None:
        if event_id is None:
            self._active_event_id = None
            return
        key = str(event_id)
        self._active_event_id = key if key in self._events else None

    def get_active_event_id(self) -> str | None:
        return self._active_event_id

    @staticmethod
    def normalize_bounds(start_idx: int, end_idx: int, frame_count: int) -> tuple[int, int]:
        if int(frame_count) <= 0:
            raise ValueError("Empty stack.")
        max_idx = int(frame_count) - 1
        start = max(0, min(int(start_idx), max_idx))
        end = max(0, min(int(end_idx), max_idx))
        if end < start:
            start, end = end, start
        return start, end

    def _allocate_event_id(self) -> str:
        while True:
            event_id = f"event_{self._next_event_number:04d}"
            self._next_event_number += 1
            if event_id not in self._events:
                return event_id

    def _bump_next_number_from_event_id(self, event_id: str) -> None:
        parts = str(event_id).split("_")
        if len(parts) != 2 or not parts[1].isdigit():
            return
        next_num = int(parts[1]) + 1
        if next_num > self._next_event_number:
            self._next_event_number = next_num
