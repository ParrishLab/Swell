from __future__ import annotations

import cv2
import numpy as np

from swell.analysis.core.frame_source import EagerFrameSource
from swell.shared.frame_source import PreparedFrameSource


def test_prepared_frame_source_prewarm_populates_cache_without_changing_values():
    frames = [np.full((8, 8), fill_value=i, dtype=np.uint8) for i in range(6)]
    source = EagerFrameSource(
        raw_frames=frames,
        subtracted_frames=frames,
        visual_frames=frames,
        frame_names=[f"f{i}.tif" for i in range(6)],
        source_paths=["/tmp/stack"] * 6,
    )
    prepared = PreparedFrameSource(source)

    expected = prepared.get_visual_frame(2).copy()
    prepared.prewarm([0, 2, 4], generation=7)

    assert {0, 2, 4}.issubset(set(prepared._frame_cache.keys()))
    np.testing.assert_array_equal(prepared.get_visual_frame(2), expected)


def test_prepared_frame_source_prewarm_stops_when_generation_is_stale():
    frames = [np.full((8, 8), fill_value=i, dtype=np.uint8) for i in range(6)]
    source = EagerFrameSource(
        raw_frames=frames,
        subtracted_frames=frames,
        visual_frames=frames,
        frame_names=[f"f{i}.tif" for i in range(6)],
        source_paths=["/tmp/stack"] * 6,
    )
    prepared = PreparedFrameSource(source)
    calls = {"count": 0}

    def should_continue() -> bool:
        calls["count"] += 1
        return calls["count"] <= 2

    prepared.prewarm([0, 1, 2, 3], generation=1, should_continue=should_continue)

    assert set(prepared._frame_cache.keys()) == {0}


def test_prepared_frame_source_stabilization_keeps_outputs_in_same_coordinate_space():
    base = np.zeros((24, 24), dtype=np.float32)
    base[8:13, 9:14] = 8.0
    matrix = np.array([[1.0, 0.0, 3.0], [0.0, 1.0, -2.0]], dtype=np.float32)
    shifted = cv2.warpAffine(base, matrix, (24, 24), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    source = EagerFrameSource(
        raw_frames=[base, shifted],
        subtracted_frames=[base, shifted],
        visual_frames=[np.asarray(base, dtype=np.uint8), np.asarray(shifted, dtype=np.uint8)],
        frame_names=["f0.tif", "f1.tif"],
        source_paths=["/tmp/stack", "/tmp/stack"],
    )
    prepared = PreparedFrameSource(
        source,
        baseline_frames=1,
        apply_smoothing=False,
        apply_baseline_subtraction=False,
        apply_global_normalization=False,
        apply_stabilization=True,
    )

    raw0 = prepared.get_raw_frame(0)
    raw1 = prepared.get_raw_frame(1)
    sub1 = prepared.get_subtracted_frame(1)
    viz1 = prepared.get_visual_frame(1)

    assert float(np.abs(raw1 - raw0).sum()) < float(np.abs(np.asarray(shifted, dtype=np.float32) - np.asarray(base, dtype=np.float32)).sum())
    np.testing.assert_allclose(sub1, raw1)
    assert viz1.shape == raw1.shape
    assert viz1.dtype == np.uint8
    np.testing.assert_array_equal(viz1 > 0, raw1 > 0)
