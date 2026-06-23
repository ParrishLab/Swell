import unittest

from swell.analysis.core.overlay_state import frame_spans, largest_contiguous_span, compute_propagated_state


class OverlayStateHelperTests(unittest.TestCase):
    def test_frame_spans(self):
        self.assertEqual(frame_spans({1, 2, 4, 5, 9}), [(1, 2), (4, 5), (9, 9)])

    def test_largest_contiguous_span(self):
        self.assertEqual(largest_contiguous_span({10, 11, 12, 3, 4}), (10, 12))

    def test_compute_propagated_state_merges_history(self):
        st = compute_propagated_state(indices={6, 7}, previous_history_indices={3, 4, 5}, frame_count=20)
        self.assertEqual(st.largest_propagated_span, (3, 7))
        self.assertEqual(st.propagated_frame_indices, {3, 4, 5, 6, 7})

    def test_compute_propagated_state_no_dirty_indices_out_of_range(self):
        st = compute_propagated_state(indices={-1, 0, 1, 999}, previous_history_indices=set(), frame_count=5)
        self.assertEqual(st.propagated_history_indices, {0, 1})


if __name__ == "__main__":
    unittest.main()
