import unittest
from unittest.mock import patch

import numpy as np

import sdapp.analysis.core.seg_state as seg_state_module
from sdapp.analysis.core.seg_state import SegmentationState


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

    def test_ground_truth_frame_is_anchor_but_not_user_frame(self):
        state = SegmentationState()
        state.set_mask(3, np.array([[True]], dtype=bool))
        state.set_ground_truth(3, True)
        self.assertTrue(state.is_ground_truth_frame(3))
        self.assertIn(3, state.get_prompt_anchor_frames())
        self.assertNotIn(3, state.get_user_frames())
        state.set_ground_truth(3, False)
        self.assertFalse(state.is_ground_truth_frame(3))
        self.assertNotIn(3, state.get_prompt_anchor_frames())

    def test_set_ground_truth_marks_user_frames_dirty(self):
        state = SegmentationState()
        state.get_user_frames()  # settle dirty flag
        self.assertFalse(state.dirty_user_frames)
        state.set_ground_truth(2, True)
        self.assertTrue(state.dirty_user_frames)

    def test_set_ground_truth_noop_does_not_dirty(self):
        state = SegmentationState()
        state.set_ground_truth(2, False)
        state.get_user_frames()
        self.assertFalse(state.dirty_user_frames)

    def test_clear_mask_discards_ground_truth(self):
        state = SegmentationState()
        state.set_mask(1, np.array([[True]], dtype=bool))
        state.set_ground_truth(1, True)
        state.clear_mask(1)
        self.assertFalse(state.is_ground_truth_frame(1))

    def test_get_ground_truth_frames_bounded(self):
        state = SegmentationState()
        state.set_ground_truth(2, True)
        state.set_ground_truth(9, True)
        self.assertEqual(state.get_ground_truth_frames(frame_count=5), {2})

    def test_boxes_count_as_user_frames_and_clear(self):
        state = SegmentationState()
        state.set_box(1, [8, 7, 2, 3])
        self.assertEqual(state.boxes[1], [2.0, 3.0, 8.0, 7.0])
        self.assertEqual(state.get_valid_box_frames(), {1})
        self.assertEqual(state.get_user_frames(), {1})
        state.clear_box(1)
        self.assertEqual(state.get_valid_box_frames(), set())
        self.assertEqual(state.get_user_frames(), set())

    def test_tiny_boxes_are_ignored(self):
        state = SegmentationState()
        state.set_box(1, [1, 1, 2, 2])
        self.assertNotIn(1, state.boxes)

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

    def test_get_nonempty_final_mask_frames_accepts_singleton_channel_masks(self):
        state = SegmentationState()
        mask = np.zeros((3, 3, 1), dtype=bool)
        mask[0, 0, 0] = True
        state.set_mask(1, mask)
        frames = state.get_nonempty_final_mask_frames(4, (3, 3))
        self.assertEqual(frames, {1})
        final_mask = state.compose_final_mask(1, (3, 3))
        self.assertEqual(final_mask.shape, (3, 3))
        self.assertTrue(bool(final_mask[0, 0]))

    def test_get_nonempty_final_mask_frames_checks_only_candidate_frames(self):
        state = SegmentationState()
        mask = np.zeros((3, 3), dtype=bool)
        mask[0, 0] = True
        state.set_mask(50, mask)
        plus = np.zeros((3, 3), dtype=bool)
        minus = np.zeros((3, 3), dtype=bool)
        plus[1, 1] = True
        state.set_paint_layer(12, plus, minus)

        checked: list[int] = []
        original = state.has_nonempty_final_mask

        def _track(frame_idx, base_shape):
            checked.append(int(frame_idx))
            return original(frame_idx, base_shape)

        state.has_nonempty_final_mask = _track  # type: ignore[method-assign]
        frames = state.get_nonempty_final_mask_frames(1000, (3, 3))

        self.assertEqual(frames, {12, 50})
        self.assertEqual(set(checked), {12, 50})

    def test_include_and_exclude_persistent_regions_apply_after_paint(self):
        state = SegmentationState()
        plus = np.zeros((10, 10), dtype=bool)
        minus = np.zeros((10, 10), dtype=bool)
        plus[1, 1] = True
        state.set_paint_layer(0, plus, minus)
        state.add_persistent_region(
            {
                "id": "include_a",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[2, 2], [7, 2], [7, 7], [2, 7]],
            }
        )
        state.add_persistent_region(
            {
                "id": "exclude_a",
                "mode": "exclude",
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[4, 4], [8, 4], [8, 8], [4, 8]],
            }
        )

        final_mask = state.compose_final_mask(0, (10, 10))

        self.assertTrue(final_mask[3, 3])
        self.assertFalse(final_mask[5, 5])
        self.assertTrue(final_mask[1, 1])

    def test_persistent_region_visibility_does_not_affect_composition(self):
        state = SegmentationState()
        state.add_persistent_region(
            {
                "id": "hidden_include",
                "mode": "include",
                "visible": False,
                "frame_start": 1,
                "frame_end": 1,
                "polygon": [[1, 1], [5, 1], [5, 5], [1, 5]],
            }
        )

        self.assertTrue(state.compose_final_mask(1, (8, 8))[2, 2])
        self.assertFalse(np.any(state.compose_final_mask(0, (8, 8))))

    def test_disabled_persistent_region_noops_and_region_only_frames_are_candidates(self):
        state = SegmentationState()
        state.add_persistent_region(
            {
                "id": "disabled",
                "mode": "include",
                "enabled": False,
                "frame_start": 1,
                "frame_end": 1,
                "polygon": [[1, 1], [5, 1], [5, 5], [1, 5]],
            }
        )
        state.add_persistent_region(
            {
                "id": "enabled",
                "mode": "include",
                "frame_start": 2,
                "frame_end": 2,
                "polygon": [[1, 1], [5, 1], [5, 5], [1, 5]],
            }
        )

        self.assertFalse(np.any(state.compose_final_mask(1, (8, 8))))
        self.assertEqual(state.get_nonempty_final_mask_frames(4, (8, 8)), {2})

    def test_region_only_frames_do_not_count_as_mask_bounds_frames(self):
        state = SegmentationState()
        state.add_persistent_region(
            {
                "id": "enabled",
                "mode": "include",
                "frame_start": 1,
                "frame_end": 3,
                "polygon": [[1, 1], [5, 1], [5, 5], [1, 5]],
            }
        )
        base_mask = np.zeros((8, 8), dtype=bool)
        base_mask[0, 0] = True
        state.set_mask(5, base_mask)

        self.assertEqual(state.get_nonempty_final_mask_frames(8, (8, 8)), {1, 2, 3, 5})
        self.assertEqual(state.get_nonempty_mask_frames_without_regions(8, (8, 8)), {5})

    def test_named_frame_sets_separate_anchors_timeline_and_exportable_masks(self):
        state = SegmentationState()
        state.set_points(1, [{"x": 1, "y": 1, "label": 1}])
        state.set_box(2, [1, 1, 5, 5])
        plus = np.zeros((8, 8), dtype=bool)
        minus = np.zeros((8, 8), dtype=bool)
        plus[1, 1] = True
        state.set_paint_layer(3, plus, minus)
        base = np.zeros((8, 8), dtype=bool)
        base[0, 0] = True
        state.set_mask(5, base)
        state.add_persistent_region(
            {
                "id": "region_only",
                "mode": "include",
                "frame_start": 6,
                "frame_end": 7,
                "polygon": [[1, 1], [5, 1], [5, 5], [1, 5]],
            }
        )

        self.assertEqual(state.get_prompt_anchor_frames(10), {1, 2, 3})
        self.assertEqual(state.get_timeline_extent_frames(10, (8, 8)), {3, 5})
        self.assertEqual(state.get_exportable_mask_frames(10, (8, 8)), {3, 5, 6, 7})

    def test_persistent_region_raster_cache_reuses_until_region_changes(self):
        state = SegmentationState()
        region_id = state.add_persistent_region(
            {
                "id": "cached",
                "mode": "include",
                "frame_start": 0,
                "frame_end": 10,
                "polygon": [[1, 1], [8, 1], [8, 8], [1, 8]],
            }
        )
        original_fill_poly = seg_state_module.cv2.fillPoly

        with patch.object(
            seg_state_module.cv2,
            "fillPoly",
            side_effect=lambda *args, **kwargs: original_fill_poly(*args, **kwargs),
        ) as fill_poly:
            self.assertTrue(state.compose_final_mask(0, (12, 12))[2, 2])
            self.assertTrue(state.compose_final_mask(1, (12, 12))[2, 2])
            self.assertEqual(fill_poly.call_count, 1)

            state.update_persistent_region(region_id, {"polygon": [[2, 2], [8, 2], [8, 8], [2, 8]]})
            self.assertTrue(state.compose_final_mask(0, (12, 12))[3, 3])
            self.assertEqual(fill_poly.call_count, 2)

    def test_persistent_region_raster_cache_avoids_per_frame_stress_rasterization(self):
        state = SegmentationState()
        for idx in range(20):
            offset = idx % 4
            state.add_persistent_region(
                {
                    "id": f"region_{idx}",
                    "mode": "include",
                    "frame_start": 0,
                    "frame_end": 49,
                    "polygon": [[1 + offset, 1], [12, 1 + offset], [12, 12], [1, 12]],
                }
            )
        original_fill_poly = seg_state_module.cv2.fillPoly

        with patch.object(
            seg_state_module.cv2,
            "fillPoly",
            side_effect=lambda *args, **kwargs: original_fill_poly(*args, **kwargs),
        ) as fill_poly:
            self.assertEqual(state.get_exportable_mask_frames(50, (16, 16)), set(range(50)))
            self.assertEqual(state.get_exportable_mask_frames(50, (16, 16)), set(range(50)))
            self.assertEqual(fill_poly.call_count, 20)


if __name__ == "__main__":
    unittest.main()
