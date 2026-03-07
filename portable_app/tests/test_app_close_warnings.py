import unittest
from unittest.mock import patch

from app.app import SDSegmentationApp


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
        return app

    @patch("app.app.messagebox.askyesno")
    def test_cancel_when_propagation_running(self, ask_mock):
        app = self._make_app()
        app._is_propagation_running = lambda: True
        app.frames_raw = []
        app.current_project_path = None
        ask_mock.return_value = False
        app.on_close()
        self.assertFalse(app.root.destroyed)
        self.assertFalse(app.autosave_manager.stopped)

    @patch("app.app.messagebox.askyesno")
    def test_cancel_when_unsaved_project(self, ask_mock):
        app = self._make_app()
        app._is_propagation_running = lambda: False
        app.frames_raw = [object()]
        app.current_project_path = None
        ask_mock.return_value = False
        app.on_close()
        self.assertFalse(app.root.destroyed)
        self.assertFalse(app.autosave_manager.stopped)

    @patch("app.app.messagebox.askyesno")
    def test_host_mode_close_skips_unsaved_prompt_and_closes(self, ask_mock):
        app = self._make_app()
        app._is_propagation_running = lambda: False
        app.frames_raw = [object()]
        app.current_project_path = None
        app._host_mode = True
        app._shutdown_model_resources = lambda: setattr(app, "_shutdown_called", True)
        app._emit_host_sync = lambda reason="": {"ok": True, "reason": reason}
        app.on_close()
        self.assertTrue(app.root.destroyed)
        self.assertTrue(app.autosave_manager.stopped)
        self.assertTrue(app.inference_manager.stopped)
        self.assertTrue(getattr(app, "_shutdown_called", False))
        ask_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
