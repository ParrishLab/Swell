import tempfile
import unittest
from pathlib import Path

from app.core.autosave_naming import derive_autosave_tag


class AutosaveNamingTests(unittest.TestCase):
    def test_single_source_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "mouse_a"
            p.mkdir()
            f = p / "img_1.tif"
            f.write_text("x", encoding="utf-8")
            self.assertEqual(derive_autosave_tag([str(f)], ""), "mouse_a")

    def test_mixed_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a"
            p2 = Path(tmp) / "b"
            p1.mkdir()
            p2.mkdir()
            f1 = p1 / "x.tif"
            f2 = p2 / "y.tif"
            f1.write_text("x", encoding="utf-8")
            f2.write_text("y", encoding="utf-8")
            self.assertEqual(derive_autosave_tag([str(f1), str(f2)], ""), "mixed_images")

    def test_entry_folder_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "session_1"
            p.mkdir()
            self.assertEqual(derive_autosave_tag([], str(p)), "session_1")

    def test_empty_defaults_to_autosave(self):
        self.assertEqual(derive_autosave_tag([], ""), "autosave")


if __name__ == "__main__":
    unittest.main()
