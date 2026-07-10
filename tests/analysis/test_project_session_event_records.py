import unittest
from types import SimpleNamespace

import numpy as np

from swell.analysis.core.project_session import EventRecord, ProjectSessionService
from swell.analysis.core.seg_state import SegmentationState


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

    def test_persistent_regions_sync_and_load_with_event(self):
        svc = ProjectSessionService()
        records = svc.coerce_event_records({}, 5)
        seg = SegmentationState()
        seg.add_persistent_region(
            {
                "id": "region_a",
                "mode": "exclude",
                "frame_start": 1,
                "frame_end": 3,
                "polygon": [[1, 1], [4, 1], [4, 4]],
            }
        )

        svc.sync_workspace_into_event(frame_count=5, event_id="sd_event_001", seg_state=seg, event_records=records)
        loaded = SegmentationState()
        svc.load_event_into_workspace(event_id="sd_event_001", event_records=records, seg_state=loaded)

        self.assertEqual(len(loaded.persistent_regions), 1)
        self.assertEqual(loaded.persistent_regions[0]["id"], "region_a")
        self.assertEqual(loaded.persistent_regions[0]["mode"], "exclude")


    def test_ground_truth_frames_sync_and_load_with_event(self):
        svc = ProjectSessionService()
        records = svc.coerce_event_records({}, 5)
        seg = SegmentationState()
        seg.set_mask(2, np.ones((3, 3), dtype=bool))
        seg.set_ground_truth(2, True)
        # A ground-truth flag with no surviving mask should not be restored.
        seg.ground_truth_frames.add(4)

        svc.sync_workspace_into_event(frame_count=5, event_id="sd_event_001", seg_state=seg, event_records=records)
        self.assertEqual(records["sd_event_001"].analysis.ground_truth_frames, {2, 4})

        loaded = SegmentationState()
        svc.load_event_into_workspace(event_id="sd_event_001", event_records=records, seg_state=loaded)
        self.assertEqual(loaded.ground_truth_frames, {2})
        self.assertIn(2, loaded.get_prompt_anchor_frames())

    def test_coerce_event_record_accepts_attribute_based_legacy_payload(self):
        svc = ProjectSessionService()
        raw = {
            "metadata": SimpleNamespace(event_id="legacy", label="Legacy", start_idx=1, end_idx=3),
            "analysis": SimpleNamespace(points={}, boxes={}, persistent_regions=[], paint_layers={}, masks_committed={}),
        }

        record = svc.coerce_event_records({"legacy": raw}, 5)["legacy"]

        self.assertEqual(record.metadata.label, "Legacy")
        self.assertEqual(record.metadata.start_idx, 1)


if __name__ == "__main__":
    unittest.main()
