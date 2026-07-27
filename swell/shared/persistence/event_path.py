from __future__ import annotations

import hashlib
import re
import unicodedata

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
_MAX_EVENT_SEGMENT_LENGTH = 120


def portable_path_collision_key(value: str) -> str:
    """Return the comparison key used by case-insensitive normalized filesystems."""

    return unicodedata.normalize("NFC", str(value or "")).casefold().rstrip(" .")


def sanitize_filesystem_filename(
    filename: str,
    *,
    default: str = "file",
    max_length: int = 180,
) -> str:
    """Build one Windows/macOS-safe, length-bounded filename component."""

    raw = unicodedata.normalize("NFC", str(filename or "").strip())
    text = _INVALID_SEGMENT_CHARS_RE.sub("_", raw).rstrip(" .")
    if text in {"", ".", ".."}:
        text = str(default or "file")

    suffix = ""
    dot_index = text.rfind(".")
    if 0 < dot_index < len(text) - 1:
        suffix = text[dot_index:]
        stem = text[:dot_index]
    else:
        stem = text
    # Windows reserves device names even when additional suffixes follow
    # (for example ``CON.log.tif``).
    if stem.split(".", 1)[0].upper() in _RESERVED_WINDOWS_BASENAMES:
        stem = f"_{stem}"
    text = f"{stem}{suffix}"

    limit = max(24, int(max_length))
    if len(text) > limit:
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        suffix_budget = min(len(suffix), max(0, limit // 3))
        kept_suffix = suffix[-suffix_budget:] if suffix_budget else ""
        stem_budget = max(1, limit - len(kept_suffix) - len(digest) - 1)
        text = f"{stem[:stem_budget]}_{digest}{kept_suffix}".rstrip(" .")
    return text


def sanitize_event_path_segment(event_id: str) -> str:
    """Normalize an event id into a cross-platform-safe single path segment."""
    return sanitize_filesystem_filename(
        str(event_id or ""),
        default="event",
        max_length=_MAX_EVENT_SEGMENT_LENGTH,
    )


def _candidate_is_available(candidate: str, used_segments: set[str]) -> bool:
    key = portable_path_collision_key(candidate)
    return all(portable_path_collision_key(used) != key for used in used_segments)


def _append_bounded_suffix(base: str, suffix: str) -> str:
    budget = max(1, _MAX_EVENT_SEGMENT_LENGTH - len(suffix))
    return f"{base[:budget]}{suffix}".rstrip(" .")


def allocate_event_path_segment(event_id: str, used_segments: set[str]) -> str:
    """Allocate a unique, deterministic path segment for an event id."""
    raw = str(event_id or "")
    base = sanitize_event_path_segment(raw)
    candidate = base
    if _candidate_is_available(candidate, used_segments):
        used_segments.add(candidate)
        return candidate

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    candidate = _append_bounded_suffix(base, f"_{digest}")
    counter = 1
    while not _candidate_is_available(candidate, used_segments):
        candidate = _append_bounded_suffix(base, f"_{digest}_{counter}")
        counter += 1
    used_segments.add(candidate)
    return candidate
