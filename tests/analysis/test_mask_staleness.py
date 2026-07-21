from __future__ import annotations

import numpy as np

from swell.analysis.core.seg_state import MASK_THRESHOLD_DEADBAND, SegmentationState


class TestMaskStaleness:
    def _state_with_mask(self, threshold=0.3):
        state = SegmentationState()
        state.set_mask(0, np.ones((8, 8), dtype=bool), threshold=threshold)
        return state

    def test_unchanged_threshold_is_not_stale(self):
        state = self._state_with_mask(0.3)
        assert state.get_stale_mask_frames(0.3) == set()

    def test_change_within_deadband_is_not_stale(self):
        state = self._state_with_mask(0.3)
        assert state.get_stale_mask_frames(0.3 + MASK_THRESHOLD_DEADBAND / 2) == set()

    def test_change_beyond_deadband_is_stale(self):
        state = self._state_with_mask(0.3)
        assert state.get_stale_mask_frames(0.3 + MASK_THRESHOLD_DEADBAND * 2) == {0}

    def test_small_nudges_accumulate(self):
        """Drift must be measured against generation, not the last check."""
        state = self._state_with_mask(0.3)
        current = 0.3
        for _ in range(5):
            current += 0.1
            state.get_stale_mask_frames(current)
        assert state.get_stale_mask_frames(current) == {0}

    def test_staleness_is_reversible(self):
        state = self._state_with_mask(0.3)
        assert state.get_stale_mask_frames(1.0) == {0}
        assert state.get_stale_mask_frames(0.3) == set()

    def test_unknown_threshold_is_never_stale(self):
        """Masks restored from a project file carry no threshold."""
        state = SegmentationState()
        state.set_mask(0, np.ones((8, 8), dtype=bool))
        assert state.get_stale_mask_frames(3.0) == set()

    def test_ground_truth_frames_are_never_stale(self):
        state = self._state_with_mask(0.3)
        state.ground_truth_frames.add(0)
        assert state.get_stale_mask_frames(3.0) == set()

    def test_painted_frames_are_never_stale(self):
        """Paint bypasses thresholding, so no re-run could clear the mark."""
        state = self._state_with_mask(0.3)
        state.set_paint_layer(0, np.ones((8, 8), dtype=bool), np.zeros((8, 8), dtype=bool))
        assert state.get_stale_mask_frames(3.0) == set()

    def test_clearing_a_mask_drops_its_threshold(self):
        state = self._state_with_mask(0.3)
        state.clear_mask(0)
        assert state.get_mask_threshold(0) is None

    def test_overwriting_without_threshold_clears_stale_record(self):
        """A paint edit must not inherit the previous mask's threshold."""
        state = self._state_with_mask(0.3)
        state.set_mask(0, np.zeros((8, 8), dtype=bool))
        assert state.get_mask_threshold(0) is None
        assert state.get_stale_mask_frames(3.0) == set()
