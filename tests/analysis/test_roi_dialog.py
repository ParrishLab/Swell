import unittest

from PIL import Image

from sdapp.analysis.ui.roi_dialog import (
    ROI_ICON_LABELS,
    _clamp_roi_viewport,
    _compute_roi_transform,
    _dialog_transform_resample,
)
from sdapp.analysis.core.viewport import ViewportState


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
        self.assertEqual(ROI_ICON_LABELS, {"zoom_in": "+", "zoom_out": "-", "fit": "□"})


if __name__ == "__main__":
    unittest.main()
