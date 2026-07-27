import cv2
import numpy as np

from swell.shared.image_overlay import apply_mask_overlay


def test_mask_overlay_matches_previous_opencv_blend_exactly() -> None:
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 256, (64, 96, 3), dtype=np.uint8)
    mask = rng.random((64, 96)) < 0.35
    overlay = frame.copy()
    overlay[mask] = (0, 255, 255)
    expected = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0.0)

    actual = apply_mask_overlay(frame, mask)

    assert np.array_equal(actual, expected)
    assert not np.shares_memory(actual, frame)


def test_stale_hatch_does_not_mutate_source_or_mask() -> None:
    frame = np.full((32, 48, 3), 80, dtype=np.uint8)
    mask = np.ones((32, 48), dtype=bool)
    source_before = frame.copy()
    mask_before = mask.copy()

    result = apply_mask_overlay(frame, mask, color=(245, 196, 81), hatch=True)

    assert np.array_equal(frame, source_before)
    assert np.array_equal(mask, mask_before)
    assert np.any(result != frame)
