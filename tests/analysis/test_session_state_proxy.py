import unittest

import numpy as np

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.controllers.host_mode_controller import AnalysisHostModeController
from swell.shared.frame_source.preprocessing import compute_visualization_stats


class SessionStateProxyTests(unittest.TestCase):
    def test_lazy_session_state_for_new_instances(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app._export_range_auto_follow = False
        app.active_event_id = "ev_1"
        app.event_states = {"ev_1": {}}
        self.assertFalse(app._export_range_auto_follow)
        self.assertEqual(app.active_event_id, "ev_1")
        self.assertIn("ev_1", app.event_states)

    def test_open_from_host_handoff_binds_provided_frame_source(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)

        class _Workspace:
            def __init__(self):
                self.bound = None
                self.open_kwargs = None

            def bind_frame_source(self, frame_source):
                self.bound = frame_source

            def open_from_handoff_payload(self, payload, frame_source=None, sync_emitter=None):
                self.open_kwargs = {
                    "payload": payload,
                    "frame_source": frame_source,
                    "sync_emitter": sync_emitter,
                }
                return {"ok": True}

        workspace = _Workspace()
        app.analysis_workspace = workspace
        app.frame_source = None
        app._ensure_analysis_workspace = lambda: None

        payload = {"event": {"event_id": "event_0001"}}
        emitter = lambda _payload: None
        result = app.open_from_host_handoff(payload, frame_source="host_fs", sync_emitter=emitter)
        self.assertTrue(result["ok"])
        self.assertEqual(app.frame_source, "host_fs")
        self.assertEqual(workspace.bound, "host_fs")
        self.assertEqual(workspace.open_kwargs["frame_source"], "host_fs")
        self.assertEqual(workspace.open_kwargs["sync_emitter"], emitter)

    def test_prepare_host_mode_buffers_creates_lazy_sequences(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)

        class _Source:
            frame_count = 2
            frame_names = ["a", "b"]
            source_paths = ["/tmp/a", "/tmp/b"]

            @staticmethod
            def get_raw_frame(idx):
                import numpy as np

                return np.full((3, 4), idx + 1, dtype=np.uint8)

            @staticmethod
            def get_subtracted_frame(_idx):
                raise NotImplementedError

            @staticmethod
            def get_visual_frame(_idx):
                raise NotImplementedError

        app._prepare_host_mode_buffers(_Source())
        self.assertEqual(len(app.frames_raw), 2)
        self.assertEqual(app.frames_raw[0].shape, (3, 4))
        self.assertEqual(app.frames_sub_viz.dtype.name, "uint8")
        self.assertEqual(app.frames_sub_viz[1].shape, (3, 4))
        self.assertEqual(app.frame_names, ["a", "b"])

    def test_prepare_host_mode_buffers_can_queue_async_launch_build_with_preview_seed(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)

        class _Source:
            frame_count = 4
            frame_shape = (3, 4)
            frame_names = ["a", "b", "c", "d"]
            source_paths = ["/tmp/a", "/tmp/b", "/tmp/c", "/tmp/d"]

            @staticmethod
            def get_raw_frame(idx):
                return np.full((3, 4), idx + 1, dtype=np.float32)

            @staticmethod
            def get_subtracted_frame(_idx):
                raise NotImplementedError

            @staticmethod
            def get_visual_frame(_idx):
                raise NotImplementedError

        source = _Source()
        stats = compute_visualization_stats(source, baseline_frames=2)
        app._host_mode = True
        app._host_processing_options = None
        app._host_buffer_sync_limit = 200
        app._host_buffer_cache_key = None
        app.frames_sub_viz = None
        app._host_buffer_generation = 0
        app._host_launch_preparation = {
            "local_frame_idx": 1,
            "raw_frame": np.full((3, 4), 2, dtype=np.float32),
            "sub_frame": np.full((3, 4), 1, dtype=np.float32),
            "viz_frame": np.full((3, 4), 128, dtype=np.uint8),
            "stats": stats,
        }
        app.root = type(
            "R",
            (),
            {
                "winfo_exists": staticmethod(lambda: False),
                "after": staticmethod(lambda *_args, **_kwargs: None),
            },
        )()
        app.log_info = lambda *_args, **_kwargs: None
        queued = {}
        app._run_thread = lambda target, **_kwargs: queued.setdefault("target", target)

        ready = app._prepare_host_mode_buffers(source, prefer_async=True)

        self.assertFalse(ready)
        self.assertIn("target", queued)
        self.assertIsNone(app.frames_raw)
        self.assertEqual(int(app._host_launch_preparation["local_frame_idx"]), 1)
        self.assertEqual(np.asarray(app._host_launch_preparation["viz_frame"]).shape, (3, 4))

    def test_prepare_host_mode_buffers_async_apply_populates_frames_without_numpy_truthiness_error(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)

        class _Source:
            frame_count = 3
            frame_shape = (3, 4)
            frame_names = ["a", "b", "c"]
            source_paths = ["/tmp/a", "/tmp/b", "/tmp/c"]

            @staticmethod
            def get_raw_frame(idx):
                return np.full((3, 4), idx + 1, dtype=np.float32)

            @staticmethod
            def get_subtracted_frame(_idx):
                raise NotImplementedError

            @staticmethod
            def get_visual_frame(_idx):
                raise NotImplementedError

        app._host_mode = True
        app._host_processing_options = None
        app._host_buffer_sync_limit = 1
        app._host_buffer_cache_key = None
        app.frames_sub_viz = None
        app._host_buffer_generation = 0
        app._host_pending_model_init_reason = None
        app.frame_names = []
        app._current_image_source_paths = []
        app.root = type(
            "R",
            (),
            {
                "winfo_exists": staticmethod(lambda: True),
                "after": staticmethod(lambda _ms, fn: fn()),
            },
        )()
        app._ui_alive = lambda: True
        app.log_info = lambda *_args, **_kwargs: None
        app.log_debug = lambda *_args, **_kwargs: None
        app._post_host_mode_open_ui = lambda message: setattr(app, "_post_open_message", str(message))
        queued = {}
        app._run_thread = lambda target, **_kwargs: queued.setdefault("target", target)

        ready = app._prepare_host_mode_buffers(_Source(), prefer_async=True)

        self.assertFalse(ready)
        queued["target"]()
        self.assertEqual(app.frames_raw.shape, (3, 3, 4))
        self.assertEqual(app.frames_sub_viz.shape, (3, 3, 4))
        self.assertEqual(getattr(app, "_post_open_message", ""), "Host workspace initialized.")

    def test_open_from_host_handoff_scopes_frame_source_to_event_bounds(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)

        class _Workspace:
            def __init__(self):
                self.bound = None

            def bind_frame_source(self, frame_source):
                self.bound = frame_source

            def open_from_handoff_payload(self, payload, frame_source=None, sync_emitter=None):
                return {"ok": True, "frame_count": int(frame_source.frame_count)}

        class _Source:
            frame_count = 10
            frame_shape = (3, 4)
            frame_names = [f"f{i}" for i in range(10)]
            source_paths = [f"/tmp/{i}" for i in range(10)]

            @staticmethod
            def get_raw_frame(idx):
                import numpy as np

                return np.full((3, 4), idx, dtype=np.uint8)

            @staticmethod
            def get_subtracted_frame(idx):
                return _Source.get_raw_frame(idx)

            @staticmethod
            def get_visual_frame(idx):
                return _Source.get_raw_frame(idx)

        app.analysis_workspace = _Workspace()
        app._ensure_analysis_workspace = lambda: None
        app._prepare_host_mode_buffers = lambda _fs: True
        app._finalize_load_ui = lambda: None
        app.log_info = lambda *_args, **_kwargs: None
        app.log_warn = lambda *_args, **_kwargs: None
        app.log_debug = lambda *_args, **_kwargs: None
        app.start_model_initialization = lambda **_kwargs: setattr(app, "_thread_started", True)
        app.frame_source = None
        app.app_context = None
        app.frames_sub_viz = np.zeros((1, 3, 4), dtype=np.uint8)

        result = app.open_from_host_handoff(
            {"event": {"start_idx": 2, "end_idx": 5}},
            frame_source=_Source(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["frame_count"], 4)
        self.assertTrue(getattr(app, "_thread_started", False))

    def test_open_from_host_handoff_defers_model_init_until_frames_ready(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)

        class _Workspace:
            def bind_frame_source(self, _frame_source):
                return None

            def open_from_handoff_payload(self, payload, frame_source=None, sync_emitter=None):
                return {"ok": True, "frame_count": int(frame_source.frame_count)}

        class _Source:
            frame_count = 5
            frame_shape = (3, 4)
            frame_names = [f"f{i}" for i in range(5)]
            source_paths = [f"/tmp/{i}" for i in range(5)]

            @staticmethod
            def get_raw_frame(idx):
                return np.full((3, 4), idx, dtype=np.uint8)

            @staticmethod
            def get_subtracted_frame(idx):
                return _Source.get_raw_frame(idx)

            @staticmethod
            def get_visual_frame(idx):
                return _Source.get_raw_frame(idx)

        app.analysis_workspace = _Workspace()
        app._ensure_analysis_workspace = lambda: None
        app._prepare_host_mode_buffers = lambda _fs, **_kwargs: False
        app._finalize_load_ui = lambda: None
        app.log_info = lambda *_args, **_kwargs: None
        app.log_warn = lambda *_args, **_kwargs: None
        app.frame_source = None
        app.app_context = None
        started: list[str] = []
        app.start_model_initialization = lambda **kwargs: started.append(str(kwargs.get("reason")))

        result = app.open_from_host_handoff(
            {"event": {"start_idx": 1, "end_idx": 3}},
            frame_source=_Source(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(started, [])
        self.assertEqual(getattr(app, "_host_pending_model_init_reason", None), "host_handoff_open")

    def test_host_mode_controller_starts_pending_model_init_once_frames_exist(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app.frames_sub_viz = np.zeros((2, 3, 4), dtype=np.uint8)
        app._host_pending_model_init_reason = "host_context_open"
        app.log_info = lambda *_args, **_kwargs: None
        started: list[str] = []
        app.start_model_initialization = lambda **kwargs: started.append(str(kwargs.get("reason")))

        controller = AnalysisHostModeController(app)
        controller._maybe_start_host_model_initialization("host_context_open")

        self.assertEqual(started, ["host_context_open"])
        self.assertIsNone(getattr(app, "_host_pending_model_init_reason", None))

    def test_post_host_mode_open_ui_reloads_active_event_state_after_finalize(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        opened: list[str] = []
        finalized: list[bool] = []
        recomputed: list[str] = []
        synced: list[str] = []
        app.slider = object()
        app.canvas_left = object()
        app.active_event_id = "event_0001"
        app._finalize_load_ui = lambda preserve_workspace_state=False: finalized.append(bool(preserve_workspace_state))
        app._recompute_slider_jump_markers = lambda: recomputed.append("markers")
        app._sync_saved_mask_overlay_state = lambda: synced.append("masks")
        app.update_display = lambda **_kwargs: None
        app.log_debug = lambda *_args, **_kwargs: None
        app.log_info = lambda *_args, **_kwargs: None
        app.log_warn = lambda *_args, **_kwargs: None
        app.lbl_status = type("L", (), {"configure": lambda self, **_kwargs: None})()
        app.analysis_workspace = type("W", (), {"open_event": lambda self, eid: opened.append(str(eid))})()
        app.root = type(
            "R",
            (),
            {
                "after": staticmethod(lambda _ms, fn: fn()),
            },
        )()

        app._post_host_mode_open_ui("Host direct workspace initialized.")

        self.assertEqual(opened, ["event_0001"])
        self.assertEqual(finalized, [True])
        self.assertEqual(recomputed, ["markers"])
        self.assertEqual(synced, ["masks"])

    def test_open_from_host_context_ready_path_completes_host_open_once(self):
        app = SwellAnalysisApp.__new__(SwellAnalysisApp)

        class _Workspace:
            def bind_frame_source(self, _frame_source):
                return None

            def open_from_host_event_context(self, context, frame_source=None, sync_emitter=None):
                del context, sync_emitter
                return {"ok": True, "frame_count": int(frame_source.frame_count)}

        class _Source:
            frame_count = 5
            frame_shape = (3, 4)
            frame_names = [f"f{i}" for i in range(5)]
            source_paths = [f"/tmp/{i}" for i in range(5)]

        app.analysis_workspace = _Workspace()
        app._ensure_analysis_workspace = lambda: None
        app._prepare_host_mode_buffers = lambda _fs, **_kwargs: True
        post_open_messages: list[str] = []
        app._post_host_mode_open_ui = lambda message: post_open_messages.append(str(message))
        app.log_info = lambda *_args, **_kwargs: None
        app.log_warn = lambda *_args, **_kwargs: None
        app.log_debug = lambda *_args, **_kwargs: None
        app.frame_source = None
        app.app_context = None
        app._host_analysis_updater = None
        app._host_project_saved_notifier = None
        app._host_sync_result_notifier = None
        app._host_log_notifier = None
        app._host_metrics_updater = None
        app._host_global_metrics_updater = None
        app._host_checkpoint_updater = None
        app._host_open_model_manager = None
        app._host_project_saver = lambda *args, **kwargs: None
        app._host_project_path_provider = None
        app._set_active_checkpoint_metadata = lambda *args, **kwargs: None
        app._apply_host_metrics_settings = lambda *args, **kwargs: None
        app._sync_saved_mask_overlay_state = lambda *args, **kwargs: None
        app._analysis_payload_has_saved_masks = lambda payload: bool(payload)
        app._saved_project_masks_by_event = {}
        app.current_project_path = None
        started: list[str] = []
        app.start_model_initialization = lambda **kwargs: started.append(str(kwargs.get("reason")))

        result = app.open_from_host_context(
            {"event": {"event_id": "event_0001", "start_idx": 1, "end_idx": 3}},
            frame_source=_Source(),
            on_host_project_save=lambda *args, **kwargs: None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(post_open_messages, ["Host direct workspace initialized."])
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main()
