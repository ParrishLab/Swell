import unittest

import numpy as np

from sdapp.analysis.core.analysis_workspace import AnalysisWorkspaceController
from sdapp.analysis.core.frame_source import EagerFrameSource
from sdapp.analysis.core.project_session import ProjectSessionService
from sdapp.analysis.core.seg_state import SegmentationState
from sdapp.analysis.core.session_state import SessionState
from sdapp.shared.contracts import load_contract_fixture, validate_sync_payload


class HostModeSyncTests(unittest.TestCase):
    def setUp(self):
        self.service = ProjectSessionService()
        self.state = SessionState()
        self.seg_state = SegmentationState()
        self.emitted = []
        self.controller = AnalysisWorkspaceController(
            session_service=self.service,
            session_state=self.state,
            seg_state=self.seg_state,
        )
        frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(12)]
        self.frame_source = EagerFrameSource(
            raw_frames=frames,
            subtracted_frames=frames,
            visual_frames=frames,
            frame_names=[f"f{i}.tif" for i in range(12)],
            source_paths=["/tmp/stack"] * 12,
        )

    def test_open_from_handoff_binds_host_event_context(self):
        payload = load_contract_fixture("valid_handoff")
        payload["event"]["flags"] = {
            "analysis_scope_start_idx": 0,
            "analysis_scope_end_idx": 5,
            "analysis_local_event_start_idx": 2,
            "analysis_local_event_end_idx": 5,
            "baseline_pre_frames": 2,
        }
        result = self.controller.open_from_handoff_payload(
            payload,
            frame_source=self.frame_source,
            sync_emitter=self.emitted.append,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(self.state.active_event_id, "event_0001")
        record = self.state.event_records["event_0001"]
        self.assertEqual(record.metadata.start_idx, 2)
        self.assertEqual(record.metadata.end_idx, 5)
        self.assertEqual(record.metadata.label, "Event 1")

    def test_emit_host_sync_on_bound_context(self):
        payload = load_contract_fixture("valid_handoff")
        self.controller.open_from_handoff_payload(
            payload,
            frame_source=self.frame_source,
            sync_emitter=self.emitted.append,
        )
        self.seg_state.masks_cache[3] = np.ones((64, 64), dtype=bool)

        sync_payload = self.controller.emit_host_sync(ui_hints={"last_frame": 3, "active_tool": "select"})
        self.assertIsNotNone(sync_payload)
        self.assertEqual(sync_payload["event_id"], "event_0001")
        self.assertEqual(len(self.emitted), 1)

        validation = validate_sync_payload(
            sync_payload,
            {
                "session_id": payload["session"]["session_id"],
                "stack_id": payload["stack"]["stack_id"],
                "frame_shape": payload["stack"]["frame_shape"],
                "event_ids": ["event_0001"],
            },
        )
        self.assertTrue(validation["ok"])

    def test_open_from_host_context_normalizes_global_saved_indices_to_local_scope(self):
        frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(11)]
        scoped_source = EagerFrameSource(
            raw_frames=frames,
            subtracted_frames=frames,
            visual_frames=frames,
            frame_names=[f"s{i}.tif" for i in range(11)],
            source_paths=["/tmp/scoped"] * 11,
        )
        global_masks = np.zeros((200, 64, 64), dtype=np.uint8)
        global_masks[103] = 1
        context = {
            "session_id": "session_abc",
            "stack_id": "stack_abc",
            "event": {
                "event_id": "event_0001",
                "label": "Event 1",
                "start_idx": 102,
                "end_idx": 105,
                "flags": {
                    "analysis_scope_start_idx": 100,
                    "analysis_scope_end_idx": 110,
                    "analysis_local_event_start_idx": 2,
                    "analysis_local_event_end_idx": 5,
                },
            },
            "analysis_state": {
                "prompts": {
                    "event_id": "event_0001",
                    "frames": {
                        "103": {"points": [{"x": 12.0, "y": 8.0, "label": 1}]},
                    },
                },
                "masks_committed": global_masks,
            },
        }
        result = self.controller.open_from_host_event_context(context, frame_source=scoped_source)
        self.assertTrue(result["ok"])
        record = self.state.event_records["event_0001"]
        self.assertIn(3, record.analysis.points)
        self.assertIn(3, record.analysis.masks_committed)
        self.assertTrue(bool(np.any(record.analysis.masks_committed[3])))


if __name__ == "__main__":
    unittest.main()
