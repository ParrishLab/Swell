import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.core.project_schema import default_project_state
from app.core.project_store import ProjectStore


class ProjectStoreRoundtripTests(unittest.TestCase):
    def test_save_load_roundtrip_single_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_path = Path(tmp) / "x.sdproj"
            state = default_project_state("1.0.0")
            state["events"] = [
                {
                    "id": "sd_event_001",
                    "masks_ref": "events/sd_event_001/masks.npz",
                    "prompts_ref": "events/sd_event_001/prompts.json",
                }
            ]
            masks = np.zeros((3, 4, 4), dtype=np.uint8)
            masks[1, 2, 2] = 1
            prompts = {"event_id": "sd_event_001", "frames": {"1": {"points": [{"x": 1, "y": 2, "label": 1}]}}}
            store = ProjectStore()
            store.save(
                project_path,
                project_state=state,
                images_manifest={"images": []},
                roi_data={"roi_points": []},
                event_payloads={"sd_event_001": {"masks": masks, "prompts": prompts}},
                embed_images=False,
            )
            loaded = store.load(project_path)
            self.assertEqual(loaded.project_state["schema_version"], state["schema_version"])
            self.assertEqual(loaded.event_payloads["sd_event_001"]["masks"].shape, (3, 4, 4))
            self.assertIn("frames", loaded.event_payloads["sd_event_001"]["prompts"])

    def test_save_load_roundtrip_with_draft_and_multi_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_path = Path(tmp) / "x.sdproj"
            state = default_project_state("1.0.0")
            state["events"] = [
                {
                    "id": "sd_event_001",
                    "masks_ref": "events/sd_event_001/masks.npz",
                    "masks_draft_ref": "events/sd_event_001/masks_draft.npz",
                    "prompts_ref": "events/sd_event_001/prompts.json",
                    "propagation_completed": False,
                    "analysis_output_dir": None,
                },
                {
                    "id": "sd_event_002",
                    "masks_ref": "events/sd_event_002/masks.npz",
                    "prompts_ref": "events/sd_event_002/prompts.json",
                    "propagation_completed": True,
                    "analysis_output_dir": None,
                },
            ]
            masks_1 = np.zeros((2, 3, 3), dtype=np.uint8)
            masks_1[0, 1, 1] = 1
            draft_1 = np.zeros((2, 3, 3), dtype=np.uint8)
            draft_1[1, 1, 2] = 1
            masks_2 = np.zeros((2, 3, 3), dtype=np.uint8)
            masks_2[1, 0, 0] = 1
            store = ProjectStore()
            store.save(
                project_path,
                project_state=state,
                images_manifest={"images": []},
                roi_data={"roi_points": []},
                event_payloads={
                    "sd_event_001": {"masks": masks_1, "masks_draft": draft_1, "prompts": {"frames": {}}},
                    "sd_event_002": {"masks": masks_2, "prompts": {"frames": {}}},
                },
                embed_images=False,
            )
            loaded = store.load(project_path)
            self.assertIn("sd_event_001", loaded.event_payloads)
            self.assertIn("sd_event_002", loaded.event_payloads)
            self.assertEqual(loaded.event_payloads["sd_event_001"]["masks_draft"].shape, (2, 3, 3))
            self.assertIsNone(loaded.event_payloads["sd_event_002"]["masks_draft"])


if __name__ == "__main__":
    unittest.main()
