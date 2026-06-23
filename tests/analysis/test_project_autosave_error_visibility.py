import tempfile
import time
import unittest

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core.project_autosave import AutosaveSnapshot, ProjectAutosaveManager


class _LabelStub:
    def __init__(self):
        self.last = {}

    def configure(self, **kwargs):
        self.last.update(kwargs)


class ProjectAutosaveErrorVisibilityTests(unittest.TestCase):
    def test_manager_reports_write_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = []

            def snapshot():
                return AutosaveSnapshot(
                    project_state={},
                    images_manifest={},
                    roi_data={},
                    event_payloads={},
                    embed_images=False,
                )

            def writer(_snapshot, _path):
                raise PermissionError("denied")

            mgr = ProjectAutosaveManager(
                snapshot_callable=snapshot,
                write_callable=writer,
                autosave_dir=tmp,
                debounce_sec=0.02,
                on_error=lambda exc, ctx: errors.append((type(exc).__name__, ctx)),
            )
            mgr.schedule("test")
            time.sleep(0.12)
            mgr.stop()
            self.assertTrue(errors)
            self.assertEqual(errors[0][0], "PermissionError")
            self.assertTrue(errors[0][1].startswith("write:"))

    def test_app_callback_logs_and_sets_status(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        logs = []
        app.log_warn = lambda ctx, msg: logs.append((ctx, msg))
        app.lbl_status = _LabelStub()
        app._on_autosave_error(RuntimeError("boom"), "write:file.sdproj")
        self.assertTrue(logs)
        self.assertEqual(logs[0][0], "Autosave")
        self.assertIn("Autosave failed", logs[0][1])
        self.assertIn("Autosave warning", app.lbl_status.last.get("text", ""))
        self.assertEqual(app.lbl_status.last.get("foreground"), "orange")


if __name__ == "__main__":
    unittest.main()
