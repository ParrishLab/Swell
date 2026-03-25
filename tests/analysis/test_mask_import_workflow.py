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


class _AppStub:
    def __init__(self, *, dialog, host_mode=False, sync_result=None, sync_exc=None):
        self.root = object()
        self.frames_raw = [np.zeros((4, 4), dtype=np.uint8) for _ in range(5)]
        self.frames_sub_viz = self.frames_raw
        self.mask_import_dialog = dialog
        self.event_records = {}
        self.active_event_id = "sd_event_001"
        self.project_session_service = _SessionStub()
        self.analysis_workspace = type("Workspace", (), {"open_event": lambda *_args, **_kwargs: None})()
        self.seg_state = object()
        self._host_mode = bool(host_mode)
        self._sync_result = sync_result
        self._sync_exc = sync_exc
        self.sync_calls = []
        self.mark_dirty_calls = []
        self.logged_warnings = []

    def _collect_nonempty_final_mask_frames(self):
        return {1, 2}

    def _set_propagated_frames(self, *_args, **_kwargs):
        return None

    def update_display(self):
        return None

    def _mark_project_dirty(self, reason=""):
        self.mark_dirty_calls.append(str(reason))

    def _emit_host_sync(self, reason):
        self.sync_calls.append(str(reason))
        if self._sync_exc is not None:
            raise self._sync_exc
        return self._sync_result

    def log_warn(self, context, message):
        self.logged_warnings.append((str(context), str(message)))


class MaskImportWorkflowTests(unittest.TestCase):
    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showinfo")
    def test_import_updates_event_masks(self, info_mock):
        mask = np.ones((4, 4), dtype=bool)
        app = _AppStub(dialog=_DialogStub(paths=["a.tif"], masks=[mask, mask], offset=1))

        mask_import_workflow.import_external_masks(app)
        committed = app.event_records["sd_event_001"].analysis.masks_committed
        self.assertIn(1, committed)
        self.assertIn(2, committed)
        self.assertTrue(info_mock.called)
        self.assertEqual(app.sync_calls, [])

    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showwarning")
    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showinfo")
    def test_host_mode_import_emits_host_sync(self, info_mock, warning_mock):
        mask = np.ones((4, 4), dtype=bool)
        app = _AppStub(
            dialog=_DialogStub(paths=["a.tif"], masks=[mask, mask], offset=1),
            host_mode=True,
            sync_result={"ok": True, "event_id": "sd_event_001"},
        )

        mask_import_workflow.import_external_masks(app)

        self.assertEqual(app.sync_calls, ["import_external_masks"])
        self.assertEqual(warning_mock.call_count, 0)
        self.assertTrue(info_mock.called)

    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showwarning")
    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showinfo")
    def test_host_mode_import_surfaces_host_rejection_but_keeps_local_masks(self, info_mock, warning_mock):
        mask = np.ones((4, 4), dtype=bool)
        app = _AppStub(
            dialog=_DialogStub(paths=["a.tif"], masks=[mask, mask], offset=1),
            host_mode=True,
            sync_result={"ok": False, "code": "EVENT_NOT_FOUND", "message": "missing event"},
        )

        mask_import_workflow.import_external_masks(app)

        committed = app.event_records["sd_event_001"].analysis.masks_committed
        self.assertIn(1, committed)
        self.assertIn(2, committed)
        self.assertEqual(app.sync_calls, ["import_external_masks"])
        self.assertTrue(warning_mock.called)
        self.assertTrue(info_mock.called)

    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showwarning")
    @patch("sdapp.analysis.core.mask_import_workflow.messagebox.showinfo")
    def test_host_mode_import_surfaces_host_sync_exception_but_keeps_local_masks(self, info_mock, warning_mock):
        mask = np.ones((4, 4), dtype=bool)
        app = _AppStub(
            dialog=_DialogStub(paths=["a.tif"], masks=[mask, mask], offset=1),
            host_mode=True,
            sync_exc=RuntimeError("host offline"),
        )

        mask_import_workflow.import_external_masks(app)

        committed = app.event_records["sd_event_001"].analysis.masks_committed
        self.assertIn(1, committed)
        self.assertIn(2, committed)
        self.assertEqual(app.sync_calls, ["import_external_masks"])
        self.assertTrue(warning_mock.called)
        self.assertTrue(any(ctx == "HostSync" for ctx, _msg in app.logged_warnings))
        self.assertTrue(info_mock.called)


if __name__ == "__main__":
    unittest.main()
