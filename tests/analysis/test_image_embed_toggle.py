import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from sdapp.analysis.core.project_schema import default_project_state
from sdapp.analysis.core.project_store import ProjectStore


class ImageEmbedToggleTests(unittest.TestCase):
    def test_embed_toggle_controls_images_folder_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "a.png"
            img.write_bytes(b"fake")
            state = default_project_state("1.0.0")
            state["events"] = [
                {"id": "sd_event_001", "masks_ref": "events/sd_event_001/masks.npz", "prompts_ref": "events/sd_event_001/prompts.json"}
            ]
            manifest = {"images": [{"id": "image_1", "absolute_path": str(img), "relative_path": str(img.name)}]}
            payloads = {"sd_event_001": {"masks": np.zeros((1, 2, 2), dtype=np.uint8), "prompts": {}}}
            store = ProjectStore()

            out1 = Path(tmp) / "no_embed.sdproj"
            out2 = Path(tmp) / "embed.sdproj"
            store.save(out1, state, manifest, {}, payloads, embed_images=False)
            store.save(out2, state, manifest, {}, payloads, embed_images=True)

            with ZipFile(out1, "r") as zf:
                self.assertFalse(any(name.startswith("images/") for name in zf.namelist()))
            with ZipFile(out2, "r") as zf:
                self.assertTrue(any(name.startswith("images/") for name in zf.namelist()))


if __name__ == "__main__":
    unittest.main()
