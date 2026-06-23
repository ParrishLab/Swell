import unittest

from swell.analysis.core.mask_import import extract_frame_number, guess_mask_mapping


class ExternalMaskAlignmentTests(unittest.TestCase):
    def test_extract_frame_number(self):
        self.assertEqual(extract_frame_number("mask_042.tif"), 42)
        self.assertIsNone(extract_frame_number("mask_no_index.tif"))

    def test_stack_exact_mapping(self):
        guess = guess_mask_mapping(["a.tif", "b.tif"], frame_count=2, event_ranges={})
        self.assertEqual(guess["strategy"], "stack_exact")
        self.assertEqual(guess["offset"], 0)

    def test_event_span_mapping(self):
        guess = guess_mask_mapping(
            ["a.tif", "b.tif", "c.tif"],
            frame_count=10,
            event_ranges={"sd_event_002": (4, 6)},
        )
        self.assertEqual(guess["strategy"], "event_span_exact")
        self.assertEqual(guess["event_id"], "sd_event_002")
        self.assertEqual(guess["offset"], 4)

    def test_filename_mapping(self):
        guess = guess_mask_mapping(
            ["mask_007.tif", "mask_008.tif"],
            frame_count=20,
            event_ranges={},
        )
        self.assertEqual(guess["strategy"], "filename_index")
        self.assertEqual(guess["offset"], 6)

    def test_manual_required(self):
        guess = guess_mask_mapping(["foo.tif", "bar.tif"], frame_count=100, event_ranges={})
        self.assertEqual(guess["strategy"], "manual_required")
        self.assertIsNone(guess["offset"])


if __name__ == "__main__":
    unittest.main()
