import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tifffile
from PIL import Image

from swell.analysis.core.io import IOActions
from swell.host.stack_reader import StackReader


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
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stack.tif"
            for idx in range(3):
                tifffile.imwrite(path, np.full((4, 4), idx, dtype=np.uint16), append=idx > 0)
            frames, names = dummy._load_frames_and_names([path])
        self.assertEqual(len(frames), 3)
        self.assertEqual(names, ["stack.tif_p1", "stack.tif_p2", "stack.tif_p3"])

    def test_mixed_file_selection_loads_supported_extensions(self):
        dummy = _DummyIO()

        with tempfile.TemporaryDirectory() as tmp:
            tiff_path = Path(tmp) / "a.tif"
            png_path = Path(tmp) / "b.png"
            tifffile.imwrite(tiff_path, np.zeros((4, 4), dtype=np.uint8))
            Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(png_path)
            frames, names = dummy._load_frames_and_names([tiff_path, png_path])
        self.assertEqual(len(frames), 2)
        self.assertEqual(names, ["a.tif", "b.png"])

    def test_dimension_mismatch_frames_are_rejected(self):
        dummy = _DummyIO()
        with tempfile.TemporaryDirectory() as tmp:
            a_path = Path(tmp) / "a.tif"
            b_path = Path(tmp) / "b.tif"
            tifffile.imwrite(a_path, np.zeros((4, 4), dtype=np.uint8))
            tifffile.imwrite(b_path, np.zeros((5, 5), dtype=np.uint8))
            with self.assertRaisesRegex(ValueError, "mixed frame dimensions"):
                dummy._load_frames_and_names([a_path, b_path])

    def test_file_selection_order_preserved(self):
        dummy = _DummyIO()
        with tempfile.TemporaryDirectory() as tmp:
            b_path = Path(tmp) / "b.png"
            a_path = Path(tmp) / "a.png"
            Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(b_path)
            Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(a_path)
            frames, names = dummy._load_frames_and_names([b_path, a_path])
        self.assertEqual(len(frames), 2)
        self.assertEqual(names, ["b.png", "a.png"])

    def test_tiny_rgb_tiff_is_one_color_frame(self):
        dummy = _DummyIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tiny.tif"
            rgb = np.zeros((4, 4, 3), dtype=np.uint8)
            rgb[:, :, 0] = 255
            tifffile.imwrite(path, rgb, photometric="rgb")
            frames, names = dummy._load_frames_and_names([path])

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].shape, (4, 4))
        self.assertEqual(names, ["tiny.tif"])

    def test_host_and_analysis_decoders_agree_on_oriented_planar_tiff(self):
        dummy = _DummyIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "planar.tif"
            rgb = np.zeros((3, 5, 7), dtype=np.uint8)
            rgb[0] = 200
            tifffile.imwrite(
                path,
                rgb,
                photometric="rgb",
                planarconfig="separate",
                extratags=[(274, "H", 1, 6, False)],
            )

            analysis_frames, _names = dummy._load_frames_and_names([path])
            host = StackReader()
            host.open_stack(tmp)
            host_frame = host.read_frame(0)

        self.assertEqual(len(analysis_frames), 1)
        np.testing.assert_array_equal(analysis_frames[0], host_frame)
        self.assertEqual(host_frame.shape, (7, 5))

    def test_corrupt_image_is_reported_while_valid_images_remain_available(self):
        dummy = _DummyIO()
        with tempfile.TemporaryDirectory() as tmp:
            valid = Path(tmp) / "a.png"
            corrupt = Path(tmp) / "b.tif"
            Image.fromarray(np.full((4, 4), 5, dtype=np.uint8)).save(valid)
            corrupt.write_bytes(b"II*\x00truncated")

            frames, names = dummy._load_frames_and_names([valid, corrupt])

        self.assertEqual(names, ["a.png"])
        self.assertEqual(len(frames), 1)
        self.assertTrue(any("b.tif" in message for _context, message in dummy.warnings))

    def test_process_stack_does_not_apply_partial_stack_after_dimension_error(self):
        class _Root:
            def __init__(self):
                self.callbacks = []

            def after(self, _delay, callback):
                self.callbacks.append(callback)

        dummy = _DummyIO()
        dummy.root = _Root()
        dummy.cleanup_temp_files = lambda: None
        dummy._current_image_source_paths = []
        dummy.log_error = lambda *_args: None
        dummy._set_busy = lambda *_args: None
        dummy.lbl_status = type("Status", (), {"configure": lambda *_args, **_kwargs: None})()
        applied = []
        dummy._apply_loaded_stack = lambda *_args, **_kwargs: applied.append(True)

        with tempfile.TemporaryDirectory() as tmp:
            a_path = Path(tmp) / "a.png"
            b_path = Path(tmp) / "b.png"
            Image.fromarray(np.zeros((4, 4), dtype=np.uint8)).save(a_path)
            Image.fromarray(np.zeros((5, 4), dtype=np.uint8)).save(b_path)
            dummy._process_stack([a_path, b_path])

        self.assertEqual(applied, [])

    def test_folder_import_uses_natural_frame_order(self):
        dummy = _DummyIO()
        with self.subTest("non_zero_padded_names"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                for name in ("frame10.png", "frame2.png", "frame1.png"):
                    (Path(tmp) / name).write_bytes(b"")

                ordered = dummy._collect_image_files_from_folder(tmp)

        self.assertEqual([p.name for p in ordered], ["frame1.png", "frame2.png", "frame10.png"])

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
        with patch("swell.analysis.core.io.resolve_existing_directory", return_value="."), patch(
            "swell.analysis.core.io.filedialog.askopenfilenames",
            return_value=("/tmp/a.png", "/tmp/b.txt"),
        ), patch.object(
            dummy,
            "_validate_selected_files",
            return_value=([Path("/tmp/a.png")], [("b.txt", "unsupported extension")]),
        ), patch(
            "swell.analysis.core.io.messagebox.showwarning"
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
        with patch("swell.analysis.core.io.resolve_existing_directory", return_value="."), patch(
            "swell.analysis.core.io.filedialog.askopenfilenames",
            return_value=("/tmp/bad.txt",),
        ), patch.object(
            dummy,
            "_validate_selected_files",
            return_value=([], [("bad.txt", "unsupported extension")]),
        ), patch(
            "swell.analysis.core.io.messagebox.showwarning"
        ) as warn_mock:
            selected = dummy.browse_input_files()
        self.assertIsNone(selected)
        self.assertEqual(dummy._selected_import_files, [Path("/tmp/old.png")])
        self.assertEqual(dummy.get_input_source_hint(), "old")
        warn_mock.assert_called_once()

    def test_browse_input_folder_clears_selected_files(self):
        dummy = _DummyIO()
        dummy._selected_import_files = [Path("/tmp/a.png")]
        with patch("swell.analysis.core.io.resolve_existing_directory", return_value="."), patch(
            "swell.analysis.core.io.filedialog.askdirectory", return_value="/tmp/images"
        ):
            result = dummy.browse_input_folder()
        self.assertEqual(result, "/tmp/images")
        self.assertIsNone(dummy._selected_import_files)
        self.assertEqual(dummy.get_input_source_hint(), "/tmp/images")


if __name__ == "__main__":
    unittest.main()
