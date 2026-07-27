from __future__ import annotations

from swell.shared.persistence.embedded_images import reserve_embedded_image_arcname
from swell.shared.persistence.event_path import (
    allocate_event_path_segment,
    sanitize_event_path_segment,
)


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


def test_allocate_event_path_segment_avoids_casefold_and_unicode_collisions() -> None:
    used: set[str] = set()
    values = [
        allocate_event_path_segment("Event", used),
        allocate_event_path_segment("event", used),
        allocate_event_path_segment("café", used),
        allocate_event_path_segment("cafe\u0301", used),
    ]

    assert len({value.casefold() for value in values}) == len(values)


def test_event_segments_are_length_bounded() -> None:
    segment = sanitize_event_path_segment("x" * 300)
    assert len(segment) <= 120


def test_embedded_image_names_are_windows_safe_and_casefold_unique() -> None:
    used: set[str] = set()
    first = reserve_embedded_image_arcname("Frame.png", used)
    second = reserve_embedded_image_arcname("frame.png", used)
    reserved = reserve_embedded_image_arcname("CON.png", used)
    reserved_with_extra_suffix = reserve_embedded_image_arcname("AUX.raw.tif", used)

    assert first.casefold() != second.casefold()
    assert reserved.endswith("/_CON.png")
    assert reserved_with_extra_suffix.endswith("/_AUX.raw.tif")
