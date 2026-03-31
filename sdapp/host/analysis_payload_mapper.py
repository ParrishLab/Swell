from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any

import numpy as np


FRAME_ORIGIN_SCOPE_LOCAL = "analysis_scope_local"
FRAME_ORIGIN_EVENT_LOCAL = "event_local"
FRAME_ORIGIN_GLOBAL = "global"


@dataclass(frozen=True)
class EventBounds:
    start_idx: int
    end_idx: int
    flags: dict[str, Any]


@dataclass(frozen=True)
class AnalysisScope:
    scope_start: int
    scope_end: int
    local_event_start: int
    local_event_end: int


@dataclass(frozen=True)
class RemapContext:
    old_bounds: EventBounds
    new_bounds: EventBounds


def scope_metadata(bounds: EventBounds) -> AnalysisScope:
    event_start = int(bounds.start_idx)
    event_end = int(bounds.end_idx)
    flags = dict(bounds.flags or {})
    scope_start = int(flags.get("analysis_scope_start_idx", event_start))
    scope_end = int(flags.get("analysis_scope_end_idx", event_end))
    scope_start = min(scope_start, event_start)
    scope_end = max(scope_end, event_end)
    local_start = int(flags.get("analysis_local_event_start_idx", event_start - scope_start))
    local_end = int(flags.get("analysis_local_event_end_idx", event_end - scope_start))
    return AnalysisScope(
        scope_start=scope_start,
        scope_end=scope_end,
        local_event_start=local_start,
        local_event_end=local_end,
    )


def recompute_scope_flags(
    flags: dict[str, Any] | None,
    *,
    old_bounds: EventBounds,
    new_start: int,
    new_end: int,
) -> dict[str, Any]:
    updated = dict(flags or {})
    old_scope = scope_metadata(old_bounds)
    baseline_pre = int(updated.get("baseline_pre_frames", max(0, int(old_bounds.start_idx) - old_scope.scope_start)))
    baseline_pre = max(0, baseline_pre)
    scope_start_idx = max(0, int(new_start) - baseline_pre)
    scope_end_idx = max(scope_start_idx, int(new_end))
    updated["baseline_pre_frames"] = baseline_pre
    updated["analysis_scope_start_idx"] = scope_start_idx
    updated["analysis_scope_end_idx"] = scope_end_idx
    updated["analysis_local_event_start_idx"] = int(new_start) - scope_start_idx
    updated["analysis_local_event_end_idx"] = int(new_end) - scope_start_idx
    return updated


def normalize_frame_origin(origin: object) -> str | None:
    normalized = str(origin or "").strip().lower()
    if normalized in {
        FRAME_ORIGIN_SCOPE_LOCAL,
        FRAME_ORIGIN_EVENT_LOCAL,
        FRAME_ORIGIN_GLOBAL,
    }:
        return normalized
    return None


def infer_local_index_origin(
    indices: list[int],
    *,
    scope_len: int,
    event_len: int,
    local_event_start: int,
) -> str:
    if not indices:
        return FRAME_ORIGIN_SCOPE_LOCAL
    if local_event_start > 0 and all(0 <= idx < event_len for idx in indices) and min(indices) < local_event_start:
        return FRAME_ORIGIN_EVENT_LOCAL
    if all(0 <= idx < scope_len for idx in indices):
        return FRAME_ORIGIN_SCOPE_LOCAL
    if all(0 <= idx < event_len for idx in indices):
        return FRAME_ORIGIN_EVENT_LOCAL
    return FRAME_ORIGIN_GLOBAL


def normalize_sidecar_index(
    idx: object,
    *,
    scope: AnalysisScope,
    event_start: int,
    event_end: int,
    origin_hint: object = None,
) -> int | None:
    try:
        raw = int(idx)
    except (TypeError, ValueError):
        return None
    scope_len = max(0, int(scope.scope_end) - int(scope.scope_start) + 1)
    event_len = max(0, int(event_end) - int(event_start) + 1)
    normalized_hint = normalize_frame_origin(origin_hint)
    if normalized_hint == FRAME_ORIGIN_GLOBAL:
        return raw
    if normalized_hint == FRAME_ORIGIN_SCOPE_LOCAL:
        if 0 <= raw < scope_len:
            return int(scope.scope_start) + raw
        if int(scope.scope_start) <= raw <= int(scope.scope_end):
            return raw
        return None
    if normalized_hint == FRAME_ORIGIN_EVENT_LOCAL:
        if 0 <= raw < event_len:
            return int(event_start) + raw
        if int(event_start) <= raw <= int(event_end):
            return raw
        return None
    if 0 <= raw < scope_len:
        inferred = infer_local_index_origin(
            [raw],
            scope_len=scope_len,
            event_len=event_len,
            local_event_start=int(scope.local_event_start),
        )
        if inferred == FRAME_ORIGIN_EVENT_LOCAL:
            return int(event_start) + raw
        return int(scope.scope_start) + raw
    if 0 <= raw < event_len:
        return int(event_start) + raw
    if int(scope.scope_start) <= raw <= int(scope.scope_end):
        return raw
    return None


