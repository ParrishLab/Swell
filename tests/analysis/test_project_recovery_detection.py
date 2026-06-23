import tempfile
import time
import unittest
from pathlib import Path

from swell.analysis.core.project_autosave import AutosaveSnapshot, ProjectAutosaveManager


class ProjectRecoveryDetectionTests(unittest.TestCase):
    def test_newest_autosave_if_newer_than(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.sdproj"
            base.write_text("base", encoding="utf-8")
            time.sleep(0.02)

            def snapshot():
                return AutosaveSnapshot(
                    project_state={},
                    images_manifest={},
                    roi_data={},
                    event_payloads={},
                    embed_images=False,
                )

            def writer(_snapshot: AutosaveSnapshot, path: Path):
                path.write_text("auto", encoding="utf-8")

            mgr = ProjectAutosaveManager(snapshot, writer, tmp, max_slots=3, debounce_sec=0.01)
            mgr.schedule("x")
            time.sleep(0.15)
            newest = mgr.newest_autosave_if_newer_than(base)
            mgr.stop()
            self.assertIsNotNone(newest)


if __name__ == "__main__":
    unittest.main()
