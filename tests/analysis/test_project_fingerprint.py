import tempfile
import unittest
import os
from pathlib import Path

from swell.analysis.core.project_fingerprint import compute_file_fingerprint, fingerprints_match


class ProjectFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.bin"
            p.write_bytes(b"abc" * 1000)
            fp1 = compute_file_fingerprint(p)
            fp2 = compute_file_fingerprint(p)
            self.assertEqual(fp1["sha256_sampled"], fp2["sha256_sampled"])
            self.assertTrue(fingerprints_match(p, fp1))

    def test_fingerprint_ignores_timestamp_changes_for_identical_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.bin"
            copied = Path(tmp) / "copied.bin"
            source.write_bytes(b"same content")
            copied.write_bytes(source.read_bytes())
            expected = compute_file_fingerprint(source)
            stat = copied.stat()
            os.utime(copied, (stat.st_atime + 20, stat.st_mtime + 20))

            self.assertTrue(fingerprints_match(copied, expected))


if __name__ == "__main__":
    unittest.main()
