import unittest
from unittest.mock import patch

import numpy as np

from sdapp.analysis.core import mask_import_workflow


class _DialogStub:
    def __init__(self, paths, masks, offset):
        self._paths = paths
        self._masks = masks
        self._offset = offset

    def choose_paths(self, _root):
        return list(self._paths)

    def load_external_mask_images(self, _paths):
        return list(self._masks)

    def ask_alignment(self, **_kwargs):
        return self._offset


class _SessionStub:
    def copy_masks_dict(self, m):
        return dict(m)

    def ensure_event_record(self, event_id, frame_count, event_records):
        if event_id not in event_records:
            event_records[event_id] = type(
                "Record",
                (),
                {
                    "metadata": type(
                        "Meta",
                        (),
                        {
                            "event_id": event_id,
                            "start_idx": 0,
                            "end_idx": max(0, frame_count - 1),
                            "propagation_completed": True,
                        },
                    )(),
                    "analysis": type(
                        "Analysis",
                        (),
                        {"masks_committed": {}, "masks_draft": None, "use_draft": False},
                    )(),
                },
            )()
        return event_records[event_id]

    def event_mask_bounds(self, committed, _frame_count):
        keys = sorted(committed.keys())
        return (keys[0], keys[-1]) if keys else (0, 0)


class MaskImportWorkflowTests(unittest.TestCase):
    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showinfo")
    def test_import_updates_event_masks(self, info_mock):
        mask = np.ones((4, 4), dtype=bool)
        app = type("App", (), {})()
        app.root = object()
        app.frames_raw = [np.zeros((4, 4), dtype=np.uint8) for _ in range(5)]
        app.frames_sub_viz = app.frames_raw
        app.mask_import_dialog = _DialogStub(paths=["a.tif"], masks=[mask, mask], offset=1)
        app.event_records = {}
        app.active_event_id = "sd_event_001"
        app.project_session_service = _SessionStub()
        app.analysis_workspace = type("Workspace", (), {"open_event": lambda *_args, **_kwargs: None})()
        app.seg_state = object()
        app._collect_nonempty_final_mask_frames = lambda: {1, 2}
        app._set_propagated_frames = lambda *_args, **_kwargs: None
        app.update_display = lambda: None
        app._mark_project_dirty = lambda *_args, **_kwargs: None

        mask_import_workflow.import_external_masks(app)
        committed = app.event_records["sd_event_001"].analysis.masks_committed
        self.assertIn(1, committed)
        self.assertIn(2, committed)
        self.assertTrue(info_mock.called)


if __name__ == "__main__":
    unittest.main()
