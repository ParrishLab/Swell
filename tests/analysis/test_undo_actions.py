import unittest

import numpy as np

from sdapp.analysis.core.seg_state import SegmentationState
from sdapp.analysis.core.undo import UndoActions


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
        s.log_info = lambda ctx, msg: s.logged.append((ctx, msg))
        s.update_display = lambda *args, **kwargs: setattr(s, "updated", s.updated + 1)
        s._prune_empty_point_frames = lambda: setattr(s, "pruned", s.pruned + 1)
        s._recompute_slider_jump_markers = lambda: setattr(s, "recomputed", s.recomputed + 1)
        s._update_mask_prediction = lambda idx: setattr(s, "inferred", s.inferred + 1)
        return s

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

    def test_apply_paint_state(self):
        s = self._make_subject()
        plus = np.zeros((3, 3), dtype=bool)
        minus = np.zeros((3, 3), dtype=bool)
        plus[1, 1] = True
        s._apply_state(0, {"plus": plus, "minus": minus}, "paint")
        self.assertIn(0, s.seg_state.paint_layers)
        self.assertEqual(s.updated, 1)


if __name__ == "__main__":
    unittest.main()
