import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from swell.analysis.core.project_autosave import AutosaveSnapshot, ProjectAutosaveManager


class ProjectAutosaveRingTests(unittest.TestCase):
    def test_rotation_continues_after_highest_existing_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "autosave_1.swell").write_text("oldest", encoding="utf-8")
            (root / "autosave_2.swell").write_text("newest", encoding="utf-8")
            mgr = ProjectAutosaveManager(lambda: None, lambda *_args: None, root, max_slots=3)
            try:
                self.assertEqual(mgr._next_slot_path().name, "autosave_3.swell")
            finally:
                mgr.stop()

    def test_existing_slot_detection_uses_configured_project_extension(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "swell.analysis.core.project_autosave.PROJECT_EXTENSION", ".sdproj"
        ):
            root = Path(tmp)
            (root / "autosave_2.sdproj").write_text("recovery", encoding="utf-8")
            mgr = ProjectAutosaveManager(lambda: None, lambda *_args: None, root, max_slots=3)
            try:
                self.assertEqual(mgr._next_slot_path().name, "autosave_3.sdproj")
            finally:
                mgr.stop()

    def test_ring_rotation_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            writes = []

            def snapshot():
                return AutosaveSnapshot(
                    project_state={},
                    images_manifest={},
                    roi_data={},
                    event_payloads={},
                    embed_images=False,
                )

            def writer(_snapshot: AutosaveSnapshot, path: Path):
                writes.append(path.name)
                path.write_text("ok", encoding="utf-8")

            mgr = ProjectAutosaveManager(snapshot, writer, tmp, max_slots=3, debounce_sec=0.05)
            for _ in range(4):
                mgr.schedule("x")
                time.sleep(0.15)
            time.sleep(0.2)
            mgr.stop()

            self.assertGreaterEqual(len(writes), 3)
            expected = {f"autosave_{i}.swell" for i in (1, 2, 3)}
            self.assertTrue(set(p.name for p in Path(tmp).glob("autosave_*.swell")).issubset(expected))

    def test_tagged_rotation_naming(self):
        with tempfile.TemporaryDirectory() as tmp:
            tag_holder = {"tag": "Mouse A"}

            def snapshot():
                return AutosaveSnapshot(
                    project_state={},
                    images_manifest={},
                    roi_data={},
                    event_payloads={},
                    embed_images=False,
                )

            def writer(_snapshot: AutosaveSnapshot, path: Path):
                path.write_text("ok", encoding="utf-8")

            mgr = ProjectAutosaveManager(
                snapshot,
                writer,
                tmp,
                max_slots=3,
                debounce_sec=0.05,
                name_tag_provider=lambda: tag_holder["tag"],
            )
            for _ in range(5):
                mgr.schedule("x")
                time.sleep(0.15)
            time.sleep(0.2)
            mgr.stop()

            files = sorted(p.name for p in Path(tmp).glob("*.swell"))
            self.assertTrue(any(name.startswith("mouse_a_autosave_") for name in files))
            self.assertTrue(all(name.endswith(".swell") for name in files))


if __name__ == "__main__":
    unittest.main()
