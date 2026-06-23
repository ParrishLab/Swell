import unittest

from PIL import Image

from swell.analysis.ui.roi_dialog import (
    ROI_ICON_LABELS,
    _build_roi_result,
    _canvas_radius_to_image_radius,
    _clamp_roi_viewport,
    _compute_roi_transform,
    _dialog_transform_resample,
    _normalize_roi_polygons,
    _normalize_roi_context,
    _roi_save_actions,
)
from swell.analysis.core.viewport import ViewportState


class RoiDialogViewportTests(unittest.TestCase):
    def test_compute_roi_transform_uses_existing_viewport_state(self):
        state = {"viewport_state": ViewportState(center_x=50.0, center_y=25.0, zoom_factor=2.0)}
        transform = _compute_roi_transform(
            state,
            canvas_width=200,
            canvas_height=100,
            image_width=100,
            image_height=50,
        )
        center = transform.canvas_to_image(100.0, 50.0)
        self.assertAlmostEqual(center[0], 50.0)
        self.assertAlmostEqual(center[1], 25.0)

    def test_clamp_roi_viewport_limits_center_to_image_bounds(self):
        state = {"viewport_state": ViewportState(center_x=500.0, center_y=500.0, zoom_factor=3.0)}
        next_state = _clamp_roi_viewport(
            state,
            canvas_width=120,
            canvas_height=80,
            image_width=100,
            image_height=60,
        )
        self.assertLessEqual(next_state.center_x, 100.0)
        self.assertLessEqual(next_state.center_y, 60.0)

    def test_dialog_transform_resample_falls_back_from_lanczos(self):
        result = _dialog_transform_resample(Image.Resampling.LANCZOS)
        self.assertEqual(result, Image.Resampling.BICUBIC)

    def test_roi_icon_labels_match_expected_controls(self):
        self.assertEqual(
            ROI_ICON_LABELS,
            {"zoom_in": "Zoom In", "zoom_out": "Zoom Out", "fit": "Fit Image"},
        )

    def test_canvas_radius_converts_to_smaller_image_radius_when_zoomed_in(self):
        base = _canvas_radius_to_image_radius(1.0, 10.0)
        zoomed = _canvas_radius_to_image_radius(2.5, 10.0)
        self.assertAlmostEqual(base, 10.0)
        self.assertAlmostEqual(zoomed, 4.0)

    def test_roi_context_actions_are_context_specific(self):
        host = _normalize_roi_context("host", allow_reset_local=False)
        analysis = _normalize_roi_context("analysis", allow_reset_local=False)
        auto_detect = _normalize_roi_context("auto_detect", allow_reset_local=False)

        self.assertEqual(_roi_save_actions(host), [("global", "Save Global ROI", "primary")])
        self.assertIn(("local", "Save Local ROI", "primary"), _roi_save_actions(analysis))
        self.assertEqual(_roi_save_actions(auto_detect), [("auto_detect", "Save Auto-detect ROI", "primary")])

    def test_legacy_roi_points_initialize_as_single_polygon(self):
        polygons = _normalize_roi_polygons(
            initial_roi_points=[[1, 1], [4, 1], [4, 4]],
        )

        self.assertEqual(polygons, [[(1, 1), (4, 1), (4, 4)]])

    def test_build_roi_result_unions_multiple_closed_regions(self):
        regions = [
            [(1, 1), (3, 1), (3, 3), (1, 3)],
            [(6, 6), (8, 6), (8, 8), (6, 8)],
            [(0, 0), (1, 0)],
        ]

        result = _build_roi_result(regions, {0, 1}, image_shape=(10, 10), target_scope="local")

        self.assertEqual(result["target_scope"], "local")
        self.assertEqual(len(result["roi_polygons"]), 2)
        self.assertTrue(result["roi_mask"][2, 2])
        self.assertTrue(result["roi_mask"][7, 7])
        self.assertFalse(result["roi_mask"][0, 0])


if __name__ == "__main__":
    unittest.main()
