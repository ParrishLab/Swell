import tempfile
import unittest
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from swell.analysis.core.project_schema import default_project_state
from swell.analysis.core.project_store import ProjectStore


class ImageEmbedToggleTests(unittest.TestCase):
    def test_embed_toggle_controls_images_folder_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "a.png"
            img.write_bytes(b"fake")
            state = default_project_state("1.0.0")
            state["events"] = [
                {"id": "event_001", "masks_ref": "events/event_001/masks.npz", "prompts_ref": "events/event_001/prompts.json"}
            ]
            manifest = {"images": [{"id": "image_1", "absolute_path": str(img), "relative_path": str(img.name)}]}
            payloads = {"event_001": {"masks": np.zeros((1, 2, 2), dtype=np.uint8), "prompts": {}}}
            store = ProjectStore()

            out1 = Path(tmp) / "no_embed.swell"
            out2 = Path(tmp) / "embed.swell"
            store.save(out1, state, manifest, {}, payloads, embed_images=False)
            store.save(out2, state, manifest, {}, payloads, embed_images=True)

            with ZipFile(out1, "r") as zf:
                self.assertFalse(any(name.startswith("images/") for name in zf.namelist()))
            with ZipFile(out2, "r") as zf:
                self.assertTrue(any(name.startswith("images/") for name in zf.namelist()))

    def test_embed_duplicate_basenames_uses_unique_archive_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dir_a = root / "A"
            dir_b = root / "B"
            dir_a.mkdir()
            dir_b.mkdir()
            img_a = dir_a / "1.png"
            img_b = dir_b / "1.png"
            img_a.write_bytes(b"from-a")
            img_b.write_bytes(b"from-b")
            state = default_project_state("1.0.0")
            state["events"] = [
                {"id": "event_001", "masks_ref": "events/event_001/masks.npz", "prompts_ref": "events/event_001/prompts.json"}
            ]
            manifest = {
                "images": [
                    {"id": "image_a", "absolute_path": str(img_a), "relative_path": "A/1.png"},
                    {"id": "image_b", "absolute_path": str(img_b), "relative_path": "B/1.png"},
                ]
            }
            payloads = {"event_001": {"masks": np.zeros((2, 2, 2), dtype=np.uint8), "prompts": {}}}
            store = ProjectStore()
            out = root / "embed_dupes.swell"

            store.save(out, state, manifest, {}, payloads, embed_images=True)

            with ZipFile(out, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("images/1.png", names)
                self.assertIn("images/1_2.png", names)
                index = json.loads(zf.read("images_embedded.json").decode("utf-8"))
                self.assertEqual(index["embedded"]["image_a"], "images/1.png")
                self.assertEqual(index["embedded"]["image_b"], "images/1_2.png")

            extract_dir = root / "extracted"
            loaded = store.load(out, extract_embedded_to=extract_dir)

            self.assertNotEqual(loaded.embedded_image_paths["image_a"], loaded.embedded_image_paths["image_b"])
            self.assertEqual(Path(loaded.embedded_image_paths["image_a"]).read_bytes(), b"from-a")
            self.assertEqual(Path(loaded.embedded_image_paths["image_b"]).read_bytes(), b"from-b")


if __name__ == "__main__":
    unittest.main()
