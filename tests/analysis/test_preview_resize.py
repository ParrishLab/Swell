import unittest

from sdapp.analysis.core.preview_resize import do_resize_preview, start_resize_preview, stop_resize_preview


class _Event:
    def __init__(self, x_root=0, y_root=0):
        self.x_root = x_root
        self.y_root = y_root


class _PreviewFrame:
    def __init__(self):
        self.width = 200
        self.height = 200
        self.configured = []
        self.updated = 0

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height

    def configure(self, **kwargs):
        self.configured.append(kwargs)
        self.width = int(kwargs.get("width", self.width))
        self.height = int(kwargs.get("height", self.height))

    def update_idletasks(self):
        self.updated += 1


class _App:
    def __init__(self):
        self.preview_frame = _PreviewFrame()
        self.update_preview_calls = 0

    def update_display(self, update_preview=False):
        if update_preview:
            self.update_preview_calls += 1


class PreviewResizeTests(unittest.TestCase):
    def test_resize_round_trip(self):
        app = _App()
        start_resize_preview(app, _Event(x_root=100, y_root=100))
        do_resize_preview(app, _Event(x_root=70, y_root=140))
        stop_resize_preview(app, _Event())
        self.assertGreater(app.preview_frame.width, 200)
        self.assertGreaterEqual(app.update_preview_calls, 2)


if __name__ == "__main__":
    unittest.main()
