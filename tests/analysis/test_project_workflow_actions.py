import unittest
from pathlib import Path

from sdapp.analysis.core import project_workflow


class ProjectWorkflowActionsTests(unittest.TestCase):
    def test_evaluate_close_requirements_reports_propagation_state(self):
        app = type("App", (), {})()
        app.frames_raw = [object()]
        app.current_project_path = None
        app._is_propagation_running = lambda: True
        req = project_workflow.evaluate_close_requirements(app)
        self.assertTrue(req.has_running_propagation)

    def test_save_project_to_path_uses_host_saver_in_host_mode(self):
        calls = []

        class _App:
            _host_mode = True
            current_project_path = None
            project_dirty = True
            _host_project_saver = staticmethod(lambda path: {"ok": True, "project_path": path})

            @staticmethod
            def _emit_host_sync(reason):  # noqa: ARG004
                calls.append("sync")
                return {"ok": True}

            @staticmethod
            def _host_project_saved_notifier(path):
                calls.append(path)

            @staticmethod
            def log_success(_ctx, _msg):
                calls.append("saved")

            @staticmethod
            def _build_project_payload():
                raise AssertionError("host-mode save should bypass analysis project store writer")

        app = _App()
        target = "/tmp/host_mode_save.sdproj"
        project_workflow.save_project_to_path(app, target, is_autosave=False)
        expected = str(Path(target).expanduser().resolve())
        self.assertEqual(app.current_project_path, expected)
        self.assertEqual(calls[0], "sync")
        self.assertIn(expected, calls)

    def test_save_project_to_path_raises_without_host_saver(self):
        class _App:
            _host_mode = True
            _host_project_saver = None

        with self.assertRaises(RuntimeError):
            project_workflow.save_project_to_path(_App(), "/tmp/no_host_saver.sdproj", is_autosave=False)

if __name__ == "__main__":
    unittest.main()
