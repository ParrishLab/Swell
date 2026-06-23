from __future__ import annotations

import numpy as np

from swell.host.analysis_payload_mapper import (
    apply_analysis_scope_flags,
    EventBounds,
    FRAME_ORIGIN_EVENT_LOCAL,
    FRAME_ORIGIN_GLOBAL,
    FRAME_ORIGIN_SCOPE_LOCAL,
    RemapContext,
    annotate_payload_origins,
    remap_analysis_payload_for_bounds_change,
)


def test_annotate_payload_origins_defaults_to_scope_local_for_scope_sized_masks() -> None:
    bounds = EventBounds(
        start_idx=2,
        end_idx=4,
        flags={
            "baseline_pre_frames": 1,
            "analysis_scope_start_idx": 1,
            "analysis_scope_end_idx": 4,
            "analysis_local_event_start_idx": 1,
            "analysis_local_event_end_idx": 3,
        },
    )
    payload = annotate_payload_origins(
        {
            "prompts": {"frames": {"1": {"points": [{"x": 2, "y": 3}]}}},
            "masks_committed": np.zeros((4, 8, 9), dtype=np.uint8),
        },
        bounds=bounds,
    )

    assert payload["prompts_frame_origin"] == FRAME_ORIGIN_SCOPE_LOCAL
    assert payload["masks_committed_frame_origin"] == FRAME_ORIGIN_SCOPE_LOCAL


def test_remap_payload_moves_event_local_masks_into_new_scope() -> None:
    payload = {
        "prompts": {"frames": {"0": {"points": [{"x": 2, "y": 3, "label": 1}]}}},
        "prompts_frame_origin": FRAME_ORIGIN_EVENT_LOCAL,
        "masks_committed": np.zeros((4, 8, 9), dtype=np.uint8),
        "masks_committed_frame_origin": FRAME_ORIGIN_EVENT_LOCAL,
    }
    payload["masks_committed"][0] = 1
    updated = remap_analysis_payload_for_bounds_change(
        payload,
        event_id="event_0001",
        context=RemapContext(
            old_bounds=EventBounds(
                start_idx=12,
                end_idx=15,
                flags={
                    "baseline_pre_frames": 2,
                    "analysis_scope_start_idx": 10,
                    "analysis_scope_end_idx": 15,
                    "analysis_local_event_start_idx": 2,
                    "analysis_local_event_end_idx": 5,
                },
            ),
            new_bounds=EventBounds(
                start_idx=13,
                end_idx=16,
                flags={
                    "baseline_pre_frames": 2,
                    "analysis_scope_start_idx": 11,
                    "analysis_scope_end_idx": 16,
                    "analysis_local_event_start_idx": 2,
                    "analysis_local_event_end_idx": 5,
                },
            ),
        ),
    )

    assert updated is not None
    masks = np.asarray(updated["masks_committed"])
    assert updated["prompts_frame_origin"] == FRAME_ORIGIN_SCOPE_LOCAL
    assert updated["masks_committed_frame_origin"] == FRAME_ORIGIN_SCOPE_LOCAL
    assert masks.shape == (6, 8, 9)
    assert bool(np.any(masks[1]))
    assert "1" in dict(updated["prompts"]["frames"])


def test_remap_payload_preserves_global_origin_noop_update() -> None:
    payload = {
        "masks_committed": np.zeros((8, 4, 5), dtype=np.uint8),
        "masks_committed_frame_origin": FRAME_ORIGIN_GLOBAL,
    }
    payload["masks_committed"][3] = 1
    bounds = EventBounds(
        start_idx=2,
        end_idx=4,
        flags={
            "baseline_pre_frames": 1,
            "analysis_scope_start_idx": 1,
            "analysis_scope_end_idx": 4,
            "analysis_local_event_start_idx": 1,
            "analysis_local_event_end_idx": 3,
        },
    )
    updated = remap_analysis_payload_for_bounds_change(
        payload,
        event_id="event_0001",
        context=RemapContext(old_bounds=bounds, new_bounds=bounds),
    )

    assert updated is not None
    masks = np.asarray(updated["masks_committed"])
    assert masks.shape == (4, 4, 5)
    assert bool(np.any(masks[2]))


def test_apply_analysis_scope_flags_sets_baseline_and_scope_fields() -> None:
    flags = apply_analysis_scope_flags(
        {"keep": True},
        event_start=12,
        event_end=16,
        baseline_pre_frames=3,
    )

    assert flags["keep"] is True
    assert int(flags["baseline_pre_frames"]) == 3
    assert int(flags["analysis_scope_start_idx"]) == 9
    assert int(flags["analysis_scope_end_idx"]) == 16
    assert int(flags["analysis_local_event_start_idx"]) == 3
    assert int(flags["analysis_local_event_end_idx"]) == 7
