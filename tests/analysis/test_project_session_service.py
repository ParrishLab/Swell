import unittest

import numpy as np

from swell.analysis.core.project_session import ProjectSessionService, SessionSnapshot
from swell.analysis.core.seg_state import SegmentationState


class ProjectSessionServiceTests(unittest.TestCase):
    def test_build_payload_multi_event(self):
        svc = ProjectSessionService()
        roi = np.zeros((4, 4), dtype=bool)
        roi[1:3, 1:3] = True
        event_records = svc.coerce_event_records(
            {
            "sd_event_001": {
                "label": "E1",
                "points": {},
                "paint_layers": {},
                "masks_committed": {1: np.ones((4, 4), dtype=bool)},
                "masks_draft": None,
                "propagation_completed": True,
                "analysis_output_dir": None,
            },
            "sd_event_002": {
                "label": "E2",
                "points": {},
                "paint_layers": {},
                "masks_committed": {2: np.ones((4, 4), dtype=bool)},
                "masks_draft": {3: np.ones((4, 4), dtype=bool)},
                "propagation_completed": False,
                "analysis_output_dir": None,
            },
            },
            5,
        )
        snap = SessionSnapshot(
            frame_count=5,
            frame_shape=(4, 4),
            current_frame_idx=0,
            active_event_id="sd_event_001",
            tool_mode="select",
            display_ratio=1.0,
            img_offset_x=0,
            img_offset_y=0,
            analysis_start=1,
            analysis_end=5,
            prop_start=1,
            prop_end=5,
            export_start=1,
            export_end=5,
            baseline_frame_count=10,
            scale_px_per_mm=2.0,
            scale_points=[(1.0, 1.0), (5.0, 1.0)],
            scale_axis_lock=False,
            scale_image_path="/tmp/scale.png",
            roi_points=[],
            roi_polygons=[],
            roi_mask=roi,
            created_at="2026-01-01T00:00:00Z",
            current_image_source_paths=[],
            event_records=event_records,
        )
        state, _images, roi_data, payloads = svc.build_payload(snap)
        self.assertEqual(len(state["events"]), 2)
        self.assertIn("sd_event_001", payloads)
        self.assertIn("sd_event_002", payloads)
        self.assertEqual(state["global"]["scale_points"], [(1.0, 1.0), (5.0, 1.0)])
        self.assertIs(state["global"]["scale_axis_lock"], False)
        self.assertEqual(state["global"]["scale_image_path"], "/tmp/scale.png")
        self.assertIsNotNone(roi_data["roi_mask_rle"])
        self.assertIn("masks_draft", payloads["sd_event_002"])

    def test_sync_and_load_event_state(self):
        svc = ProjectSessionService()
        seg = SegmentationState()
        seg.points[0] = [{"x": 1.0, "y": 2.0, "label": 1}]
        seg.masks_cache[0] = np.ones((3, 3), dtype=bool)
        records = svc.coerce_event_records({}, 4)
        svc.sync_workspace_into_event(
            frame_count=4,
            event_id="sd_event_001",
            seg_state=seg,
            event_records=records,
        )
        self.assertIn("sd_event_001", records)
        seg2 = SegmentationState()
        svc.load_event_into_workspace(event_id="sd_event_001", event_records=records, seg_state=seg2)
        self.assertIn(0, seg2.points)
        self.assertIn(0, seg2.masks_cache)

    def test_propagation_transition_restore(self):
        svc = ProjectSessionService()
        current = {0: np.ones((2, 2), dtype=bool)}
        snapshot = {0: np.zeros((2, 2), dtype=bool)}
        transition = svc.on_propagation_status(
            status="failed",
            prop_start=0,
            prop_end=1,
            active_event_id="sd_event_001",
            event_records={},
            current_masks=current,
            committed_snapshot=snapshot,
        )
        self.assertIsNotNone(transition.restored_masks)
        self.assertFalse(bool(transition.event_record.metadata.propagation_completed))

    def test_masks_dict_to_array_accepts_singleton_channel_masks(self):
        svc = ProjectSessionService()
        arr = svc.masks_dict_to_array(
            mask_dict={1: np.ones((3, 3, 1), dtype=bool)},
            frame_count=4,
            shape_hw=(3, 3),
        )
        self.assertEqual(arr.shape, (4, 3, 3))
        self.assertEqual(int(arr[1].sum()), 9)


if __name__ == "__main__":
    unittest.main()
