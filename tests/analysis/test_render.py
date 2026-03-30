import unittest

from sdapp.analysis.core.render import RenderActions


class _CanvasStub:
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height


class _RenderHarness(RenderActions):
    pass


class RenderActionsTests(unittest.TestCase):
    def test_display_transform_matches_non_upscaled_rendering(self):
        harness = _RenderHarness()
        canvas = _CanvasStub(width=400, height=300)

        ratio, offset_x, offset_y = harness._get_display_transform(canvas, img_w=100, img_h=50)

        self.assertEqual(ratio, 1.0)
        self.assertEqual(offset_x, 150)
        self.assertEqual(offset_y, 125)


if __name__ == "__main__":
    unittest.main()
