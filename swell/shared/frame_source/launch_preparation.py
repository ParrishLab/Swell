from __future__ import annotations


def build_launch_preparation_cache_key(
    *,
    event_id: str,
    scope_start: int,
    scope_end: int,
    local_event_start_idx: int | None = None,
    baseline_pre_frames: int,
    apply_horizontal_bar_denoise: bool,
    apply_smoothing: bool,
    apply_baseline_subtraction: bool,
    apply_global_normalization: bool,
    apply_stabilization: bool,
) -> tuple:
    return (
        str(event_id or ""),
        int(scope_start),
        int(scope_end),
        None if local_event_start_idx is None else int(local_event_start_idx),
        max(1, int(baseline_pre_frames)),
        bool(apply_horizontal_bar_denoise),
        bool(apply_smoothing),
        bool(apply_baseline_subtraction),
        bool(apply_global_normalization),
        bool(apply_stabilization),
    )
