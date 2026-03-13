import unittest

from sdapp.analysis.app import SDSegmentationApp


class _SpinStub:
    def __init__(self, value):
        self.value = str(value)

    def get(self):
        return self.value

    def delete(self, _start, _end):
        self.value = ""

    def insert(self, _index, text):
        self.value = str(text)


class _SliderStub:
    def __init__(self):
        self.config = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)


class _SegStateStub:
    def invalidate_user_frames(self):
        return None

    def invalidate_final_mask_frames(self):
        return None


class AppExportRangeStateTests(unittest.TestCase):
    def _make_app_for_recompute(self, nonempty_frames):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.frames_raw = [object()] * 20
        app._export_range_auto_follow = True
        app._programmatic_spinbox_update = False
        app.spin_prop_start = _SpinStub(1)
        app.spin_prop_end = _SpinStub(20)
        app.spin_export_start = _SpinStub(1)
        app.spin_export_end = _SpinStub(20)
        app.slider_jump_markers = {}
        app._redraw_slider_overlay = lambda: None
        app.log_debug = lambda *_args: None
        app._collect_user_defined_frames = lambda: set()
        app._collect_nonempty_final_mask_frames = lambda: set(nonempty_frames)
        return app

    def test_recompute_updates_propagation_and_export_ranges(self):
        app = self._make_app_for_recompute({3, 7})
        app._recompute_slider_jump_markers()
        self.assertEqual(int(app.spin_prop_start.get()), 4)
        self.assertEqual(int(app.spin_prop_end.get()), 8)
        self.assertEqual(int(app.spin_export_start.get()), 4)
        self.assertEqual(int(app.spin_export_end.get()), 8)

    def test_finalize_load_resets_export_range_to_full_stack(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.frames_raw = [object()] * 12
        app.current_frame_idx = 0
        app.points = {}
        app.seg_state = _SegStateStub()
        app.selected_point = None
        app._export_range_auto_follow = False
        app._programmatic_spinbox_update = False
        app.spin_prop_start = _SpinStub(1)
        app.spin_prop_end = _SpinStub(1)
        app.spin_export_start = _SpinStub(1)
        app.spin_export_end = _SpinStub(1)
        app.slider = _SliderStub()
        app.update_display = lambda: None
        app._recompute_slider_jump_markers = lambda: None
        app._set_data_controls_enabled = lambda _enabled: None
        app._set_busy = lambda *_args: None
        app.log_success = lambda *_args: None
        app._finalize_load_ui()
        self.assertTrue(app._export_range_auto_follow)
        self.assertEqual(int(app.spin_export_start.get()), 1)
        self.assertEqual(int(app.spin_export_end.get()), 12)


if __name__ == "__main__":
    unittest.main()
