import unittest

import numpy as np

from swell.analysis.core.seg_state import SegmentationState
from swell.analysis.core.undo import UndoActions


class _SliderStub:
    def __init__(self):
        self.values = []

    def set(self, value):
        self.values.append(value)


class UndoActionsTests(unittest.TestCase):
    def _make_subject(self):
        class Subject(UndoActions):
            pass

        s = Subject()
        s.undo_stack = []
        s.redo_stack = []
        s.seg_state = SegmentationState()
        s.model_ready = False
        s.current_frame_idx = 0
        s.slider = _SliderStub()
        s.logged = []
        s.updated = 0
        s.pruned = 0
        s.recomputed = 0
        s.inferred = 0
        s.leverage_recomputed = 0
        s.log_info = lambda ctx, msg: s.logged.append((ctx, msg))
        s.update_display = lambda *args, **kwargs: setattr(s, "updated", s.updated + 1)
        s._prune_empty_point_frames = lambda: setattr(s, "pruned", s.pruned + 1)
        s._recompute_slider_jump_markers = lambda: setattr(s, "recomputed", s.recomputed + 1)
        s._schedule_leverage_recompute = lambda *a, **k: setattr(
            s, "leverage_recomputed", s.leverage_recomputed + 1
        )
        s._update_mask_prediction = lambda idx: setattr(s, "inferred", s.inferred + 1)
        return s

    def test_undo_steps_back_region_draft_point_before_project_undo(self):
        s = self._make_subject()
        s.record_action("point", 0, None, None)

        class _DraftController:
            def __init__(self):
                self.calls = 0

            def undo_region_draft_point(self):
                self.calls += 1
                return True

        s.interaction_controller = _DraftController()

        self.assertEqual(s.on_undo(), "break")

        # The draft is transient and never reaches the stack, so undo must
        # consume the keystroke without popping the committed action.
        self.assertEqual(s.interaction_controller.calls, 1)
        self.assertEqual(len(s.undo_stack), 1)
        self.assertEqual(s.redo_stack, [])

    def test_undo_falls_through_to_project_undo_when_no_draft(self):
        s = self._make_subject()
        s.record_action("point", 0, None, None)

        class _DraftController:
            def undo_region_draft_point(self):
                return False

        s.interaction_controller = _DraftController()

        self.assertEqual(s.on_undo(), "break")

        self.assertEqual(s.undo_stack, [])
        self.assertEqual(len(s.redo_stack), 1)

    def test_record_action_caps_stack(self):
        s = self._make_subject()
        for i in range(60):
            s.record_action("point", i, None, None)
        self.assertEqual(len(s.undo_stack), 50)

    def test_undo_and_redo_point(self):
        s = self._make_subject()
        before = [{"x": 1, "y": 1, "label": 1}]
        after = [{"x": 2, "y": 2, "label": 1}]
        s.record_action("point", 3, before, after)
        s.on_undo()
        self.assertEqual(s.seg_state.points[3], before)
        s.on_redo()
        self.assertEqual(s.seg_state.points[3], after)

    def test_undo_and_redo_schedule_leverage_recompute(self):
        s = self._make_subject()
        s.record_action("point", 3, [{"x": 1, "y": 1, "label": 1}], None)
        s.on_undo()
        s.on_redo()
        # Both directions must refresh the leverage heatmap so it is not stale.
        self.assertEqual(s.leverage_recomputed, 2)

    def test_apply_paint_state(self):
        s = self._make_subject()
        plus = np.zeros((3, 3), dtype=bool)
        minus = np.zeros((3, 3), dtype=bool)
        plus[1, 1] = True
        s._apply_state(0, {"plus": plus, "minus": minus}, "paint")
        self.assertIn(0, s.seg_state.paint_layers)
        self.assertEqual(s.updated, 1)

    def test_cross_frame_apply_state_defers_display_until_slider_navigation(self):
        s = self._make_subject()
        plus = np.zeros((3, 3), dtype=bool)
        minus = np.zeros((3, 3), dtype=bool)
        plus[1, 1] = True

        s._apply_state(3, {"plus": plus, "minus": minus}, "paint")

        self.assertIn(3, s.seg_state.paint_layers)
        self.assertEqual(s.updated, 0)
        self.assertEqual(s.slider.values, [3])

    def test_same_frame_apply_state_still_updates_display_once(self):
        s = self._make_subject()
        plus = np.zeros((3, 3), dtype=bool)
        minus = np.zeros((3, 3), dtype=bool)

        s._apply_state(0, {"plus": plus, "minus": minus}, "paint")

        self.assertEqual(s.updated, 1)
        self.assertEqual(s.slider.values, [])

    def test_cross_frame_model_ready_point_undo_keeps_mask_prediction(self):
        s = self._make_subject()
        s.model_ready = True
        point = [{"x": 1, "y": 1, "label": 1}]

        s._apply_state(4, point, "point")

        self.assertEqual(s.inferred, 1)
        self.assertEqual(s.updated, 0)
        self.assertEqual(s.slider.values, [4])

    def test_undo_and_redo_box(self):
        s = self._make_subject()
        before = [1.0, 2.0, 8.0, 9.0]
        after = [2.0, 3.0, 10.0, 12.0]
        s.record_action("box", 3, before, after)
        s.on_undo()
        self.assertEqual(s.seg_state.boxes[3], before)
        s.on_redo()
        self.assertEqual(s.seg_state.boxes[3], after)

    def test_undo_and_redo_region_snapshot(self):
        s = self._make_subject()
        before = []
        after = [
            {
                "id": "region_a",
                "mode": "include",
                "enabled": True,
                "visible": True,
                "frame_start": 0,
                "frame_end": 2,
                "polygon": [[1, 1], [4, 1], [4, 4]],
            }
        ]
        s.seg_state.persistent_regions = [dict(after[0])]
        s.record_action("region", 0, before, after)

        s.on_undo()
        self.assertEqual(s.seg_state.persistent_regions, [])

        s.on_redo()
        self.assertEqual(s.seg_state.persistent_regions[0]["id"], "region_a")

    def test_double_undo_restores_propagated_mask_after_point_add_remove(self):
        s = self._make_subject()
        s.model_ready = True
        frame_idx = 2
        propagated_mask = np.zeros((4, 4), dtype=bool)
        propagated_mask[1:3, 1:3] = True
        point = [{"x": 1, "y": 1, "label": 1}]

        s.record_action("point", frame_idx, None, point, mask_before=propagated_mask.copy())
        s.record_action("point", frame_idx, point, None)

        s.seg_state.clear_points(frame_idx)
        s.seg_state.clear_mask(frame_idx)

        s.on_undo()
        self.assertEqual(s.seg_state.points[frame_idx], point)
        self.assertEqual(s.inferred, 1)

        s.on_undo()
        self.assertNotIn(frame_idx, s.seg_state.points)
        self.assertIn(frame_idx, s.seg_state.masks_cache)
        self.assertTrue(np.array_equal(s.seg_state.masks_cache[frame_idx], propagated_mask))
        self.assertEqual(s.inferred, 1)

    def test_undo_redo_clear_frame_roundtrip_restores_frame_payload(self):
        s = self._make_subject()
        frame_idx = 1
        points_before = [{"x": 3, "y": 2, "label": 1}]
        plus = np.zeros((5, 5), dtype=bool)
        minus = np.zeros((5, 5), dtype=bool)
        plus[2, 2] = True
        mask_before = np.zeros((5, 5), dtype=bool)
        mask_before[1:4, 1:4] = True
        clear_before = {
            "points": points_before,
            "box": [1.0, 1.0, 4.0, 4.0],
            "paint": {"plus": plus.copy(), "minus": minus.copy()},
            "mask": mask_before.copy(),
        }
        clear_after = {"points": None, "box": None, "paint": None, "mask": None}

        s.record_action("clear_frame", frame_idx, clear_before, clear_after)
        s.on_undo()
        self.assertEqual(s.seg_state.points[frame_idx], points_before)
        self.assertEqual(s.seg_state.boxes[frame_idx], [1.0, 1.0, 4.0, 4.0])
        self.assertTrue(np.any(s.seg_state.paint_layers[frame_idx]["plus"]))
        self.assertTrue(np.array_equal(s.seg_state.masks_cache[frame_idx], mask_before))

        s.on_redo()
        self.assertNotIn(frame_idx, s.seg_state.points)
        self.assertNotIn(frame_idx, s.seg_state.boxes)
        self.assertNotIn(frame_idx, s.seg_state.paint_layers)
        self.assertNotIn(frame_idx, s.seg_state.masks_cache)


if __name__ == "__main__":
    unittest.main()
