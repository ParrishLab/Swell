from __future__ import annotations

import hashlib
import re

_INVALID_SEGMENT_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_RESERVED_WINDOWS_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def sanitize_event_path_segment(event_id: str) -> str:
    """Normalize an event id into a cross-platform-safe single path segment."""
    text = str(event_id or "").strip()
    text = _INVALID_SEGMENT_CHARS_RE.sub("_", text)
    text = text.rstrip(" .")
    if text in {"", ".", ".."}:
        text = "event"

    stem = text.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_BASENAMES:
        text = f"_{text}"
    return text


def allocate_event_path_segment(event_id: str, used_segments: set[str]) -> str:
    """Allocate a unique, deterministic path segment for an event id."""
    raw = str(event_id or "")
    base = sanitize_event_path_segment(raw)
    candidate = base
    if candidate not in used_segments:
        used_segments.add(candidate)
        return candidate

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}_{digest}"
    counter = 1
    while candidate in used_segments:
        candidate = f"{base}_{digest}_{counter}"
        counter += 1
    used_segments.add(candidate)
    return candidate
