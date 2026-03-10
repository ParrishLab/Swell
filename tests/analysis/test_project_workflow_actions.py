import unittest

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


if __name__ == "__main__":
    unittest.main()
