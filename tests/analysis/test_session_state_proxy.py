import unittest

from sdapp.analysis.app import SDSegmentationApp


class SessionStateProxyTests(unittest.TestCase):
    def test_lazy_session_state_for_new_instances(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app._analysis_range_auto_follow = False
        app._export_range_auto_follow = False
        app.active_event_id = "ev_1"
        app.event_states = {"ev_1": {}}
        self.assertFalse(app._analysis_range_auto_follow)
        self.assertFalse(app._export_range_auto_follow)
        self.assertEqual(app.active_event_id, "ev_1")
        self.assertIn("ev_1", app.event_states)

    def test_open_from_host_handoff_binds_provided_frame_source(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)

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
        app = SDSegmentationApp.__new__(SDSegmentationApp)
        app.spin_baseline = type("S", (), {"get": lambda self: "2"})()

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

    def test_open_from_host_handoff_scopes_frame_source_to_event_bounds(self):
        app = SDSegmentationApp.__new__(SDSegmentationApp)

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
        app._prepare_host_mode_buffers = lambda _fs: None
        app._finalize_load_ui = lambda: None
        app.log_info = lambda *_args, **_kwargs: None
        app.log_warn = lambda *_args, **_kwargs: None
        app._run_thread = lambda _fn: setattr(app, "_thread_started", True)
        app._init_sam2_background = lambda: None
        app.entry_model = type("E", (), {"get": lambda self: "/tmp/model.pt"})()
        app.frame_source = None
        app.app_context = None

        result = app.open_from_host_handoff(
            {"event": {"start_idx": 2, "end_idx": 5}},
            frame_source=_Source(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["frame_count"], 4)
        self.assertTrue(getattr(app, "_thread_started", False))


if __name__ == "__main__":
    unittest.main()
