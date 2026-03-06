import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.core.mask_import_dialog import MaskImportDialogService


class MaskImportDialogServiceTests(unittest.TestCase):
    def test_path_natural_key_sort(self):
        svc = MaskImportDialogService()
        names = [Path("mask_10.tif"), Path("mask_2.tif"), Path("mask_1.tif")]
        ordered = sorted(names, key=svc.path_natural_key)
        self.assertEqual([p.name for p in ordered], ["mask_1.tif", "mask_2.tif", "mask_10.tif"])

    def test_collect_mask_paths_from_folder_filters_and_sorts(self):
        svc = MaskImportDialogService()
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "z.txt").write_text("x", encoding="utf-8")
            cv2.imwrite(str(d / "mask_10.png"), np.zeros((2, 2), dtype=np.uint8))
            cv2.imwrite(str(d / "mask_2.png"), np.zeros((2, 2), dtype=np.uint8))
            out = svc.collect_mask_paths_from_folder(d)
            self.assertEqual([p.name for p in out], ["mask_2.png", "mask_10.png"])

    def test_load_external_mask_images(self):
        svc = MaskImportDialogService()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.png"
            arr = np.zeros((3, 3), dtype=np.uint8)
            arr[1, 1] = 255
            cv2.imwrite(str(p), arr)
            masks = svc.load_external_mask_images([p])
            self.assertEqual(len(masks), 1)
            self.assertTrue(bool(masks[0][1, 1]))


if __name__ == "__main__":
    unittest.main()
