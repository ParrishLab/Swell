import unittest

from app.app import SDSegmentationApp


class BrowseSplitButtonTests(unittest.TestCase):
    def _make_app(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app._browse_mode = "folder"
        app.calls = []
        app.browse_input_folder = lambda: app.calls.append(("folder", None))
        app.browse_input_files = lambda: app.calls.append(("files", None))
        return app

    def test_default_mode_is_folder(self):
        app = self._make_app()
        self.assertEqual(app._browse_mode, "folder")

    def test_dropdown_folder_switches_mode_and_opens_folder(self):
        app = self._make_app()
        app._browse_mode = "files"
        app.on_browse_select_folder()
        self.assertEqual(app._browse_mode, "folder")
        self.assertEqual(app.calls, [("folder", None)])

    def test_dropdown_files_switches_mode_and_opens_files(self):
        app = self._make_app()
        app._browse_mode = "folder"
        app.on_browse_select_files()
        self.assertEqual(app._browse_mode, "files")
        self.assertEqual(app.calls, [("files", None)])


if __name__ == "__main__":
    unittest.main()
