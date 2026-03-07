import unittest

import numpy as np

from app.app import SDSegmentationApp
from app.core.analysis_workspace import AnalysisWorkspaceController
from app.core.frame_source import EagerFrameSource
from app.core.project_session import ProjectSessionService
from app.core.project_workflow import apply_loaded_project_plan, ProjectLoadPlan
from app.core.seg_state import SegmentationState
from app.core.session_state import SessionState


class _DummySlider:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _DummyToolMode:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _DummyLabel:
    def configure(self, **_kwargs):
        return None


class ProjectWorkflowFrameSourceTests(unittest.TestCase):
    def test_apply_loaded_project_plan_binds_frame_source_and_opens_event(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.project_session_service = ProjectSessionService()
        app.session_state = SessionState()
        app.seg_state = SegmentationState()
        app.analysis_workspace = AnalysisWorkspaceController(
            session_service=app.project_session_service,
            session_state=app.session_state,
            seg_state=app.seg_state,
        )
        app.app_context = type("Ctx", (), {"frame_source": None})()
        app.frame_names = []
        app.scale_px_per_mm = None
        app.roi_points = []
        app.roi_mask = None
        app._propagation_committed_snapshot = None
        app.tool_mode = _DummyToolMode()
        app.slider = _DummySlider()
        app.lbl_status = _DummyLabel()
        app._set_spinbox_value = lambda *_args, **_kwargs: None
        app._collect_nonempty_final_mask_frames = lambda: set()
        app._set_propagated_frames = lambda *_args, **_kwargs: None
        app.update_display = lambda: None
        app.log_success = lambda *_args, **_kwargs: None
        app.log_warn = lambda *_args, **_kwargs: None
        app.project_dirty = True
        app._apply_loaded_stack = lambda frames_raw, frames_sub, frames_sub_viz, frame_names, source_paths=None: (
            setattr(app, "frames_raw", frames_raw),
            setattr(app, "frames_sub", frames_sub),
            setattr(app, "frames_sub_viz", frames_sub_viz),
            setattr(app, "frame_names", list(frame_names)),
            setattr(app, "_current_image_source_paths", list(source_paths or [])),
        )

        frames = [np.zeros((3, 3), dtype=np.uint8) for _ in range(2)]
        records = app.project_session_service.coerce_event_records({}, 2)
        records["sd_event_001"].analysis.masks_committed[1] = np.ones((3, 3), dtype=bool)
        plan = ProjectLoadPlan(
            project_path="/tmp/test.sdproj",
            state={"created_at": "2026-01-01T00:00:00Z"},
            ui_state={"active_event_id": "sd_event_001", "active_tool": "select", "last_frame": 1},
            global_state={"baseline_frame_count": 30},
            image_paths=["/tmp/frame1.tif"],
            frame_names=["f1", "f2"],
            frames_raw=frames,
            frames_sub=frames,
            frames_sub_viz=frames,
            frame_source=EagerFrameSource(
                raw_frames=frames,
                subtracted_frames=frames,
                visual_frames=frames,
                frame_names=["f1", "f2"],
                source_paths=["/tmp/frame1.tif"],
            ),
            event_records=records,
            active_event_id="sd_event_001",
            roi_points=[],
            roi_mask=None,
            fingerprint_mismatches=[],
        )
        apply_loaded_project_plan(app, plan)
        self.assertIsNotNone(app.frame_source)
        self.assertEqual(app.app_context.frame_source, app.frame_source)
        self.assertIn(1, app.seg_state.masks_cache)
        self.assertEqual(app.active_event_id, "sd_event_001")


if __name__ == "__main__":
    unittest.main()
