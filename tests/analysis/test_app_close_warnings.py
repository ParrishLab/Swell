import unittest
from unittest.mock import patch

from sdapp.analysis.app import SDSegmentationApp


class _MgrStub:
    def __init__(self):
        self.stopped = False

    def stop(self, *args, **kwargs):
        self.stopped = True


class _RootStub:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class AppCloseWarningsTests(unittest.TestCase):
    def _make_app(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.root = _RootStub()
        app.autosave_manager = _MgrStub()
        app.inference_manager = _MgrStub()
        app.cleanup_temp_files = lambda: None
        app._ui_alive = lambda: True
        app.project_dirty = False
        app._collect_nonempty_final_mask_frames = lambda: set()
        app.save_current_masks = lambda: None
        return app

    @patch("sdapp.analysis.app.messagebox.askyesno")
    def test_cancel_when_propagation_running(self, ask_mock):
        app = self._make_app()
        app._is_propagation_running = lambda: True
        app.frames_raw = []
        app.current_project_path = None
        ask_mock.return_value = False
        app.on_close()
        self.assertFalse(app.root.destroyed)
        self.assertFalse(app.autosave_manager.stopped)

    @patch("sdapp.analysis.app.messagebox.askyesno")
    def test_close_without_propagation_prompt_closes(self, ask_mock):
        app = self._make_app()
        app._is_propagation_running = lambda: False
        app.frames_raw = [object()]
        app.current_project_path = None
        app._shutdown_model_resources = lambda: setattr(app, "_shutdown_called", True)
        app._emit_host_sync = lambda reason="": {"ok": True, "reason": reason}
        app.on_close()
        self.assertTrue(app.root.destroyed)
        self.assertTrue(app.autosave_manager.stopped)
        self.assertTrue(app.inference_manager.stopped)
        self.assertTrue(getattr(app, "_shutdown_called", False))
        ask_mock.assert_not_called()

    @patch("sdapp.analysis.app.messagebox.askyesnocancel")
    @patch("sdapp.analysis.app.messagebox.askyesno")
    def test_close_prompts_to_save_unsaved_masks_and_cancels(self, ask_yesno_mock, ask_ync_mock):
        app = self._make_app()
        app._is_propagation_running = lambda: False
        app.frames_raw = [object()]
        app.current_project_path = "/tmp/proj.sdproj"
        app.project_dirty = True
        app._collect_nonempty_final_mask_frames = lambda: {1, 2}
        ask_ync_mock.return_value = None
        app.on_close()
        self.assertFalse(app.root.destroyed)
        self.assertFalse(app.autosave_manager.stopped)
        ask_yesno_mock.assert_not_called()

    @patch("sdapp.analysis.app.messagebox.askyesnocancel")
    @patch("sdapp.analysis.app.messagebox.askyesno")
    def test_close_prompts_to_save_unsaved_masks_and_runs_save_flow(self, ask_yesno_mock, ask_ync_mock):
        app = self._make_app()
        app._is_propagation_running = lambda: False
        app.frames_raw = [object()]
        app.current_project_path = "/tmp/proj.sdproj"
        app.project_dirty = True
        app._collect_nonempty_final_mask_frames = lambda: {1}
        called = []

        def _save():
            called.append("save")
            app.project_dirty = False

        app.save_current_masks = _save
        ask_ync_mock.return_value = True
        app.on_close()
        self.assertEqual(called, ["save"])
        self.assertTrue(app.root.destroyed)
        self.assertTrue(app.autosave_manager.stopped)
        ask_yesno_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
