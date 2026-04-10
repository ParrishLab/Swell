import tempfile
import unittest
from pathlib import Path
import zipfile

import numpy as np

from sdapp.analysis.core.project_schema import default_project_state
from sdapp.analysis.core.project_store import ProjectStore
from sdapp.shared.persistence.event_path import sanitize_event_path_segment


class ProjectStoreRoundtripTests(unittest.TestCase):
    def test_save_load_roundtrip_single_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_path = Path(tmp) / "x.sdproj"
            state = default_project_state("1.0.0")
            state["global"]["scale_px_per_mm"] = 2.5
            state["global"]["scale_points"] = [[10.0, 12.0], [30.0, 12.0]]
            state["global"]["scale_axis_lock"] = False
            state["global"]["scale_image_path"] = "/tmp/scale-ref.png"
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
            self.assertEqual(loaded.project_state["global"]["scale_points"], [[10.0, 12.0], [30.0, 12.0]])
            self.assertIs(loaded.project_state["global"]["scale_axis_lock"], False)
            self.assertEqual(loaded.project_state["global"]["scale_image_path"], "/tmp/scale-ref.png")
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

    def test_save_load_roundtrip_with_filesystem_unsafe_event_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_path = Path(tmp) / "unsafe.sdproj"
            unsafe_event_id = 'bad:event?*"<>|'
            state = default_project_state("1.0.0")
            state["events"] = [
                {
                    "id": unsafe_event_id,
                    "masks_ref": "events/bad/masks.npz",
                    "prompts_ref": "events/bad/prompts.json",
                }
            ]
            masks = np.zeros((2, 3, 3), dtype=np.uint8)
            store = ProjectStore()
            store.save(
                project_path,
                project_state=state,
                images_manifest={"images": []},
                roi_data={"roi_points": []},
                event_payloads={unsafe_event_id: {"masks": masks, "prompts": {"frames": {}}}},
                embed_images=False,
            )

            expected_segment = sanitize_event_path_segment(unsafe_event_id)
            with zipfile.ZipFile(project_path, "r") as zf:
                names = set(zf.namelist())
                self.assertIn(f"events/{expected_segment}/masks.npz", names)
                self.assertIn(f"events/{expected_segment}/prompts.json", names)

            loaded = store.load(project_path)
            self.assertIn(unsafe_event_id, loaded.event_payloads)
            self.assertEqual(loaded.event_payloads[unsafe_event_id]["masks"].shape, (2, 3, 3))


if __name__ == "__main__":
    unittest.main()
