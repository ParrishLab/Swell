import unittest

import numpy as np

from app.core.frame_source import EagerFrameSource


class FrameSourceTests(unittest.TestCase):
    def test_eager_frame_source_exposes_shapes_and_frames(self):
        raw = [np.zeros((3, 4), dtype=np.uint8), np.ones((3, 4), dtype=np.uint8)]
        sub = [np.full((3, 4), 2, dtype=np.uint8), np.full((3, 4), 3, dtype=np.uint8)]
        viz = [np.full((3, 4), 4, dtype=np.uint8), np.full((3, 4), 5, dtype=np.uint8)]
        src = EagerFrameSource(
            raw_frames=raw,
            subtracted_frames=sub,
            visual_frames=viz,
            frame_names=["a", "b"],
            source_paths=["/tmp/a.tif"],
        )
        self.assertEqual(src.frame_count, 2)
        self.assertEqual(src.frame_shape, (3, 4))
        self.assertEqual(list(src.frame_names), ["a", "b"])
        self.assertEqual(list(src.source_paths), ["/tmp/a.tif"])
        self.assertTrue(np.array_equal(src.get_raw_frame(1), raw[1]))
        self.assertTrue(np.array_equal(src.get_subtracted_frame(0), sub[0]))
        self.assertTrue(np.array_equal(src.get_visual_frame(1), viz[1]))

    def test_eager_frame_source_validates_index(self):
        src = EagerFrameSource(raw_frames=[np.zeros((2, 2), dtype=np.uint8)])
        with self.assertRaises(IndexError):
            src.get_raw_frame(2)


if __name__ == "__main__":
    unittest.main()
