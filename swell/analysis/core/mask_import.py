from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


_INDEX_RE = re.compile(r"(\d+)(?!.*\d)")


def extract_frame_number(path: str | Path) -> Optional[int]:
    name = Path(path).stem
    match = _INDEX_RE.search(name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def guess_mask_mapping(
    mask_paths: Iterable[str | Path],
    frame_count: int,
    event_ranges: Dict[str, Tuple[int, int]],
) -> Dict[str, object]:
    paths = [str(Path(p)) for p in mask_paths]
    n_masks = len(paths)
    if frame_count <= 0 or n_masks <= 0:
        return {"strategy": "none", "offset": None, "event_id": None}

    if n_masks == int(frame_count):
        return {"strategy": "stack_exact", "offset": 0, "event_id": None}

    for event_id, bounds in event_ranges.items():
        start_idx, end_idx = int(bounds[0]), int(bounds[1])
        span_len = max(0, end_idx - start_idx + 1)
        if span_len == n_masks:
            return {"strategy": "event_span_exact", "offset": start_idx, "event_id": str(event_id)}

    indices = [extract_frame_number(p) for p in paths]
    if all(idx is not None for idx in indices):
        idxs = [int(v) for v in indices if v is not None]
        if not idxs:
            return {"strategy": "none", "offset": None, "event_id": None}
        first = idxs[0]
        if min(idxs) >= 1:
            one_based = first - 1
            if 0 <= one_based < frame_count:
                return {"strategy": "filename_index", "offset": one_based, "event_id": None}
        zero_based = first
        if 0 <= zero_based < frame_count:
            return {"strategy": "filename_index", "offset": zero_based, "event_id": None}

    return {"strategy": "manual_required", "offset": None, "event_id": None}
