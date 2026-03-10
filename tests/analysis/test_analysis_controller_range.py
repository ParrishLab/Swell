import unittest
from unittest.mock import patch

import numpy as np

from sdapp.analysis.core.analysis_controller import AnalysisController


class AnalysisControllerRangeTests(unittest.TestCase):
    def _make_controller(self, analysis_range, nonempty_frames):
        frames = [np.zeros((6, 6), dtype=np.float32) for _ in range(5)]
        masks_cache = {i: np.ones((6, 6), dtype=bool) for i in nonempty_frames}
        roi_mask = np.ones((6, 6), dtype=bool)

        captured = {"writes": []}

        controller = AnalysisController(
            root=None,
            app_root=".",
            get_frames_raw=lambda: frames,
            get_masks_cache=lambda: masks_cache,
            get_paint_layers=lambda: {},
            get_points=lambda: {},
            get_frame_names=lambda: [f"f{i}.png" for i in range(5)],
            get_input_folder=lambda: ".",
            get_compose_final_mask_for_frame=lambda idx: np.ones((6, 6), dtype=bool) if idx in nonempty_frames else None,
            get_nonempty_final_mask_frames=lambda: set(nonempty_frames),
            get_output_folder=lambda: ".",
            get_export_range=lambda: (0, 4),
            get_analysis_range=lambda: analysis_range,
            get_seconds_per_frame=lambda: 1.0,
            get_scale_px_per_mm=lambda: 10.0,
            set_scale_px_per_mm=lambda _v: None,
            get_scale_points=lambda: [],
            set_scale_points=lambda _v: None,
            get_last_scale_image_path=lambda: "",
            set_last_scale_image_path=lambda _v: None,
            get_roi_mask=lambda: roi_mask,
            set_roi_mask=lambda _v: None,
            get_roi_points=lambda: [],
            set_roi_points=lambda _v: None,
            update_display=lambda: None,
            log_info=lambda *_args: None,
            log_success=lambda *_args: None,
        )

        def fake_compute_frame_metrics(boundaries, min_dist_px):
            n = len(boundaries)
            return {"areas_px": np.ones(n, dtype=float), "avg_dist_px": np.ones(n, dtype=float)}

        def fake_compute_roi_metrics(roi_mask, areas_px, avg_dist_px, px_per_mm, sec_per_frame):
            n = len(areas_px)
            return {
                "area_mm2": np.ones(n, dtype=float) * 0.1,
                "speed_um_per_sec": np.ones(n, dtype=float) * 2.0,
                "overall_avg_speed_um_per_sec": 2.0,
                "max_area_mm2": 0.1,
                "relative_area_pct": 10.0,
                "roi_area_mm2": 1.0,
                "roi_pixels": int(np.count_nonzero(roi_mask)),
                "px_per_mm": px_per_mm,
                "um_per_px": 100.0,
                "mm_per_px": 0.1,
                "sec_per_frame": float(sec_per_frame),
            }

        def fake_write_metrics_outputs(_out_dir, frame_df, summary):
            captured["writes"].append((frame_df.copy(), dict(summary)))

        patches = [
            patch("sdapp.analysis.core.analysis_controller.extract_primary_boundary", return_value=np.array([[0.0, 0.0], [1.0, 1.0]])),
            patch("sdapp.analysis.core.analysis_controller.smooth_boundary_fft", side_effect=lambda b, n_keep: b),
            patch("sdapp.analysis.core.analysis_controller.compute_frame_metrics", side_effect=fake_compute_frame_metrics),
            patch("sdapp.analysis.core.analysis_controller.compute_roi_metrics", side_effect=fake_compute_roi_metrics),
            patch("sdapp.analysis.core.analysis_controller.write_metrics_outputs", side_effect=fake_write_metrics_outputs),
            patch("sdapp.analysis.core.analysis_controller.generate_metrics_plots", return_value=None),
            patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo", return_value=None),
            patch("sdapp.analysis.core.analysis_controller.messagebox.askyesno", return_value=True),
        ]
        return controller, captured, patches

    def test_metrics_use_only_analysis_range_frames(self):
        controller, captured, patches = self._make_controller((1, 2), {0, 1, 2, 3})
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch(
            "sdapp.analysis.core.analysis_controller.messagebox.showwarning", return_value=None
        ):
            controller.run_metrics_analysis()
        self.assertEqual(len(captured["writes"]), 1)
        frame_df, summary = captured["writes"][0]
        self.assertEqual(list(frame_df["frame_index"]), [1, 2])
        self.assertEqual(summary["range_start_frame"], 2)
        self.assertEqual(summary["range_end_frame"], 3)

    def test_empty_filtered_range_shows_specific_warning(self):
        controller, _captured, patches = self._make_controller((3, 4), {0, 1})
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch(
            "sdapp.analysis.core.analysis_controller.messagebox.showwarning"
        ) as warn_mock:
            controller.run_metrics_analysis()
        warn_mock.assert_called_with("No Masks", "No generated masks found in selected analysis range.")


if __name__ == "__main__":
    unittest.main()
