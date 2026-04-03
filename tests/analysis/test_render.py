import unittest

import numpy as np
from PIL import Image

from sdapp.analysis.core.render import RenderActions
from sdapp.analysis.core.viewport import ViewportState, compute_transform


class _CanvasStub:
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height


class _RenderHarness(RenderActions):
    pass


class _ViewportRenderHarness(RenderActions):
    def __init__(self):
        self.viewport_state = ViewportState(center_x=5.0, center_y=5.0, zoom_factor=2.0)

    def _get_canvas_viewport_transform(self, canvas, img_w, img_h):
        return compute_transform(
            self.viewport_state,
            canvas_width=canvas.winfo_width(),
            canvas_height=canvas.winfo_height(),
            image_width=img_w,
            image_height=img_h,
        )


class RenderActionsTests(unittest.TestCase):
    def test_display_transform_matches_non_upscaled_rendering(self):
        harness = _RenderHarness()
        canvas = _CanvasStub(width=400, height=300)

        ratio, offset_x, offset_y = harness._get_display_transform(canvas, img_w=100, img_h=50)

        self.assertEqual(ratio, 1.0)
        self.assertEqual(offset_x, 150)
        self.assertEqual(offset_y, 125)

    def test_rendered_center_pixel_stays_aligned_across_canvases(self):
        harness = _ViewportRenderHarness()
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        for y in range(10):
            for x in range(10):
                img[y, x] = [x * 10, y * 10, 0]

        left_img, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=100, height=80),
            img,
            resample=Image.Resampling.NEAREST,
            fill_value=(241, 241, 241),
        )
        preview_img, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=60, height=60),
            img,
            resample=Image.Resampling.NEAREST,
            fill_value=(241, 241, 241),
        )

        left_center = left_img.getpixel((50, 40))
        preview_center = preview_img.getpixel((30, 30))
        self.assertEqual(left_center[:2], preview_center[:2])

    def test_mask_preview_render_uses_nearest_neighbor_values(self):
        harness = _ViewportRenderHarness()
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[:, 5:] = 255
        preview_img, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=63, height=63),
            mask,
            resample=Image.Resampling.NEAREST,
            fill_value=0,
        )
        values = set(preview_img.getdata())
        self.assertEqual(values, {0, 255})

    def test_affine_transform_falls_back_from_lanczos_to_bicubic(self):
        harness = _ViewportRenderHarness()
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[:, :] = [10, 20, 30]
        rendered, _ = harness._render_array_to_canvas_image(
            _CanvasStub(width=40, height=40),
            img,
            resample=Image.Resampling.LANCZOS,
            fill_value=(241, 241, 241),
        )
        self.assertEqual(rendered.size, (40, 40))

    def test_slider_move_does_not_mark_dirty(self):
        harness = _RenderHarness()
        harness.current_frame_idx = 0
        harness.update_display = lambda: None
        harness._schedule_analysis_prewarm = lambda _idx: None
        harness._initial_frame_nav_ts = None
        calls = []
        harness._mark_project_dirty = lambda reason="": calls.append(str(reason))

        harness.on_slider_move(3)

        self.assertEqual(harness.current_frame_idx, 3)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
