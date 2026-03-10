import unittest
from pathlib import Path
from unittest.mock import patch

from sdapp.analysis.app import SDSegmentationApp


class _EntryStub:
    def __init__(self, value):
        self.value = str(value)

    def get(self):
        return self.value

    def delete(self, _start, _end):
        self.value = ""

    def insert(self, _index, text):
        self.value = str(text)


class ModelBrowseReloadTests(unittest.TestCase):
    @patch("sdapp.analysis.app.filedialog.askopenfilename")
    def test_no_reload_when_model_path_unchanged(self, ask_mock):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.root = object()
        app.app_root = "/tmp"
        app.entry_model = _EntryStub("/tmp/models/a.pt")
        ran = {"count": 0}
        app._run_thread = lambda _fn: ran.__setitem__("count", ran["count"] + 1)
        app._init_sam2_background = lambda: None
        app.log_info = lambda *_args, **_kwargs: None
        ask_mock.return_value = "/tmp/models/a.pt"

        app.on_browse_model()
        self.assertEqual(ran["count"], 0)

    @patch("sdapp.analysis.app.filedialog.askopenfilename")
    def test_reload_when_model_path_changes(self, ask_mock):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.root = object()
        app.app_root = "/tmp"
        app.entry_model = _EntryStub("/tmp/models/a.pt")
        ran = {"count": 0}
        app._run_thread = lambda _fn: ran.__setitem__("count", ran["count"] + 1)
        app._init_sam2_background = lambda: None
        app.log_info = lambda *_args, **_kwargs: None
        ask_mock.return_value = "/tmp/models/b.pt"

        app.on_browse_model()
        self.assertEqual(ran["count"], 1)
        self.assertEqual(Path(app.entry_model.get()).resolve(), Path("/tmp/models/b.pt").resolve())


if __name__ == "__main__":
    unittest.main()
