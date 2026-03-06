import unittest

import numpy as np

from app.core.seg_state import SegmentationState


class SegmentationStateTests(unittest.TestCase):
    def test_valid_point_frames_filters_invalid_entries(self):
        state = SegmentationState()
        state.points[0] = [{"x": 1, "y": 2, "label": 1}]
        state.points[1] = [{"x": 1, "y": 2}]  # invalid
        self.assertEqual(state.get_valid_point_frames(), {0})

    def test_get_user_frames_includes_nonempty_paint(self):
        state = SegmentationState()
        plus = np.zeros((4, 4), dtype=bool)
        minus = np.zeros((4, 4), dtype=bool)
        plus[1, 1] = True
        state.set_paint_layer(2, plus, minus)
        self.assertEqual(state.get_user_frames(), {2})

    def test_compose_final_mask_applies_plus_and_minus(self):
        state = SegmentationState()
        base = np.zeros((5, 5), dtype=bool)
        base[1, 1] = True
        state.set_mask(0, base)
        plus = np.zeros((5, 5), dtype=bool)
        minus = np.zeros((5, 5), dtype=bool)
        plus[2, 2] = True
        minus[1, 1] = True
        state.set_paint_layer(0, plus, minus)
        final_mask = state.compose_final_mask(0, (5, 5))
        self.assertTrue(final_mask[2, 2])
        self.assertFalse(final_mask[1, 1])

    def test_get_nonempty_final_mask_frames(self):
        state = SegmentationState()
        mask = np.zeros((3, 3), dtype=bool)
        mask[0, 0] = True
        state.set_mask(1, mask)
        frames = state.get_nonempty_final_mask_frames(4, (3, 3))
        self.assertEqual(frames, {1})


if __name__ == "__main__":
    unittest.main()
