import unittest

from sdapp.analysis.app import SDSegmentationApp


class ProjectPathPreservationTests(unittest.TestCase):
    def test_apply_loaded_stack_preserves_source_paths_after_reset(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app._current_image_source_paths = ["old"]
        app._reset_for_new_import = lambda: setattr(app, "_current_image_source_paths", [])
        app._finalize_load_ui = lambda: None
        app.start_model_initialization = lambda **_kwargs: None
        app._mark_project_dirty = lambda _reason: None

        app._apply_loaded_stack(
            frames_raw=[object()],
            frames_sub=[object()],
            frames_sub_viz=[object()],
            frame_names=["f1"],
            source_paths=["/tmp/a.tif", "/tmp/b.tif"],
        )

        self.assertEqual(app._current_image_source_paths, ["/tmp/a.tif", "/tmp/b.tif"])


if __name__ == "__main__":
    unittest.main()
