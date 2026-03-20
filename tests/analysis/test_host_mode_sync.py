import unittest

import numpy as np

from sdapp.analysis.core.analysis_workspace import AnalysisWorkspaceController
from sdapp.analysis.core.frame_source import EagerFrameSource
from sdapp.analysis.core.project_session import ProjectSessionService
from sdapp.analysis.core.seg_state import SegmentationState
from sdapp.analysis.core.session_state import SessionState
from sdapp.shared.contracts import load_contract_fixture, validate_sync_payload
from sdapp.shared.frame_source import EventScopedFrameSource


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

    def test_open_from_host_context_normalizes_event_local_saved_masks_into_scoped_frames(self):
        frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(11)]
        scoped_source = EagerFrameSource(
            raw_frames=frames,
            subtracted_frames=frames,
            visual_frames=frames,
            frame_names=[f"s{i}.tif" for i in range(11)],
            source_paths=["/tmp/scoped"] * 11,
        )
        event_local_masks = np.zeros((4, 64, 64), dtype=np.uint8)
        event_local_masks[1] = 1
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
                "masks_committed": event_local_masks,
            },
        }
        result = self.controller.open_from_host_event_context(context, frame_source=scoped_source)
        self.assertTrue(result["ok"])
        record = self.state.event_records["event_0001"]
        self.assertIn(3, record.analysis.masks_committed)
        self.assertTrue(bool(np.any(record.analysis.masks_committed[3])))

    def test_open_from_host_context_normalizes_singleton_channel_mask_dict_entries(self):
        frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(11)]
        scoped_source = EagerFrameSource(
            raw_frames=frames,
            subtracted_frames=frames,
            visual_frames=frames,
            frame_names=[f"s{i}.tif" for i in range(11)],
            source_paths=["/tmp/scoped"] * 11,
        )
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
                "masks_committed": {"103": np.ones((64, 64, 1), dtype=np.uint8)},
            },
        }
        result = self.controller.open_from_host_event_context(context, frame_source=scoped_source)
        self.assertTrue(result["ok"])
        record = self.state.event_records["event_0001"]
        self.assertIn(3, record.analysis.masks_committed)
        mask = record.analysis.masks_committed[3]
        self.assertEqual(mask.shape, (64, 64))
        self.assertTrue(bool(np.any(mask)))

    def test_open_from_host_context_unwraps_object_array_wrapped_dict_masks(self):
        frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(11)]
        scoped_source = EagerFrameSource(
            raw_frames=frames,
            subtracted_frames=frames,
            visual_frames=frames,
            frame_names=[f"s{i}.tif" for i in range(11)],
            source_paths=["/tmp/scoped"] * 11,
        )
        wrapped = np.array({"103": np.ones((64, 64), dtype=np.uint8)}, dtype=object)
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
                "masks_committed": wrapped,
            },
        }
        result = self.controller.open_from_host_event_context(context, frame_source=scoped_source)
        self.assertTrue(result["ok"])
        record = self.state.event_records["event_0001"]
        self.assertIn(3, record.analysis.masks_committed)
        self.assertTrue(bool(np.any(record.analysis.masks_committed[3])))

    def test_export_active_event_analysis_payload_prefers_raw_frame_shape_over_frame_source_metadata(self):
        frames = [np.zeros((2048, 3072), dtype=np.uint8) for _ in range(3)]

        class _BrokenShapeFrameSource(EagerFrameSource):
            @property
            def frame_shape(self) -> tuple[int, int]:
                return (3072, 3)

        broken_source = _BrokenShapeFrameSource(
            raw_frames=frames,
            subtracted_frames=frames,
            visual_frames=frames,
            frame_names=[f"b{i}.tif" for i in range(3)],
            source_paths=["/tmp/broken"] * 3,
        )
        self.controller.bind_frame_source(broken_source)
        self.state.active_event_id = "event_0001"
        self.state.event_records = self.service.coerce_event_records({"event_0001": {}}, 3)
        self.seg_state.masks_cache[1] = np.ones((2048, 3072), dtype=bool)

        payload = self.controller.export_active_event_analysis_payload()

        self.assertIsNotNone(payload)
        masks = np.asarray(payload["masks_committed"])
        self.assertEqual(masks.shape, (3, 2048, 3072))
        self.assertTrue(bool(np.any(masks[1])))

    def test_open_from_host_context_uses_scoped_get_raw_frame_shape_when_metadata_is_wrong(self):
        frames = [np.zeros((2048, 3072), dtype=np.uint8) for _ in range(11)]
        global_masks = np.zeros((11, 2048, 3072), dtype=np.uint8)
        global_masks[3] = 1

        class _BrokenShapeBase(EagerFrameSource):
            @property
            def frame_shape(self) -> tuple[int, int]:
                return (3072, 3)

        scoped_source = EventScopedFrameSource(
            _BrokenShapeBase(
                raw_frames=frames,
                subtracted_frames=frames,
                visual_frames=frames,
                frame_names=[f"s{i}.tif" for i in range(11)],
                source_paths=["/tmp/scoped"] * 11,
            ),
            0,
            10,
        )
        context = {
            "session_id": "session_abc",
            "stack_id": "stack_abc",
            "event": {
                "event_id": "event_0001",
                "label": "Event 1",
                "start_idx": 0,
                "end_idx": 10,
                "flags": {
                    "analysis_scope_start_idx": 0,
                    "analysis_scope_end_idx": 10,
                    "analysis_local_event_start_idx": 0,
                    "analysis_local_event_end_idx": 10,
                },
            },
            "analysis_state": {
                "masks_committed": global_masks,
            },
        }

        result = self.controller.open_from_host_event_context(context, frame_source=scoped_source)

        self.assertTrue(result["ok"])
        record = self.state.event_records["event_0001"]
        self.assertIn(3, record.analysis.masks_committed)
        self.assertEqual(record.analysis.masks_committed[3].shape, (2048, 3072))
        self.assertTrue(bool(np.any(record.analysis.masks_committed[3])))

    def test_build_host_sync_payload_uses_scoped_get_raw_frame_shape_when_metadata_is_wrong(self):
        frames = [np.zeros((2048, 3072), dtype=np.uint8) for _ in range(5)]

        class _BrokenShapeBase(EagerFrameSource):
            @property
            def frame_shape(self) -> tuple[int, int]:
                return (3072, 3)

        scoped_source = EventScopedFrameSource(
            _BrokenShapeBase(
                raw_frames=frames,
                subtracted_frames=frames,
                visual_frames=frames,
                frame_names=[f"s{i}.tif" for i in range(5)],
                source_paths=["/tmp/scoped"] * 5,
            ),
            0,
            4,
        )
        payload = load_contract_fixture("valid_handoff")
        self.controller.open_from_handoff_payload(
            payload,
            frame_source=scoped_source,
            sync_emitter=self.emitted.append,
        )
        self.seg_state.masks_cache[2] = np.ones((2048, 3072), dtype=bool)

        sync_payload = self.controller.build_host_sync_payload(ui_hints={"last_frame": 2})

        self.assertIsNotNone(sync_payload)
        analysis_payload = sync_payload["analysis"]
        self.assertEqual(analysis_payload["masks_committed"]["frame_count"], 5)
        self.assertEqual(analysis_payload["masks_committed"]["shape"], [2048, 3072])


if __name__ == "__main__":
    unittest.main()
