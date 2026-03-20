import unittest

import numpy as np

from sdapp.analysis.core.analysis_workspace import AnalysisWorkspaceController, WorkspaceUiState
from sdapp.analysis.core.frame_source import EagerFrameSource
from sdapp.analysis.core.project_session import ProjectSessionService
from sdapp.analysis.core.seg_state import SegmentationState
from sdapp.analysis.core.session_state import SessionState
from sdapp.shared.contracts import load_contract_fixture
from sdapp.shared.frame_source import EventScopedFrameSource


class AnalysisWorkspaceControllerTests(unittest.TestCase):
    def setUp(self):
        self.service = ProjectSessionService()
        self.state = SessionState()
        self.seg_state = SegmentationState()
        self.opened_events: list[str] = []
        self.controller = AnalysisWorkspaceController(
            session_service=self.service,
            session_state=self.state,
            seg_state=self.seg_state,
            on_event_opened=lambda event_id: self.opened_events.append(str(event_id)),
        )
        frames = [np.zeros((4, 4), dtype=np.uint8) for _ in range(5)]
        self.controller.bind_frame_source(
            EagerFrameSource(
                raw_frames=frames,
                subtracted_frames=frames,
                visual_frames=frames,
                frame_names=[f"f{i}" for i in range(5)],
                source_paths=["/tmp/stack"],
            )
        )

    def test_reset_and_open_event(self):
        self.controller.reset_workspace_for_new_stack()
        self.assertIn("sd_event_001", self.state.event_records)
        self.seg_state.masks_cache[1] = np.ones((4, 4), dtype=bool)
        self.controller.sync_active_event()
        self.controller.open_event("sd_event_001")
        self.assertIn(1, self.seg_state.masks_cache)
        self.assertIn("sd_event_001", self.opened_events)

    def test_build_session_snapshot_uses_frame_source(self):
        self.controller.reset_workspace_for_new_stack()
        snap = self.controller.build_session_snapshot(
            WorkspaceUiState(
                current_frame_idx=2,
                tool_mode="brush",
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
                scale_px_per_mm=None,
                roi_points=[],
                roi_mask=None,
                created_at="2026-01-01T00:00:00Z",
            )
        )
        self.assertEqual(snap.frame_count, 5)
        self.assertEqual(snap.frame_shape, (4, 4))
        self.assertEqual(snap.current_image_source_paths, ["/tmp/stack"])

    def test_propagation_transition_preserves_draft(self):
        self.controller.reset_workspace_for_new_stack()
        self.seg_state.masks_cache[0] = np.ones((4, 4), dtype=bool)
        transition = self.controller.on_propagation_status("failed", 0, 2, committed_snapshot={0: np.zeros((4, 4), dtype=bool)})
        self.assertFalse(transition.event_record.metadata.propagation_completed)
        self.assertIsNotNone(transition.restored_masks)

    def test_open_from_handoff_payload_validates(self):
        payload = load_contract_fixture("valid_handoff")
        result = self.controller.open_from_handoff_payload(payload)
        self.assertTrue(result["ok"])
        self.assertIn("normalized", result)

    def test_build_session_snapshot_uses_scoped_raw_frame_shape_and_invalidates_cache_on_rebind(self):
        first_frames = [np.zeros((2048, 3072), dtype=np.uint8) for _ in range(3)]
        second_frames = [np.zeros((32, 48), dtype=np.uint8) for _ in range(2)]

        class _BrokenShapeBase(EagerFrameSource):
            @property
            def frame_shape(self) -> tuple[int, int]:
                return (3072, 3)

        first_source = EventScopedFrameSource(
            _BrokenShapeBase(
                raw_frames=first_frames,
                subtracted_frames=first_frames,
                visual_frames=first_frames,
                frame_names=["a", "b", "c"],
                source_paths=["/tmp/one"],
            ),
            0,
            2,
        )
        second_source = EventScopedFrameSource(
            EagerFrameSource(
                raw_frames=second_frames,
                subtracted_frames=second_frames,
                visual_frames=second_frames,
                frame_names=["d", "e"],
                source_paths=["/tmp/two"],
            ),
            0,
            1,
        )

        self.controller.bind_frame_source(first_source)
        snap_one = self.controller.build_session_snapshot(
            WorkspaceUiState(
                current_frame_idx=1,
                tool_mode="brush",
                display_ratio=1.0,
                img_offset_x=0,
                img_offset_y=0,
                analysis_start=1,
                analysis_end=3,
                prop_start=1,
                prop_end=3,
                export_start=1,
                export_end=3,
                baseline_frame_count=10,
                scale_px_per_mm=None,
                roi_points=[],
                roi_mask=None,
                created_at="2026-01-01T00:00:00Z",
            )
        )

        self.controller.bind_frame_source(second_source)
        snap_two = self.controller.build_session_snapshot(
            WorkspaceUiState(
                current_frame_idx=0,
                tool_mode="brush",
                display_ratio=1.0,
                img_offset_x=0,
                img_offset_y=0,
                analysis_start=1,
                analysis_end=2,
                prop_start=1,
                prop_end=2,
                export_start=1,
                export_end=2,
                baseline_frame_count=10,
                scale_px_per_mm=None,
                roi_points=[],
                roi_mask=None,
                created_at="2026-01-01T00:00:00Z",
            )
        )

        self.assertEqual(snap_one.frame_shape, (2048, 3072))
        self.assertEqual(snap_one.frame_count, 3)
        self.assertEqual(snap_two.frame_shape, (32, 48))
        self.assertEqual(snap_two.frame_count, 2)


if __name__ == "__main__":
    unittest.main()
