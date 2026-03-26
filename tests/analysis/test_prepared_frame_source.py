from __future__ import annotations

import numpy as np

from sdapp.analysis.core.frame_source import EagerFrameSource
from sdapp.shared.frame_source import PreparedFrameSource


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
