import unittest

from sdapp.analysis.core.analysis_controller import AnalysisController


class AnalysisControllerMetricsRemovedTests(unittest.TestCase):
    def test_controller_no_longer_exposes_run_metrics_analysis(self):
        controller = AnalysisController(
            root=None,
            app_root=".",
            get_frame_count=lambda: 0,
            get_raw_frame=lambda _idx: None,
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
            get_scale_points=lambda: [],
            set_scale_points=lambda _v: None,
            get_last_scale_image_path=lambda: "",
            set_last_scale_image_path=lambda _v: None,
            get_roi_mask=lambda: None,
            set_roi_mask=lambda _v: None,
            get_roi_points=lambda: [],
            set_roi_points=lambda _v: None,
            update_display=lambda: None,
            log_info=lambda *_args: None,
            log_success=lambda *_args: None,
        )
        self.assertFalse(hasattr(controller, "run_metrics_analysis"))


if __name__ == "__main__":
    unittest.main()
