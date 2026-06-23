import unittest

import numpy as np

from swell.analysis.core.seg_state import SegmentationState


class SegStatePromptSerializationTests(unittest.TestCase):
    def test_points_and_paint_roundtrip(self):
        st = SegmentationState()
        st.set_points(2, [{"x": 1, "y": 2, "label": 1}])
        st.set_box(2, [0, 1, 3, 4])
        plus = np.zeros((4, 4), dtype=bool)
        minus = np.zeros((4, 4), dtype=bool)
        plus[1, 1] = True
        minus[2, 2] = True
        st.set_paint_layer(2, plus, minus)

        payload = st.to_prompts_json("sd_event_001")
        st2 = SegmentationState()
        st2.load_prompts_json(payload, base_shape=(4, 4))
        self.assertIn(2, st2.points)
        self.assertEqual(st2.boxes[2], [0.0, 1.0, 3.0, 4.0])
        self.assertTrue(st2.paint_layers[2]["plus"][1, 1])
        self.assertTrue(st2.paint_layers[2]["minus"][2, 2])

    def test_ground_truth_frames_roundtrip(self):
        st = SegmentationState()
        st.set_ground_truth(2, True)
        st.set_ground_truth(5, True)
        payload = st.to_prompts_json("sd_event_001")
        self.assertEqual(payload["ground_truth_frames"], [2, 5])
        st2 = SegmentationState()
        st2.load_prompts_json(payload, base_shape=(4, 4))
        self.assertEqual(st2.ground_truth_frames, {2, 5})

    def test_missing_ground_truth_frames_defaults_empty(self):
        st = SegmentationState()
        st.set_ground_truth(1, True)
        st.load_prompts_json({"frames": {}}, base_shape=(4, 4))
        self.assertEqual(st.ground_truth_frames, set())

    def test_persistent_regions_roundtrip(self):
        st = SegmentationState()
        st.add_persistent_region(
            {
                "id": "region_a",
                "mode": "exclude",
                "enabled": True,
                "visible": False,
                "frame_start": 2,
                "frame_end": 5,
                "polygon": [[1, 1], [4, 1], [4, 4]],
            }
        )

        payload = st.to_prompts_json("sd_event_001")
        st2 = SegmentationState()
        st2.load_prompts_json(payload, base_shape=(8, 8))

        self.assertEqual(len(st2.persistent_regions), 1)
        region = st2.persistent_regions[0]
        self.assertEqual(region["id"], "region_a")
        self.assertEqual(region["mode"], "exclude")
        self.assertFalse(region["visible"])
        self.assertEqual(region["frame_start"], 2)
        self.assertEqual(region["frame_end"], 5)


if __name__ == "__main__":
    unittest.main()
