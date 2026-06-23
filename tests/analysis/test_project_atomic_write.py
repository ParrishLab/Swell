import tempfile
import unittest
from pathlib import Path

import numpy as np

from swell.analysis.core.project_schema import default_project_state
from swell.analysis.core.project_store import ProjectStore


class ProjectAtomicWriteTests(unittest.TestCase):
    def test_atomic_write_replaces_target_and_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "p.swell"
            state = default_project_state("1.0.0")
            state["events"] = [
                {"id": "event_001", "masks_ref": "events/event_001/masks.npz", "prompts_ref": "events/event_001/prompts.json"}
            ]
            store = ProjectStore()
            store.save(
                out,
                project_state=state,
                images_manifest={"images": []},
                roi_data={},
                event_payloads={"event_001": {"masks": np.zeros((1, 2, 2), dtype=np.uint8), "prompts": {}}},
            )
            self.assertTrue(out.exists())
            tmp_files = list(Path(tmp).glob("*.swell.tmp"))
            self.assertEqual(tmp_files, [])


if __name__ == "__main__":
    unittest.main()
