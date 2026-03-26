from __future__ import annotations

from pathlib import Path

import numpy as np

from sdapp.analysis.model.sam2_frame_cache import SAM2FrameCache, build_sam2_frame_cache_key
from sdapp.shared.frame_source.preprocessing import VisualizationStats


class _Source:
    frame_count = 3
    frame_shape = (4, 5)
    source_paths = ["/tmp/a.tif"]
    frame_names = ["a_000.tif", "a_001.tif", "a_002.tif"]


def test_frame_cache_key_changes_with_processing_flags():
    stats = VisualizationStats(
        frame_count=3,
        frame_shape=(4, 5),
        baseline_frames=2,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        baseline=np.zeros((4, 5), dtype=np.float32),
        p1=1.0,
        p99=9.0,
    )
    common = dict(
        frame_source=_Source(),
        frame_count=3,
        frame_shape=(4, 5),
        baseline_frames=2,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        stats=stats,
    )
    key_a = build_sam2_frame_cache_key(apply_smoothing=True, **common)
    key_b = build_sam2_frame_cache_key(apply_smoothing=False, **common)
    assert key_a != key_b


def test_frame_cache_reuses_complete_dir(tmp_path: Path):
    cache = SAM2FrameCache(cache_root=str(tmp_path / "cache"))
    frames = np.zeros((2, 4, 4), dtype=np.uint8)
    source = _Source()
    key = build_sam2_frame_cache_key(
        frame_source=source,
        frame_count=2,
        frame_shape=(4, 4),
        baseline_frames=2,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        stats=None,
    )
    logs: list[tuple[str, str]] = []
    first = cache.export_frames(
        frame_source=source,
        frames_viz=frames,
        cache_key=key,
        logger=lambda ctx, msg: logs.append((ctx, msg)),
    )
    second = cache.export_frames(
        frame_source=source,
        frames_viz=frames,
        cache_key=key,
        logger=lambda ctx, msg: logs.append((ctx, msg)),
    )
    assert first.exported_count == 2
    assert second.reused is True
    assert second.exported_count == 0
    assert (Path(second.cache_dir) / "00000.jpg").exists()
    assert any("cache hit" in msg for _ctx, msg in logs)


def test_frame_cache_completes_partial_dir(tmp_path: Path):
    cache = SAM2FrameCache(cache_root=str(tmp_path / "cache"))
    frames = np.zeros((3, 4, 4), dtype=np.uint8)
    source = _Source()
    key = build_sam2_frame_cache_key(
        frame_source=source,
        frame_count=3,
        frame_shape=(4, 4),
        baseline_frames=2,
        apply_smoothing=True,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        stats=None,
    )
    first = cache.export_frames(
        frame_source=source,
        frames_viz=frames,
        cache_key=key,
        logger=lambda *_args: None,
    )
    (Path(first.cache_dir) / "00001.jpg").unlink()
    second = cache.export_frames(
        frame_source=source,
        frames_viz=frames,
        cache_key=key,
        logger=lambda *_args: None,
    )
    assert second.exported_count == 1
    assert cache.is_complete(second.cache_dir, 3)
