import unittest

import numpy as np

from sdapp.analysis.core.project_session import EventRecord, ProjectSessionService
from sdapp.analysis.core.seg_state import SegmentationState


class ProjectSessionEventRecordTests(unittest.TestCase):
    def test_ensure_event_record_defaults(self):
        svc = ProjectSessionService()
        records = {}
        record = svc.ensure_event_record("sd_event_001", 8, records)
        self.assertIsInstance(record, EventRecord)
        self.assertEqual(record.metadata.start_idx, 0)
        self.assertEqual(record.metadata.end_idx, 7)

    def test_update_event_metadata_only_changes_metadata(self):
        svc = ProjectSessionService()
        records = svc.coerce_event_records({}, 6)
        svc.update_event_metadata("sd_event_001", records, label="Wave A", start_idx=2, end_idx=4)
        record = records["sd_event_001"]
        self.assertEqual(record.metadata.label, "Wave A")
        self.assertEqual(record.metadata.start_idx, 2)
        self.assertEqual(record.metadata.end_idx, 4)
        self.assertEqual(record.analysis.masks_committed, {})

    def test_sync_workspace_into_target_event_only(self):
        svc = ProjectSessionService()
        records = svc.coerce_event_records({"sd_event_002": {}}, 5)
        seg = SegmentationState()
        seg.masks_cache[1] = np.ones((3, 3), dtype=bool)
        svc.sync_workspace_into_event(frame_count=5, event_id="sd_event_001", seg_state=seg, event_records=records)
        self.assertIn("sd_event_001", records)
        self.assertIn("sd_event_002", records)
        self.assertIn(1, records["sd_event_001"].analysis.masks_committed)
        self.assertEqual(records["sd_event_002"].analysis.masks_committed, {})


if __name__ == "__main__":
    unittest.main()
