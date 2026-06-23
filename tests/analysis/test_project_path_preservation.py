import unittest

import numpy as np

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core.seg_state import SegmentationState


class ResetInteractionStateTests(unittest.TestCase):
    def test_reset_clears_boxes_along_with_other_prompts(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app.seg_state = SegmentationState()
        # Mirror the real app's aliases onto seg_state collections.
        app.points = app.seg_state.points
        app.boxes = app.seg_state.boxes
        app.paint_layers = app.seg_state.paint_layers
        app.masks_cache = app.seg_state.masks_cache

        app.seg_state.set_box(5, [10, 10, 40, 40])
        app.points[5] = [{"x": 1, "y": 2, "label": 1}]
        app.masks_cache[5] = np.ones((4, 4), dtype=bool)

        app._reset_interaction_state()

        # Stale box prompts must not survive into a freshly imported stack.
        self.assertEqual(app.boxes, {})
        self.assertEqual(app.seg_state.boxes, {})
        self.assertEqual(app.points, {})
        self.assertEqual(app.masks_cache, {})

    def test_reset_clears_seg_state_boxes_without_alias(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app.seg_state = SegmentationState()
        app.points = app.seg_state.points
        app.paint_layers = app.seg_state.paint_layers
        app.masks_cache = app.seg_state.masks_cache

        app.seg_state.set_box(5, [10, 10, 40, 40])

        app._reset_interaction_state()

        self.assertEqual(app.seg_state.boxes, {})
        self.assertIs(app.boxes, app.seg_state.boxes)


class ProjectPathPreservationTests(unittest.TestCase):
    def test_apply_loaded_stack_preserves_source_paths_after_reset(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app._current_image_source_paths = ["old"]
        app._reset_for_new_import = lambda: setattr(app, "_current_image_source_paths", [])
        app._finalize_load_ui = lambda: None
        app.start_model_initialization = lambda **_kwargs: None
        app._mark_project_dirty = lambda _reason: None

        app._apply_loaded_stack(
            frames_raw=[object()],
            frames_sub=[object()],
            frames_sub_viz=[object()],
            frame_names=["f1"],
            source_paths=["/tmp/a.tif", "/tmp/b.tif"],
        )

        self.assertEqual(app._current_image_source_paths, ["/tmp/a.tif", "/tmp/b.tif"])


if __name__ == "__main__":
    unittest.main()
