import unittest

from app.app import SDSegmentationApp


class SessionStateProxyTests(unittest.TestCase):
    def test_lazy_session_state_for_new_instances(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app._analysis_range_auto_follow = False
        app._export_range_auto_follow = False
        app.active_event_id = "ev_1"
        app.event_states = {"ev_1": {}}
        self.assertFalse(app._analysis_range_auto_follow)
        self.assertFalse(app._export_range_auto_follow)
        self.assertEqual(app.active_event_id, "ev_1")
        self.assertIn("ev_1", app.event_states)


if __name__ == "__main__":
    unittest.main()
