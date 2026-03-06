import tempfile
import unittest
from pathlib import Path

from app.core.project_fingerprint import compute_file_fingerprint, fingerprints_match


class ProjectFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.bin"
            p.write_bytes(b"abc" * 1000)
            fp1 = compute_file_fingerprint(p)
            fp2 = compute_file_fingerprint(p)
            self.assertEqual(fp1["sha256_sampled"], fp2["sha256_sampled"])
            self.assertTrue(fingerprints_match(p, fp1))


if __name__ == "__main__":
    unittest.main()
