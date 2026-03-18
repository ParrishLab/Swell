import unittest

import numpy as np

from sdapp.analysis.core.analysis_controller import AnalysisController


class AnalysisControllerHelperTests(unittest.TestCase):
    def _make_controller(self):
        return AnalysisController(
            root=None,
            app_root=".",
            get_frames_raw=lambda: None,
            get_masks_cache=lambda: {},
            get_paint_layers=lambda: {},
            get_points=lambda: {},
            get_frame_names=lambda: [],
            get_import_source_hint=lambda: "",
            get_compose_final_mask_for_frame=lambda _idx: None,
            get_nonempty_final_mask_frames=lambda: set(),
            get_frames_per_sec=lambda: 1.0,
            get_scale_px_per_mm=lambda: None,
            set_scale_px_per_mm=lambda _v: None,
            get_scale_points=lambda: None,
            set_scale_points=lambda _v: None,
            get_last_scale_image_path=lambda: "",
            set_last_scale_image_path=lambda _v: None,
            get_roi_mask=lambda: None,
            set_roi_mask=lambda _v: None,
            get_roi_points=lambda: None,
            set_roi_points=lambda _v: None,
            update_display=lambda: None,
            log_info=lambda _c, _m: None,
            log_success=lambda _c, _m: None,
        )

    def test_snap_scale_points_axis_horizontal(self):
        c = self._make_controller()
        p1, p2, mode = c._snap_scale_points_axis((0, 0), (10, 1))
        self.assertEqual(mode, "horizontal")
        self.assertAlmostEqual(p1[1], p2[1])

    def test_compute_axis_unit_vertical(self):
        c = self._make_controller()
        ux, uy, nx, ny, mode = c._compute_axis_unit((0, 0), (1, 4))
        self.assertEqual(mode, "vertical")
        self.assertEqual((ux, uy), (0.0, 1.0))
        self.assertEqual((nx, ny), (-1.0, 0.0))

    def test_subpixel_peak_index_internal_point(self):
        c = self._make_controller()
        y = np.array([0.0, 1.0, 2.0, 1.0, 0.0], dtype=float)
        idx = c._subpixel_peak_index(y, 2)
        self.assertAlmostEqual(idx, 2.0, places=6)

    def test_refine_scale_bar_points_fallback_on_empty(self):
        c = self._make_controller()
        out = c._refine_scale_bar_points(np.array([], dtype=np.uint8), (1, 1), (5, 1))
        self.assertFalse(out["refined_ok"])
        self.assertTrue(out["fallback"])


if __name__ == "__main__":
    unittest.main()
