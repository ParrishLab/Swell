import math
import unittest

from sdapp.analysis.core.viewport import (
    ViewportState,
    clamp_viewport_center,
    compute_transform,
    fit_viewport,
    pan_viewport,
    zoom_viewport_at,
)


class ViewportTests(unittest.TestCase):
    def test_fit_viewport_centers_image_with_default_zoom(self):
        state = fit_viewport(320, 160)
        self.assertEqual(state.zoom_factor, 1.0)
        self.assertEqual(state.center_x, 160.0)
        self.assertEqual(state.center_y, 80.0)

    def test_zoom_at_anchor_keeps_image_point_stationary(self):
        state = fit_viewport(200, 100)
        next_state = zoom_viewport_at(
            state,
            image_width=200,
            image_height=100,
            canvas_width=100,
            canvas_height=50,
            anchor_canvas_x=25.0,
            anchor_canvas_y=10.0,
            new_zoom_factor=2.0,
            shared_canvas_sizes=[(100, 50)],
        )
        before = compute_transform(state, canvas_width=100, canvas_height=50, image_width=200, image_height=100)
        after = compute_transform(next_state, canvas_width=100, canvas_height=50, image_width=200, image_height=100)
        anchor_img = before.canvas_to_image(25.0, 10.0)
        anchor_img_after = after.canvas_to_image(25.0, 10.0)
        self.assertAlmostEqual(anchor_img[0], anchor_img_after[0], places=4)
        self.assertAlmostEqual(anchor_img[1], anchor_img_after[1], places=4)

    def test_pan_is_clamped_by_most_restrictive_canvas(self):
        state = ViewportState(center_x=100.0, center_y=50.0, zoom_factor=3.0)
        moved = pan_viewport(
            state,
            image_width=200,
            image_height=100,
            canvas_width=100,
            canvas_height=50,
            delta_canvas_x=-500.0,
            delta_canvas_y=-250.0,
            shared_canvas_sizes=[(100, 50), (160, 80)],
        )
        clamped = clamp_viewport_center(
            moved,
            image_width=200,
            image_height=100,
            canvas_sizes=[(100, 50), (160, 80)],
        )
        self.assertAlmostEqual(moved.center_x, clamped.center_x)
        self.assertAlmostEqual(moved.center_y, clamped.center_y)
        self.assertLessEqual(moved.center_x, 200.0)
        self.assertLessEqual(moved.center_y, 100.0)

    def test_transforms_share_center_across_different_canvas_sizes(self):
        state = ViewportState(center_x=60.0, center_y=45.0, zoom_factor=2.5)
        left = compute_transform(state, canvas_width=400, canvas_height=300, image_width=120, image_height=90)
        preview = compute_transform(state, canvas_width=150, canvas_height=150, image_width=120, image_height=90)
        left_center = left.canvas_to_image(left.canvas_width / 2.0, left.canvas_height / 2.0)
        preview_center = preview.canvas_to_image(preview.canvas_width / 2.0, preview.canvas_height / 2.0)
        self.assertTrue(math.isclose(left_center[0], 60.0, abs_tol=1e-6))
        self.assertTrue(math.isclose(left_center[1], 45.0, abs_tol=1e-6))
        self.assertEqual(left_center, preview_center)


if __name__ == "__main__":
    unittest.main()
