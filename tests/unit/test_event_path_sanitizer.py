from __future__ import annotations

from sdapp.shared.persistence.event_path import allocate_event_path_segment, sanitize_event_path_segment


def test_sanitize_event_path_segment_replaces_windows_invalid_characters() -> None:
    assert sanitize_event_path_segment('event:bad<name>|"x"?*') == "event_bad_name___x___"


def test_sanitize_event_path_segment_handles_reserved_names_and_trailing_dot_space() -> None:
    assert sanitize_event_path_segment("CON. ") == "_CON"
    assert sanitize_event_path_segment("LPT1") == "_LPT1"


def test_allocate_event_path_segment_avoids_collisions_deterministically() -> None:
    used: set[str] = set()
    first = allocate_event_path_segment("A:B", used)
    second = allocate_event_path_segment("A?B", used)
    assert first == "A_B"
    assert second.startswith("A_B_")
    assert second != first
