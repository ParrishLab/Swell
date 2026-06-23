import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from swell.analysis.core.metrics import (
    compute_frame_metrics,
    compute_roi_metrics,
    compute_scale,
    generate_metrics_plots,
    smooth_boundary_fft,
    write_metrics_outputs,
)


class MetricsTests(unittest.TestCase):
    def test_compute_scale(self):
        result = compute_scale(((0, 0), (3, 4)), mm_length=2.0)
        self.assertAlmostEqual(result["scale_bar_pixels"], 5.0)
        self.assertAlmostEqual(result["px_per_mm"], 2.5)

    def test_smooth_boundary_fft_returns_input_for_short_boundary(self):
        b = np.array([[0.0, 0.0], [1.0, 1.0]])
        out = smooth_boundary_fft(b, n_keep=25)
        self.assertTrue(np.array_equal(out, b))

    def test_compute_frame_metrics_shapes(self):
        b1 = np.array([[1, 1], [1, 3], [3, 3], [3, 1]], dtype=np.float64)
        b2 = np.array([[0, 0], [0, 4], [4, 4], [4, 0]], dtype=np.float64)
        metrics = compute_frame_metrics([b1, b2], min_dist_px=0.1)
        self.assertEqual(metrics["areas_px"].shape[0], 2)
        self.assertEqual(metrics["avg_dist_px"].shape[0], 2)
        self.assertEqual(metrics["transition_valid"].shape[0], 2)
        self.assertTrue(np.isfinite(metrics["areas_px"][0]))

    def test_compute_frame_metrics_marks_valid_non_growth_without_faking_speed(self):
        b1 = np.array([[1, 1], [1, 3], [3, 3], [3, 1]], dtype=np.float64)
        metrics = compute_frame_metrics([b1, b1.copy()], min_dist_px=0.1)

        self.assertTrue(bool(metrics["transition_valid"][1]))
        self.assertTrue(np.isnan(metrics["avg_dist_px"][1]))

    def test_compute_roi_metrics(self):
        roi = np.zeros((4, 4), dtype=bool)
        roi[1:3, 1:3] = True
        areas = np.array([2.0, 4.0])
        avg_dist = np.array([np.nan, 3.0])
        out = compute_roi_metrics(roi, areas, avg_dist, px_per_mm=10.0, sec_per_frame=2.0)
        self.assertEqual(out["roi_pixels"], 4)
        self.assertTrue(np.isfinite(out["max_area_mm2"]))
        self.assertTrue(np.isfinite(out["overall_max_speed_um_per_sec"]))

    def test_write_outputs_and_generate_plots(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame_df = pd.DataFrame(
                {
                    "time_sec": [0.0, 1.0],
                    "speed_um_per_sec": [1.0, 2.0],
                    "area_mm2": [0.1, 0.2],
                    "relative_area_pct": [10.0, 20.0],
                }
            )
            summary = {"a": 1}
            write_metrics_outputs(tmp, frame_df, summary)
            generate_metrics_plots(tmp, frame_df, summary)
            self.assertTrue((Path(tmp) / "frame_metrics.csv").exists())
            self.assertTrue((Path(tmp) / "summary_metrics.csv").exists())
            self.assertTrue((Path(tmp) / "summary_metrics.json").exists())
            self.assertTrue((Path(tmp) / "propagation_speed.png").exists())
            self.assertTrue((Path(tmp) / "area_speed_combo.png").exists())


if __name__ == "__main__":
    unittest.main()
