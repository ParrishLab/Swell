import unittest

import numpy as np

from sdapp.analysis.app import SDSegmentationApp
from sdapp.analysis.core.overlay_renderer import recompute_slider_jump_markers


class PropagationOverlayStateTests(unittest.TestCase):
    class _Spinbox:
        def __init__(self, value="", state="normal"):
            self.value = str(value)
            self.state = state

        def get(self):
            return self.value

        def delete(self, _start, _end=None):
            self.value = ""

        def insert(self, _index, value):
            self.value = str(value)

        def cget(self, name):
            if name == "state":
                return self.state
            raise KeyError(name)

        def configure(self, **kwargs):
            if "state" in kwargs:
                self.state = str(kwargs["state"])

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
        app.log_debug = lambda *_args, **_kwargs: None
        app._programmatic_spinbox_update = False
        app._export_range_auto_follow = True
        app._analysis_range_auto_follow = True
        app.spin_prop_start = self._Spinbox("1")
        app.spin_prop_end = self._Spinbox(str(frame_count))
        app._set_spinbox_value = SDSegmentationApp._set_spinbox_value.__get__(app, SDSegmentationApp)
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

    def test_workspace_event_opened_reseeds_overlay_from_event_saved_masks(self):
        app = self._make_app()
        app._set_propagated_frames({2, 3, 4, 5})
        app._collect_nonempty_final_mask_frames = lambda: {20, 21}

        app._on_workspace_event_opened("event_0002")

        self.assertEqual(app._largest_propagated_span, (20, 21))
        self.assertEqual(app._propagated_history_indices, {20, 21})
        self.assertEqual(app.propagated_frame_indices, {20, 21})

    def test_marker_sync_uses_current_nonempty_mask_edges(self):
        app = self._make_app(frame_count=30)
        app._collect_user_defined_frames = lambda: {9}
        app._collect_nonempty_final_mask_frames = lambda: {4, 5, 6, 12}

        recompute_slider_jump_markers(app)

        self.assertEqual(app.slider_jump_markers[4], "start")
        self.assertEqual(app.slider_jump_markers[12], "end")
        self.assertEqual(app.slider_jump_markers[9], "user")
        self.assertEqual(app.spin_prop_start.get(), "5")
        self.assertEqual(app.spin_prop_end.get(), "13")

    def test_frame_helpers_fall_back_when_frame_source_metadata_is_invalid(self):
        app = self._make_app(frame_count=3)
        app.frames_raw = [np.zeros((7, 9), dtype=np.uint8) for _ in range(3)]
        app.frame_source = type("BrokenSource", (), {"frame_count": 0, "frame_shape": (0, 0)})()

        self.assertEqual(app._get_frame_count(), 3)
        self.assertEqual(app._get_frame_shape(), (7, 9))

    def test_frame_shape_prefers_loaded_frames_when_frame_source_shape_disagrees(self):
        app = self._make_app(frame_count=2)
        app.frames_raw = [np.zeros((11, 13), dtype=np.uint8) for _ in range(2)]
        app.frame_source = type("BadShapeSource", (), {"frame_count": 2, "frame_shape": (13, 3)})()

        self.assertEqual(app._get_frame_shape(), (11, 13))

    def test_set_spinbox_value_updates_disabled_spinbox(self):
        app = self._make_app(frame_count=2)
        spinbox = self._Spinbox("100", state="disabled")

        app._set_spinbox_value(spinbox, 101)

        self.assertEqual(spinbox.get(), "101")
        self.assertEqual(spinbox.state, "disabled")


if __name__ == "__main__":
    unittest.main()
