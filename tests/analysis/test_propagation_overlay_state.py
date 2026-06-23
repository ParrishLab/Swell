import unittest

import numpy as np
from types import SimpleNamespace

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core.overlay_renderer import (
    recompute_slider_jump_markers,
    redraw_slider_overlay,
    timeline_progress_geometry,
    update_slider_playhead,
    update_timeline_loading_progress,
    update_timeline_propagation_progress,
)
from swell.analysis.core.seg_state import SegmentationState


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

    class _Canvas:
        def __init__(self, width=100, height=18):
            self.width = int(width)
            self.height = int(height)
            self.items = []
            self.deleted_tags = []
            self.raised_tags = []
            self._next_id = 1

        def delete(self, *_args):
            self.deleted_tags.extend(str(arg) for arg in _args)
            if "all" in _args:
                self.items.clear()
                return
            tags = {str(arg) for arg in _args}
            self.items = [item for item in self.items if tags.isdisjoint(set(item["tags"]))]

        def winfo_width(self):
            return self.width

        def winfo_height(self):
            return self.height

        def create_rectangle(self, *args, **kwargs):
            item_id = self._next_id
            self._next_id += 1
            tags = kwargs.get("tags", ())
            if isinstance(tags, str):
                tags = (tags,)
            self.items.append({"id": item_id, "coords": tuple(args), "kwargs": dict(kwargs), "tags": tuple(tags)})
            return item_id

        def coords(self, item_id, *args):
            for item in self.items:
                if item["id"] == item_id:
                    if args:
                        item["coords"] = tuple(args)
                    return item["coords"]
            return ()

        def type(self, item_id):
            return "rectangle" if any(item["id"] == item_id for item in self.items) else ""

        def tag_raise(self, tag):
            self.raised_tags.append(str(tag))

    def _make_app(self, frame_count=50):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
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
        app._set_spinbox_value = SwellAnalysisApp._set_spinbox_value.__get__(app, SwellAnalysisApp)
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

    def test_workspace_event_opened_preserves_prompt_markers_when_no_saved_masks_exist(self):
        app = self._make_app(frame_count=30)
        app._recompute_slider_jump_markers = SwellAnalysisApp._recompute_slider_jump_markers.__get__(app, SwellAnalysisApp)
        app._collect_user_defined_frames = lambda: {9}
        app._collect_nonempty_final_mask_frames = lambda: set()

        app._on_workspace_event_opened("event_0003")

        self.assertEqual(app.slider_jump_markers[9], "user")
        self.assertIsNone(app._largest_propagated_span)
        self.assertEqual(app.propagated_frame_indices, set())

    def test_clear_current_frame_data_reseeds_overlay_from_remaining_saved_masks(self):
        app = self._make_app()
        app._set_propagated_frames({2, 3, 4, 5})
        app._collect_nonempty_final_mask_frames = lambda: {2, 4, 5}
        app.interaction_controller = SimpleNamespace(clear_current_frame_data=lambda: None)
        app._mark_project_dirty = lambda _reason="": None

        app.clear_current_frame_data()

        self.assertEqual(app._largest_propagated_span, (4, 5))
        self.assertEqual(app._propagated_history_indices, {2, 4, 5})
        self.assertEqual(app.propagated_frame_indices, {4, 5})

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

    def test_marker_sync_uses_lightweight_region_extent_without_composing_each_frame(self):
        app = self._make_app(frame_count=20)
        app.frames_raw = [np.zeros((8, 8), dtype=np.uint8) for _ in range(20)]
        app.seg_state = SegmentationState()
        app._collect_user_defined_frames = lambda: set()
        start_mask = np.zeros((8, 8), dtype=bool)
        end_mask = np.zeros((8, 8), dtype=bool)
        start_mask[1, 1] = True
        end_mask[2, 2] = True
        app.seg_state.set_mask(5, start_mask)
        app.seg_state.set_mask(10, end_mask)
        app.seg_state.add_persistent_region(
            {
                "id": "wide_include",
                "mode": "include",
                "frame_start": 1,
                "frame_end": 15,
                "polygon": [[1, 1], [5, 1], [5, 5], [1, 5]],
            }
        )
        calls = []
        original = app.seg_state.compose_final_mask

        def _track(frame_idx, base_shape, apply_persistent_regions=True):
            calls.append(int(frame_idx))
            return original(frame_idx, base_shape, apply_persistent_regions=apply_persistent_regions)

        app.seg_state.compose_final_mask = _track

        recompute_slider_jump_markers(app)

        self.assertEqual(app.slider_jump_markers[1], "start")
        self.assertEqual(app.slider_jump_markers[15], "end")
        self.assertEqual(app.spin_prop_start.get(), "2")
        self.assertEqual(app.spin_prop_end.get(), "16")
        self.assertEqual(set(calls), {5, 10})
        self.assertEqual(len(calls), 2)

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

    def test_timeline_progress_geometry_aggregate_stays_inside_selected_range(self):
        app = self._make_app(frame_count=10)
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        geometry = timeline_progress_geometry(
            app,
            width=100,
            total_frames=10,
            state={"active": True, "done": 2, "total": 4, "prop_start": 2, "prop_end": 6},
        )

        self.assertEqual(geometry["direction"], "aggregate")
        self.assertAlmostEqual(geometry["track_left"], 20.0)
        self.assertAlmostEqual(geometry["track_right"], 70.0)
        self.assertAlmostEqual(geometry["fill_left"], 20.0)
        self.assertAlmostEqual(geometry["fill_right"], 45.0)

    def test_timeline_progress_geometry_forward_fills_from_anchor(self):
        app = self._make_app(frame_count=10)
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        geometry = timeline_progress_geometry(
            app,
            width=100,
            total_frames=10,
            state={
                "active": True,
                "prop_start": 2,
                "prop_end": 8,
                "anchor": 4,
                "direction": "forward",
                "phase_done": 2,
                "phase_total": 4,
            },
        )

        self.assertEqual(geometry["direction"], "forward")
        self.assertAlmostEqual(geometry["fill_left"], 40.0)
        self.assertAlmostEqual(geometry["fill_right"], 65.0)

    def test_timeline_progress_geometry_backward_fills_toward_start(self):
        app = self._make_app(frame_count=10)
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        geometry = timeline_progress_geometry(
            app,
            width=100,
            total_frames=10,
            state={
                "active": True,
                "prop_start": 1,
                "prop_end": 7,
                "anchor": 5,
                "direction": "backward",
                "phase_done": 2,
                "phase_total": 4,
            },
        )

        self.assertEqual(geometry["direction"], "backward")
        self.assertAlmostEqual(geometry["fill_left"], 35.0)
        self.assertAlmostEqual(geometry["fill_right"], 60.0)

    def test_loading_progress_layers_under_markers_without_full_width_fill(self):
        app = self._make_app(frame_count=10)
        app.slider_overlay = self._Canvas(width=100, height=18)
        app.slider_jump_markers = {3: "user"}
        app.propagated_frame_indices = set()
        app._timeline_progress_state = {"active": True, "kind": "loading"}
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        redraw_slider_overlay(app)

        self.assertIn(3, app._slider_marker_bounds)
        self.assertFalse(
            any(item["coords"][0] == 0 and item["coords"][2] == 100 and item["kwargs"].get("fill") == "#1b75bc" for item in app.slider_overlay.items)
        )
        progress_track_idx = max(idx for idx, item in enumerate(app.slider_overlay.items) if item["kwargs"].get("fill") == "#1a2028")
        marker_idx = max(idx for idx, item in enumerate(app.slider_overlay.items) if item["kwargs"].get("fill") == "#b26bff")
        self.assertGreater(marker_idx, progress_track_idx)
        self.assertIn("timeline_marker", app.slider_overlay.raised_tags)

    def test_playhead_tracks_current_frame_full_height(self):
        app = self._make_app(frame_count=10)
        app.slider_overlay = self._Canvas(width=100, height=18)
        app.current_frame_idx = 4
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        update_slider_playhead(app)

        playheads = [it for it in app.slider_overlay.items if "timeline_playhead" in it["tags"]]
        self.assertEqual(len(playheads), 1)
        coords = playheads[0]["coords"]
        self.assertAlmostEqual(coords[0], 44.0)
        self.assertAlmostEqual(coords[2], 46.0)
        self.assertEqual(coords[1], 0)  # spans full height
        self.assertEqual(coords[3], 18)
        self.assertEqual(playheads[0]["kwargs"].get("fill"), "#ffffff")

    def test_playhead_moves_without_duplicating(self):
        app = self._make_app(frame_count=10)
        app.slider_overlay = self._Canvas(width=100, height=18)
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        app.current_frame_idx = 2
        update_slider_playhead(app)
        app.current_frame_idx = 7
        update_slider_playhead(app)

        playheads = [it for it in app.slider_overlay.items if "timeline_playhead" in it["tags"]]
        self.assertEqual(len(playheads), 1)
        self.assertAlmostEqual(playheads[0]["coords"][0], 74.0)

    def test_redraw_draws_playhead_on_top(self):
        app = self._make_app(frame_count=10)
        app.slider_overlay = self._Canvas(width=100, height=18)
        app.current_frame_idx = 5
        app.slider_jump_markers = {3: "user"}
        app.propagated_frame_indices = set()
        app._timeline_progress_state = {"active": False, "kind": None}
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        redraw_slider_overlay(app)

        playhead_idxs = [i for i, it in enumerate(app.slider_overlay.items) if "timeline_playhead" in it["tags"]]
        self.assertEqual(len(playhead_idxs), 1)
        # Playhead is created last so it stays above the marker bands.
        self.assertEqual(playhead_idxs[0], len(app.slider_overlay.items) - 1)

    def test_loading_progress_tick_updates_existing_items_without_full_redraw(self):
        app = self._make_app(frame_count=10)
        app.slider_overlay = self._Canvas(width=100, height=18)
        app.slider_jump_markers = {3: "user"}
        app.propagated_frame_indices = set()
        app._timeline_progress_state = {"active": True, "kind": "loading"}
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        redraw_slider_overlay(app)
        progress_ids = dict(app._timeline_progress_item_ids)
        delete_count = len(app.slider_overlay.deleted_tags)
        item_count = len(app.slider_overlay.items)

        update_timeline_loading_progress(app)

        self.assertEqual(progress_ids, app._timeline_progress_item_ids)
        self.assertEqual(delete_count, len(app.slider_overlay.deleted_tags))
        self.assertEqual(item_count, len(app.slider_overlay.items))
        self.assertIn("timeline_marker", app.slider_overlay.raised_tags)

    def test_propagation_progress_update_reuses_items_and_stays_in_range(self):
        app = self._make_app(frame_count=10)
        app.slider_overlay = self._Canvas(width=100, height=18)
        app.slider_jump_markers = {2: "start", 7: "end"}
        app.propagated_frame_indices = set()
        app._timeline_progress_state = {
            "active": True,
            "kind": "propagation",
            "done": 2,
            "total": 4,
            "prop_start": 2,
            "prop_end": 7,
        }
        app._frame_to_overlay_x = lambda frame_idx, width=100, total_frames=10: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        redraw_slider_overlay(app)
        progress_ids = dict(app._timeline_progress_item_ids)
        app._timeline_progress_state["done"] = 3
        update_timeline_propagation_progress(app)

        self.assertEqual(progress_ids, app._timeline_progress_item_ids)
        fill_item = next(item for item in app.slider_overlay.items if item["id"] == progress_ids["fill"])
        self.assertGreaterEqual(fill_item["coords"][0], 20.0)
        self.assertLessEqual(fill_item["coords"][2], 80.0)
        self.assertIn("timeline_marker", app.slider_overlay.raised_tags)

    def test_bidirectional_propagation_progress_keeps_completed_forward_segment_visible(self):
        app = self._make_app(frame_count=70)
        app.slider_overlay = self._Canvas(width=700, height=18)
        app.slider_jump_markers = {37: "start", 49: "user", 54: "end"}
        app.propagated_frame_indices = set()
        app._timeline_progress_state = {
            "active": True,
            "kind": "propagation",
            "done": 7,
            "total": 8,
            "prop_start": 37,
            "prop_end": 54,
            "anchor": 49,
            "direction": "backward",
            "phase_done": 1,
            "phase_total": 2,
            "forward_done": 6,
            "forward_total": 6,
            "backward_done": 1,
            "backward_total": 2,
        }
        app._frame_to_overlay_x = lambda frame_idx, width=700, total_frames=70: (float(frame_idx) + 0.5) * float(width) / float(total_frames)

        redraw_slider_overlay(app)
        progress_ids = app._timeline_progress_item_ids
        forward_item = next(item for item in app.slider_overlay.items if item["id"] == progress_ids["fill"])
        backward_item = next(item for item in app.slider_overlay.items if item["id"] == progress_ids["fill_wrap"])

        self.assertGreater(forward_item["coords"][2] - forward_item["coords"][0], 1.0)
        self.assertGreater(backward_item["coords"][2] - backward_item["coords"][0], 1.0)
        self.assertAlmostEqual(forward_item["coords"][0], 490.0)
        self.assertAlmostEqual(forward_item["coords"][2], 550.0)
        self.assertGreaterEqual(backward_item["coords"][0], 370.0)
        self.assertLessEqual(backward_item["coords"][2], 500.0)


if __name__ == "__main__":
    unittest.main()