def infer_payload_origin(
    payload: Any,
    *,
    scope: AnalysisScope,
    event_start: int,
    event_end: int,
) -> str | None:
    if payload is None:
        return None
    scope_len = max(0, int(scope.scope_end) - int(scope.scope_start) + 1)
    event_len = max(0, int(event_end) - int(event_start) + 1)
    if isinstance(payload, dict):
        raw_indices: list[int] = []
        for key in payload.keys():
            try:
                raw_indices.append(int(key))
            except (TypeError, ValueError):
                continue
        if not raw_indices:
            return FRAME_ORIGIN_SCOPE_LOCAL
        return infer_local_index_origin(
            raw_indices,
            scope_len=scope_len,
            event_len=event_len,
            local_event_start=int(scope.local_event_start),
        )
    arr = np.asarray(payload)
    if arr.ndim == 4 and arr.shape[-1] == 1:
        arr = np.squeeze(arr, axis=-1)
    elif arr.ndim == 4 and arr.shape[1] == 1:
        arr = np.squeeze(arr, axis=1)
    if arr.ndim != 3:
        return None
    frame_count = int(arr.shape[0])
    if scope_len > 0 and frame_count == scope_len:
        return FRAME_ORIGIN_SCOPE_LOCAL
    if event_len > 0 and frame_count == event_len:
        return FRAME_ORIGIN_EVENT_LOCAL
    if frame_count > int(scope.scope_end):
        return FRAME_ORIGIN_GLOBAL
    return FRAME_ORIGIN_EVENT_LOCAL


def annotate_payload_origins(payload: dict[str, Any], *, bounds: EventBounds) -> dict[str, Any]:
    annotated = dict(payload or {})
    scope = scope_metadata(bounds)
    prompts = annotated.get("prompts")
    if isinstance(prompts, dict) and "prompts_frame_origin" not in annotated:
        annotated["prompts_frame_origin"] = infer_payload_origin(
            dict(prompts.get("frames", {})) if isinstance(prompts.get("frames"), dict) else {},
            scope=scope,
            event_start=int(bounds.start_idx),
            event_end=int(bounds.end_idx),
        ) or FRAME_ORIGIN_SCOPE_LOCAL
    for field_name in ("masks_committed", "masks_draft"):
        origin_key = f"{field_name}_frame_origin"
        if annotated.get(field_name) is None or origin_key in annotated:
            continue
        inferred = infer_payload_origin(
            annotated.get(field_name),
            scope=scope,
            event_start=int(bounds.start_idx),
            event_end=int(bounds.end_idx),
        )
        if inferred is not None:
            annotated[origin_key] = inferred
    return annotated


