from __future__ import annotations

import numpy as np

from swell.analysis.model.cpu_fallback_predictor import (
    DeterministicCpuFallbackPredictor,
    FallbackInferenceState,
)


def _mask_from_logits(logits) -> np.ndarray:
    return np.asarray(logits[0].cpu().numpy()).squeeze() > 0.5


def test_init_and_reset_preserve_deterministic_seed_state() -> None:
    predictor = DeterministicCpuFallbackPredictor(frame_count=4, frame_shape=(20, 30))
    state = predictor.init_state("unused")
    seed = np.zeros((20, 30), dtype=bool)
    seed[4:8, 7:12] = True
    predictor.add_new_mask(inference_state=state, frame_idx=1, obj_id=9, mask=seed)

    predictor.reset_state(state)

    assert isinstance(state, FallbackInferenceState)
    assert state.frame_count == 4
    assert state.frame_shape == (20, 30)
    np.testing.assert_array_equal(state.seeded_masks[1], seed)


def test_add_mask_resizes_to_runtime_shape_with_binary_output() -> None:
    predictor = DeterministicCpuFallbackPredictor(frame_count=2, frame_shape=(8, 12))
    state = predictor.init_state()
    seed = np.zeros((4, 6), dtype=np.uint8)
    seed[1:3, 2:5] = 1

    frame_idx, object_ids, logits = predictor.add_new_mask(
        inference_state=state,
        frame_idx=0,
        obj_id=3,
        mask=seed,
    )

    assert frame_idx == 0
    assert object_ids == [3]
    assert _mask_from_logits(logits).shape == (8, 12)
    assert set(np.unique(_mask_from_logits(logits))) <= {False, True}


def test_points_and_box_apply_positive_and_negative_prompts() -> None:
    predictor = DeterministicCpuFallbackPredictor(frame_count=1, frame_shape=(100, 120))
    state = predictor.init_state()

    _, object_ids, logits = predictor.add_new_points_or_box(
        inference_state=state,
        frame_idx=0,
        obj_id=7,
        box=np.array([10, 10, 80, 70], dtype=np.float32),
        points=np.array([[20, 20], [50, 50]], dtype=np.float32),
        labels=np.array([1, 0], dtype=np.int32),
    )
    mask = _mask_from_logits(logits)

    assert object_ids == [7]
    assert mask[20, 20]
    assert not mask[50, 50]
    assert mask[30, 30]
    assert not mask[90, 100]


def test_propagation_uses_latest_seed_in_each_direction() -> None:
    predictor = DeterministicCpuFallbackPredictor(frame_count=6, frame_shape=(5, 7))
    state = predictor.init_state()
    first = np.zeros((5, 7), dtype=bool)
    second = np.zeros((5, 7), dtype=bool)
    first[1, 1] = True
    second[3, 5] = True
    predictor.add_new_mask(inference_state=state, frame_idx=1, obj_id=1, mask=first)
    predictor.add_new_mask(inference_state=state, frame_idx=4, obj_id=1, mask=second)

    forward = list(predictor.propagate_in_video(state, start_frame_idx=0, reverse=False))
    reverse = list(predictor.propagate_in_video(state, start_frame_idx=5, reverse=True))

    assert [item[0] for item in forward] == [1, 2, 3, 4, 5]
    np.testing.assert_array_equal(_mask_from_logits(forward[0][2]), first)
    np.testing.assert_array_equal(_mask_from_logits(forward[-1][2]), second)
    assert [item[0] for item in reverse] == [4, 3, 2, 1, 0]
    np.testing.assert_array_equal(_mask_from_logits(reverse[0][2]), second)
    np.testing.assert_array_equal(_mask_from_logits(reverse[-1][2]), first)


def test_propagation_without_a_seed_is_empty() -> None:
    predictor = DeterministicCpuFallbackPredictor(frame_count=3, frame_shape=(5, 7))

    assert list(predictor.propagate_in_video(predictor.init_state(), start_frame_idx=0, reverse=False)) == []

