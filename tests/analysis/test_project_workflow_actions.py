import unittest
from pathlib import Path

from sdapp.analysis.core import project_workflow


class ProjectWorkflowActionsTests(unittest.TestCase):
    def test_evaluate_new_project_requirements(self):
        app = type("App", (), {})()
        app.frames_raw = [object()]
        app.project_dirty = True
        req = project_workflow.evaluate_new_project_requirements(app)
        self.assertTrue(req.needs_discard_prompt)

    def test_evaluate_close_requirements(self):
        app = type("App", (), {})()
        app.frames_raw = [object()]
        app.current_project_path = None
        app._is_propagation_running = lambda: True
        req = project_workflow.evaluate_close_requirements(app)
        self.assertTrue(req.has_running_propagation)
        self.assertTrue(req.not_saved_as_project)

    def test_evaluate_close_requirements_host_mode_skips_unsaved_gate(self):
        app = type("App", (), {})()
        app.frames_raw = [object()]
        app.current_project_path = None
        app._host_mode = True
        app._is_propagation_running = lambda: False
        req = project_workflow.evaluate_close_requirements(app)
        self.assertFalse(req.not_saved_as_project)

    def test_save_project_to_path_notifies_host_project_path(self):
        calls = []

        class _Store:
            def save(self, **_kwargs):
                return None

        class _App:
            project_store = _Store()
            app_context = None
            _project_embed_images = False
            current_project_path = None
            project_dirty = True

            @staticmethod
            def _build_project_payload():
                return {}, {}, {}, {}

            @staticmethod
            def _emit_host_sync(reason):  # noqa: ARG004
                return None

            @staticmethod
            def log_success(_ctx, _msg):
                return None

            @staticmethod
            def _host_project_saved_notifier(path):
                calls.append(path)

        app = _App()
        target = "/tmp/project_from_analysis.sdproj"
        project_workflow.save_project_to_path(app, target, is_autosave=False)
        expected = str(Path(target).expanduser().resolve())
        self.assertEqual(app.current_project_path, expected)
        self.assertEqual(calls, [expected])

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


if __name__ == "__main__":
    unittest.main()