def _remap_mask_payload(
    payload: Any,
    *,
    old_scope: AnalysisScope,
    new_scope: AnalysisScope,
    old_event_start: int,
    old_event_end: int,
    origin_hint: object = None,
):
    if payload is None:
        return None
    new_scope_len = max(0, int(new_scope.scope_end) - int(new_scope.scope_start) + 1)
    if new_scope_len <= 0:
        return None
    if isinstance(payload, dict):
        remapped: dict[str, np.ndarray] = {}
        for frame_idx, mask in payload.items():
            global_idx = normalize_sidecar_index(
                frame_idx,
                scope=old_scope,
                event_start=old_event_start,
                event_end=old_event_end,
                origin_hint=origin_hint,
            )
            if global_idx is None:
                continue
            new_local = int(global_idx) - int(new_scope.scope_start)
            if not (0 <= new_local < new_scope_len):
                continue
            remapped[str(new_local)] = np.asarray(mask).copy()
        return remapped
    arr = np.asarray(payload)
    if arr.ndim == 4 and arr.shape[-1] == 1:
        arr = np.squeeze(arr, axis=-1)
    elif arr.ndim == 4 and arr.shape[1] == 1:
        arr = np.squeeze(arr, axis=1)
    if arr.ndim != 3:
        return payload
    remapped = np.zeros((new_scope_len, *arr.shape[1:]), dtype=arr.dtype)
    old_scope_len = max(0, int(old_scope.scope_end) - int(old_scope.scope_start) + 1)
    old_event_len = max(0, int(old_event_end) - int(old_event_start) + 1)
    normalized_origin = normalize_frame_origin(origin_hint)
    if normalized_origin == FRAME_ORIGIN_SCOPE_LOCAL:
        limit = min(int(arr.shape[0]), old_scope_len)
        global_index_for_local = lambda local_idx: int(old_scope.scope_start) + int(local_idx)
    elif normalized_origin == FRAME_ORIGIN_EVENT_LOCAL:
        limit = min(int(arr.shape[0]), old_event_len)
        global_index_for_local = lambda local_idx: int(old_event_start) + int(local_idx)
    elif normalized_origin == FRAME_ORIGIN_GLOBAL:
        limit = min(int(arr.shape[0]), max(0, int(old_scope.scope_end) + 1))
        global_index_for_local = lambda local_idx: int(local_idx)
    elif old_scope_len > 0 and int(arr.shape[0]) == old_scope_len:
        limit = min(int(arr.shape[0]), old_scope_len)
        global_index_for_local = lambda local_idx: int(old_scope.scope_start) + int(local_idx)
    elif old_event_len > 0 and int(arr.shape[0]) == old_event_len:
        limit = min(int(arr.shape[0]), old_event_len)
        global_index_for_local = lambda local_idx: int(old_event_start) + int(local_idx)
    elif int(arr.shape[0]) > int(old_scope.scope_end):
        limit = min(int(arr.shape[0]), max(0, int(old_scope.scope_end) + 1))
        global_index_for_local = lambda local_idx: int(local_idx)
    else:
        limit = min(int(arr.shape[0]), old_event_len)
        global_index_for_local = lambda local_idx: int(old_event_start) + int(local_idx)
    for old_local in range(limit):
        global_idx = global_index_for_local(old_local)
        new_local = int(global_idx) - int(new_scope.scope_start)
        if 0 <= new_local < new_scope_len:
            remapped[new_local] = arr[old_local]
    return remapped


def _remap_prompts_payload(
    prompts: dict[str, Any],
    *,
    event_id: str,
    old_scope: AnalysisScope,
    new_scope: AnalysisScope,
    old_event_start: int,
    old_event_end: int,
    origin_hint: object = None,
) -> dict[str, Any]:
    frames = dict(prompts.get("frames", {})) if isinstance(prompts.get("frames"), dict) else {}
    new_scope_len = max(0, int(new_scope.scope_end) - int(new_scope.scope_start) + 1)
    remapped_frames: dict[str, dict[str, Any]] = {}
    for frame_idx, frame_payload in frames.items():
        global_idx = normalize_sidecar_index(
            frame_idx,
            scope=old_scope,
            event_start=old_event_start,
            event_end=old_event_end,
            origin_hint=origin_hint,
        )
        if global_idx is None:
            continue
        new_local = int(global_idx) - int(new_scope.scope_start)
        if not (0 <= new_local < new_scope_len):
            continue
        remapped_frames[str(new_local)] = copy.deepcopy(frame_payload)
    updated = dict(prompts)
    updated["event_id"] = str(event_id)
    updated["frames"] = remapped_frames
    return updated


def remap_analysis_payload_for_bounds_change(
    payload: dict[str, Any] | None,
    *,
    event_id: str,
    context: RemapContext,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload:
        return None
    old_scope = scope_metadata(context.old_bounds)
    new_scope = scope_metadata(context.new_bounds)
    updated = dict(payload)
    if isinstance(updated.get("prompts"), dict):
        updated["prompts"] = _remap_prompts_payload(
            dict(updated.get("prompts") or {}),
            event_id=event_id,
            old_scope=old_scope,
            new_scope=new_scope,
            old_event_start=int(context.old_bounds.start_idx),
            old_event_end=int(context.old_bounds.end_idx),
            origin_hint=updated.get("prompts_frame_origin"),
        )
        updated["prompts_frame_origin"] = FRAME_ORIGIN_SCOPE_LOCAL
    if "masks_committed" in updated:
        updated["masks_committed"] = _remap_mask_payload(
            updated.get("masks_committed"),
            old_scope=old_scope,
            new_scope=new_scope,
            old_event_start=int(context.old_bounds.start_idx),
            old_event_end=int(context.old_bounds.end_idx),
            origin_hint=updated.get("masks_committed_frame_origin"),
        )
        updated["masks_committed_frame_origin"] = FRAME_ORIGIN_SCOPE_LOCAL
    if "masks_draft" in updated:
        updated["masks_draft"] = _remap_mask_payload(
            updated.get("masks_draft"),
            old_scope=old_scope,
            new_scope=new_scope,
            old_event_start=int(context.old_bounds.start_idx),
            old_event_end=int(context.old_bounds.end_idx),
            origin_hint=updated.get("masks_draft_frame_origin"),
        )
        updated["masks_draft_frame_origin"] = FRAME_ORIGIN_SCOPE_LOCAL
    return updated
