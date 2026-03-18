import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from sdapp.analysis.core.io import IOActions


class _DummyIO(IOActions):
    def __init__(self):
        self.warnings = []
        self._input_source_hint = ""
        self._baseline_frame_count = 30
        self.root = object()
        self.app_root = "."
        self._selected_import_files = None

    def log_warn(self, context, message):
        self.warnings.append((context, message))

    def get_input_source_hint(self):
        return self._input_source_hint

    def set_input_source_hint(self, value):
        self._input_source_hint = str(value)

    def get_baseline_frame_count(self):
        return int(self._baseline_frame_count)


class IOImportTests(unittest.TestCase):
    def test_single_multipage_tiff_file_expands_to_multiple_frames(self):
        dummy = _DummyIO()
        with patch("sdapp.analysis.core.io.tifffile.imread", return_value=np.zeros((3, 4, 4), dtype=np.uint16)):
            frames, names = dummy._load_frames_and_names([Path("stack.tif")])
        self.assertEqual(len(frames), 3)
        self.assertEqual(names, ["stack.tif_p1", "stack.tif_p2", "stack.tif_p3"])

    def test_mixed_file_selection_loads_supported_extensions(self):
        dummy = _DummyIO()

        def fake_tiff_read(_path):
            return np.zeros((4, 4), dtype=np.uint8)

        def fake_cv_read(_path, _flag):
            return np.zeros((4, 4, 3), dtype=np.uint8)

        with patch("sdapp.analysis.core.io.tifffile.imread", side_effect=fake_tiff_read), patch(
            "sdapp.analysis.core.io.cv2.imread", side_effect=fake_cv_read
        ):
            frames, names = dummy._load_frames_and_names([Path("a.tif"), Path("b.png")])
        self.assertEqual(len(frames), 2)
        self.assertEqual(names, ["a.tif", "b.png"])

    def test_dimension_mismatch_frames_are_skipped(self):
        dummy = _DummyIO()

        def fake_tiff_read(path):
            if str(path).endswith("a.tif"):
                return np.zeros((4, 4), dtype=np.uint8)
            return np.zeros((5, 5), dtype=np.uint8)

        with patch("sdapp.analysis.core.io.tifffile.imread", side_effect=fake_tiff_read):
            frames, names = dummy._load_frames_and_names([Path("a.tif"), Path("b.tif")])
        self.assertEqual(len(frames), 1)
        self.assertEqual(names, ["a.tif"])
        self.assertTrue(any("Dimension mismatch" in msg for _ctx, msg in dummy.warnings))

    def test_file_selection_order_preserved(self):
        dummy = _DummyIO()
        with patch("sdapp.analysis.core.io.cv2.imread", return_value=np.zeros((4, 4, 3), dtype=np.uint8)):
            frames, names = dummy._load_frames_and_names([Path("b.png"), Path("a.png")])
        self.assertEqual(len(frames), 2)
        self.assertEqual(names, ["b.png", "a.png"])

    def test_validate_selected_files_rejects_unsupported_and_duplicates(self):
        dummy = _DummyIO()
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.is_dir", return_value=False), patch(
            "os.access", return_value=True
        ):
            valid, rejected = dummy._validate_selected_files(
                ["/tmp/a.png", "/tmp/a.png", "/tmp/b.txt"]
            )
        self.assertEqual([p.name for p in valid], ["a.png"])
        self.assertEqual(len(rejected), 2)

    def test_browse_input_files_mixed_valid_invalid_warns_and_keeps_valid(self):
        dummy = _DummyIO()
        with patch("sdapp.analysis.core.io.resolve_existing_directory", return_value="."), patch(
            "sdapp.analysis.core.io.filedialog.askopenfilenames",
            return_value=("/tmp/a.png", "/tmp/b.txt"),
        ), patch.object(
            dummy,
            "_validate_selected_files",
            return_value=([Path("/tmp/a.png")], [("b.txt", "unsupported extension")]),
        ), patch(
            "sdapp.analysis.core.io.messagebox.showwarning"
        ) as warn_mock:
            selected = dummy.browse_input_files()
        self.assertEqual(selected, [Path("/tmp/a.png")])
        self.assertEqual(dummy._selected_import_files, [Path("/tmp/a.png")])
        self.assertEqual(dummy.get_input_source_hint(), "/tmp/a.png")
        warn_mock.assert_called_once()

    def test_browse_input_files_all_invalid_keeps_previous_state(self):
        dummy = _DummyIO()
        dummy._selected_import_files = [Path("/tmp/old.png")]
        dummy.set_input_source_hint("old")
        with patch("sdapp.analysis.core.io.resolve_existing_directory", return_value="."), patch(
            "sdapp.analysis.core.io.filedialog.askopenfilenames",
            return_value=("/tmp/bad.txt",),
        ), patch.object(
            dummy,
            "_validate_selected_files",
            return_value=([], [("bad.txt", "unsupported extension")]),
        ), patch(
            "sdapp.analysis.core.io.messagebox.showwarning"
        ) as warn_mock:
            selected = dummy.browse_input_files()
        self.assertIsNone(selected)
        self.assertEqual(dummy._selected_import_files, [Path("/tmp/old.png")])
        self.assertEqual(dummy.get_input_source_hint(), "old")
        warn_mock.assert_called_once()

    def test_browse_input_folder_clears_selected_files(self):
        dummy = _DummyIO()
        dummy._selected_import_files = [Path("/tmp/a.png")]
        with patch("sdapp.analysis.core.io.resolve_existing_directory", return_value="."), patch(
            "sdapp.analysis.core.io.filedialog.askdirectory", return_value="/tmp/images"
        ):
            result = dummy.browse_input_folder()
        self.assertEqual(result, "/tmp/images")
        self.assertIsNone(dummy._selected_import_files)
        self.assertEqual(dummy.get_input_source_hint(), "/tmp/images")


if __name__ == "__main__":
    unittest.main()
