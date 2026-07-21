from __future__ import annotations

import numpy as np

from swell.analysis.core.inference_manager import InferenceManager
from swell.analysis.core.seg_state import (
    MASK_THRESHOLD_DEADBAND,
    POINT_STRENGTH_JITTER_PX,
    POINT_STRENGTH_MAX,
    POINT_STRENGTH_MIN,
    SegmentationState,
    expand_point_prompts,
    point_hit_tolerance,
    point_marker_radius,
    point_weight,
)


def _point(x=10.0, y=20.0, label=1, weight=None):
    point = {"x": x, "y": y, "label": label}
    if weight is not None:
        point["weight"] = weight
    return point


class TestPointWeight:
    def test_missing_weight_reads_as_one(self):
        assert point_weight(_point()) == 1

    def test_weight_is_clamped_to_range(self):
        assert point_weight(_point(weight=99)) == POINT_STRENGTH_MAX
        assert point_weight(_point(weight=0)) == POINT_STRENGTH_MIN
        assert point_weight(_point(weight=-5)) == POINT_STRENGTH_MIN

    def test_unusable_weight_falls_back_to_default(self):
        assert point_weight(_point(weight="strong")) == 1
        assert point_weight(_point(weight=None)) == 1
        assert point_weight("not a point") == 1


class TestExpandPointPrompts:
    def test_legacy_point_is_unchanged(self):
        """Projects predating strength must produce byte-identical prompts."""
        points, labels = expand_point_prompts([_point()])
        assert points.tolist() == [[10.0, 20.0]]
        assert labels.tolist() == [1]

    def test_weight_controls_token_count(self):
        for weight in range(POINT_STRENGTH_MIN, POINT_STRENGTH_MAX + 1):
            points, labels = expand_point_prompts([_point(weight=weight)])
            assert len(points) == weight
            assert len(labels) == weight

    def test_expansion_preserves_label(self):
        _points, labels = expand_point_prompts([_point(label=0, weight=4)])
        assert set(labels.tolist()) == {0}

    def test_original_click_is_always_the_first_token(self):
        points, _labels = expand_point_prompts([_point(x=7.0, y=8.0, weight=5)])
        assert points[0].tolist() == [7.0, 8.0]

    def test_copies_are_offset_not_coincident(self):
        """SAM2 never saw identical points in training."""
        points, _labels = expand_point_prompts([_point(x=0.0, y=0.0, weight=5)])
        for extra in points[1:]:
            assert not np.allclose(extra, points[0])
            assert np.isclose(float(np.hypot(extra[0], extra[1])), POINT_STRENGTH_JITTER_PX, atol=1e-4)

    def test_expansion_is_deterministic(self):
        """The logits cache assumes one prompt always yields one mask."""
        first, _ = expand_point_prompts([_point(weight=4)])
        second, _ = expand_point_prompts([_point(weight=4)])
        assert np.array_equal(first, second)

    def test_mixed_labels_and_weights(self):
        points, labels = expand_point_prompts([_point(label=1, weight=2), _point(label=0, weight=3)])
        assert len(points) == 5
        assert int((labels == 1).sum()) == 2
        assert int((labels == 0).sum()) == 3

    def test_user_click_is_never_clamped(self):
        """A wrong frame shape must not silently relocate a real prompt."""
        points, _labels = expand_point_prompts([_point(x=200.0, y=300.0)], frame_shape=(4, 4))
        assert points[0].tolist() == [200.0, 300.0]

    def test_generated_copies_are_clamped_into_frame(self):
        points, _labels = expand_point_prompts([_point(x=0.0, y=0.0, weight=5)], frame_shape=(64, 64))
        extras = points[1:]
        assert (extras >= 0).all()
        assert (extras[:, 0] <= 63).all() and (extras[:, 1] <= 63).all()

    def test_empty_and_malformed_input(self):
        assert expand_point_prompts([]) == (None, None)
        assert expand_point_prompts(None) == (None, None)
        assert expand_point_prompts([{"x": 1.0}]) == (None, None)

    def test_malformed_points_are_skipped_not_fatal(self):
        points, labels = expand_point_prompts([{"x": 1.0}, _point(x=5.0, y=6.0)])
        assert points.tolist() == [[5.0, 6.0]]
        assert labels.tolist() == [1]


class TestPromptSignature:
    """Strength must key the logits cache, or changing it serves a stale mask."""

    def _signature(self, points):
        state = SegmentationState()
        state.set_points(0, points)
        manager = InferenceManager.__new__(InferenceManager)
        manager.state = state
        return manager._prompt_signature(0)

    def test_differing_weights_do_not_share_a_cache_entry(self):
        assert self._signature([_point(weight=1)]) != self._signature([_point(weight=3)])

    def test_absent_weight_matches_explicit_default(self):
        """Existing cache entries stay valid for pre-strength projects."""
        assert self._signature([_point()]) == self._signature([_point(weight=1)])


class TestMarkerGeometry:
    def test_default_weight_keeps_original_radius(self):
        assert point_marker_radius(_point()) == 3.0

    def test_radius_grows_with_strength(self):
        radii = [point_marker_radius(_point(weight=w)) for w in range(1, POINT_STRENGTH_MAX + 1)]
        assert radii == sorted(radii)
        assert len(set(radii)) == len(radii)

    def test_hit_tolerance_never_smaller_than_marker(self):
        """A point drawn larger than its grab area feels broken."""
        for weight in range(POINT_STRENGTH_MIN, POINT_STRENGTH_MAX + 1):
            point = _point(weight=weight)
            assert point_hit_tolerance(point) >= point_marker_radius(point)

    def test_hit_tolerance_never_below_legacy_value(self):
        assert point_hit_tolerance(_point()) == 10.0


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
