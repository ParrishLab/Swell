import os
import tempfile
import time
import unittest
from pathlib import Path

from swell.analysis.core.project_store import cleanup_stale_temp_files


class ProjectTmpCleanupTests(unittest.TestCase):
    def test_cleanup_removes_only_old_matching_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_tmp = base / "old.sdproj.tmp"
            new_tmp = base / "new.sdproj.tmp"
            other = base / "keep.txt"
            old_tmp.write_text("x", encoding="utf-8")
            new_tmp.write_text("y", encoding="utf-8")
            other.write_text("z", encoding="utf-8")

            old_ts = time.time() - 90000
            os.utime(old_tmp, (old_ts, old_ts))
            removed = cleanup_stale_temp_files(base, older_than_sec=86400)

            self.assertEqual(removed, 1)
            self.assertFalse(old_tmp.exists())
            self.assertTrue(new_tmp.exists())
            self.assertTrue(other.exists())


if __name__ == "__main__":
    unittest.main()
