import unittest
from pathlib import Path
from unittest.mock import patch

from swell.analysis.app import SwellAnalysisApp


class ModelBrowseReloadTests(unittest.TestCase):
    @patch("swell.analysis.app.filedialog.askopenfilename")
    def test_no_reload_when_model_path_unchanged(self, ask_mock):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app.root = object()
        app.app_root = "/tmp"
        state = {"token": "/tmp/models/a.pt"}
        app.get_model_token = lambda: state["token"]
        app.set_model_token = lambda value: state.__setitem__("token", str(value))
        ran = {"count": 0}
        app.start_model_initialization = lambda **_kwargs: ran.__setitem__("count", ran["count"] + 1)
        app.log_info = lambda *_args, **_kwargs: None
        ask_mock.return_value = "/tmp/models/a.pt"

        app.on_browse_model()
        self.assertEqual(ran["count"], 0)

    @patch("swell.analysis.app.filedialog.askopenfilename")
    def test_reload_when_model_path_changes(self, ask_mock):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app.root = object()
        app.app_root = "/tmp"
        state = {"token": "/tmp/models/a.pt"}
        app.get_model_token = lambda: state["token"]
        app.set_model_token = lambda value: state.__setitem__("token", str(value))
        ran = {"count": 0}
        app.start_model_initialization = lambda **_kwargs: ran.__setitem__("count", ran["count"] + 1)
        app.log_info = lambda *_args, **_kwargs: None
        ask_mock.return_value = "/tmp/models/b.pt"

        app.on_browse_model()
        self.assertEqual(ran["count"], 1)
        self.assertEqual(Path(state["token"]).resolve(), Path("/tmp/models/b.pt").resolve())


if __name__ == "__main__":
    unittest.main()
