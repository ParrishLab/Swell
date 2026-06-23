import tempfile
import unittest
from pathlib import Path

from swell.analysis.utils.paths import resolve_existing_directory


class PathsTests(unittest.TestCase):
    def test_resolve_existing_directory_uses_fallback_for_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = resolve_existing_directory("", app_root=tmp, fallback_dir=tmp)
            self.assertEqual(Path(result).resolve(), Path(tmp).resolve())

    def test_resolve_existing_directory_returns_existing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp) / "child"
            child.mkdir()
            result = resolve_existing_directory("child", app_root=tmp, fallback_dir=tmp)
            self.assertEqual(Path(result), child.resolve())

    def test_resolve_existing_directory_returns_parent_for_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "x.txt"
            file_path.write_text("x", encoding="utf-8")
            result = resolve_existing_directory(str(file_path), app_root=tmp, fallback_dir=tmp)
            self.assertEqual(Path(result), Path(tmp).resolve())


if __name__ == "__main__":
    unittest.main()
