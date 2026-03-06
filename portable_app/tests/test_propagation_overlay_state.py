import unittest

from app.app import SDSegmentationApp


class PropagationOverlayStateTests(unittest.TestCase):
    def _make_app(self, frame_count=50):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.frames_raw = [None] * frame_count
        app._largest_propagated_span = None
        app._propagated_history_indices = set()
        app.propagated_frame_indices = set()
        app.propagated_frame_spans = []
        app.slider_jump_markers = {}
        app._slider_marker_bounds = {}
        app._recompute_slider_jump_markers = lambda: None
        app._redraw_slider_overlay = lambda: None
        return app

    def test_updates_on_first_nonempty_run(self):
        app = self._make_app()
        app._set_propagated_frames({10, 11, 12})
        self.assertEqual(app._largest_propagated_span, (10, 12))
        self.assertEqual(app.propagated_frame_indices, {10, 11, 12})

    def test_does_not_shrink_on_smaller_later_run(self):
        app = self._make_app()
        app._set_propagated_frames({5, 6, 7, 8, 9})
        app._set_propagated_frames({6, 7})
        self.assertEqual(app._largest_propagated_span, (5, 9))
        self.assertEqual(app.propagated_frame_indices, {5, 6, 7, 8, 9})

    def test_expands_on_strictly_larger_later_run(self):
        app = self._make_app()
        app._set_propagated_frames({20, 21, 22})
        app._set_propagated_frames({15, 16, 17, 18, 19, 20})
        self.assertEqual(app._largest_propagated_span, (15, 22))
        self.assertEqual(app.propagated_frame_indices, {15, 16, 17, 18, 19, 20, 21, 22})

    def test_expands_when_smaller_run_stitches_with_previous_range(self):
        app = self._make_app()
        app._set_propagated_frames({10, 11, 12, 13, 14})
        app._set_propagated_frames({15, 16})
        self.assertEqual(app._largest_propagated_span, (10, 16))
        self.assertEqual(app.propagated_frame_indices, {10, 11, 12, 13, 14, 15, 16})

    def test_ignores_empty_run_after_existing_span(self):
        app = self._make_app()
        app._set_propagated_frames({1, 2, 3, 4})
        app._set_propagated_frames(set())
        self.assertEqual(app._largest_propagated_span, (1, 4))
        self.assertEqual(app.propagated_frame_indices, {1, 2, 3, 4})

    def test_resets_largest_span_on_clear_state(self):
        app = self._make_app()
        app._set_propagated_frames({8, 9, 10})
        app._clear_propagation_overlay_state()
        self.assertIsNone(app._largest_propagated_span)
        self.assertEqual(app._propagated_history_indices, set())
        self.assertEqual(app.propagated_frame_indices, set())
        self.assertEqual(app.propagated_frame_spans, [])

    def test_tie_equal_length_keeps_existing_span(self):
        app = self._make_app()
        app._set_propagated_frames({2, 3, 4})
        app._set_propagated_frames({20, 21, 22})
        self.assertEqual(app._largest_propagated_span, (2, 4))
        self.assertEqual(app.propagated_frame_indices, {2, 3, 4})


if __name__ == "__main__":
    unittest.main()
