import unittest

import numpy as np

from app.core.seg_state import SegmentationState


class SegStatePromptSerializationTests(unittest.TestCase):
    def test_points_and_paint_roundtrip(self):
        st = SegmentationState()
        st.set_points(2, [{"x": 1, "y": 2, "label": 1}])
        plus = np.zeros((4, 4), dtype=bool)
        minus = np.zeros((4, 4), dtype=bool)
        plus[1, 1] = True
        minus[2, 2] = True
        st.set_paint_layer(2, plus, minus)

        payload = st.to_prompts_json("sd_event_001")
        st2 = SegmentationState()
        st2.load_prompts_json(payload, base_shape=(4, 4))
        self.assertIn(2, st2.points)
        self.assertTrue(st2.paint_layers[2]["plus"][1, 1])
        self.assertTrue(st2.paint_layers[2]["minus"][2, 2])


if __name__ == "__main__":
    unittest.main()
