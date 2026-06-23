import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from swell.analysis.core.project_schema import default_project_state
from swell.analysis.core import project_store as project_store_mod
from swell.analysis.core.project_store import ProjectStore, _fsync_parent_directory


class ProjectStoreAtomicDurabilityTests(unittest.TestCase):
    def test_save_calls_parent_directory_fsync_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "p.sdproj"
            state = default_project_state("1.0.0")
            state["events"] = [
                {"id": "sd_event_001", "masks_ref": "events/sd_event_001/masks.npz", "prompts_ref": "events/sd_event_001/prompts.json"}
            ]
            store = ProjectStore()
            with patch.object(project_store_mod, "_fsync_parent_directory") as fsync_mock:
                store.save(
                    out,
                    project_state=state,
                    images_manifest={"images": []},
                    roi_data={},
                    event_payloads={"sd_event_001": {"masks": np.zeros((1, 2, 2), dtype=np.uint8), "prompts": {}}},
                )
                self.assertTrue(fsync_mock.called)

    def test_parent_fsync_best_effort_on_open_error(self):
        with patch("swell.analysis.core.project_store.os.open", side_effect=OSError("not supported")):
            _fsync_parent_directory(Path("/tmp/x.sdproj"))


if __name__ == "__main__":
    unittest.main()
