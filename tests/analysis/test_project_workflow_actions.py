import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from swell.analysis.core import project_workflow


class ProjectWorkflowActionsTests(unittest.TestCase):
    def test_evaluate_close_requirements_reports_propagation_state(self):
        app = type("App", (), {})()
        app.frames_raw = [object()]
        app.current_project_path = None
        app._is_propagation_running = lambda: True
        req = project_workflow.evaluate_close_requirements(app)
        self.assertTrue(req.has_running_propagation)

    def test_save_project_to_path_uses_host_saver_in_host_mode(self):
        calls = []

        class _App:
            _host_mode = True
            current_project_path = None
            project_dirty = True
            _host_project_saver = staticmethod(lambda path: {"ok": True, "project_path": path})

            @staticmethod
            def _emit_host_sync(reason):  # noqa: ARG004
                calls.append("sync")
                return {"ok": True}

            @staticmethod
            def _host_project_saved_notifier(path):
                calls.append(path)

            @staticmethod
            def log_success(_ctx, _msg):
                calls.append("saved")

            @staticmethod
            def _build_project_payload():
                raise AssertionError("host-mode save should bypass analysis project store writer")

        app = _App()
        target = "/tmp/host_mode_save.sdproj"
        project_workflow.save_project_to_path(app, target, is_autosave=False)
        expected = str(Path(target).expanduser().resolve())
        self.assertEqual(app.current_project_path, expected)
        self.assertEqual(calls[0], "sync")
        self.assertIn(expected, calls)

    def test_save_project_to_path_raises_without_host_saver(self):
        class _App:
            _host_mode = True
            _host_project_saver = None

        with self.assertRaises(RuntimeError):
            project_workflow.save_project_to_path(_App(), "/tmp/no_host_saver.sdproj", is_autosave=False)

    def test_save_project_to_path_does_not_save_host_after_stale_sync_rejection(self):
        saver_calls = []

        class _App:
            _host_mode = True
            current_project_path = None
            project_dirty = True
            _host_project_saver = staticmethod(lambda path: saver_calls.append(path))
            _emit_host_sync = staticmethod(
                lambda reason: {
                    "ok": False,
                    "code": "STALE_ANALYSIS_MAPPING",
                    "message": "event mapping changed",
                }
            )

        with self.assertRaisesRegex(RuntimeError, "STALE_ANALYSIS_MAPPING"):
            project_workflow.save_project_to_path(_App(), "/tmp/stale.sdproj", is_autosave=False)

        self.assertEqual(saver_calls, [])

    def test_save_project_to_path_raises_runtime_error_for_invalid_target_path(self):
        class _App:
            _host_mode = True
            _host_project_saver = staticmethod(lambda path: {"ok": True, "project_path": path})

            @staticmethod
            def _emit_host_sync(reason):  # noqa: ARG004
                return {"ok": True}

            @staticmethod
            def log_success(_ctx, _msg):
                return None

        with self.assertRaises(RuntimeError):
            project_workflow.save_project_to_path(_App(), "bad\0path.sdproj", is_autosave=False)

    def test_save_project_rejects_missing_current_project_path(self):
        calls = []

        class _App:
            _host_mode = True
            current_project_path = None
            _host_project_saver = staticmethod(lambda path: calls.append(path))

            @staticmethod
            def save_project_as():
                raise AssertionError("missing existing project path should not silently switch targets")

        with TemporaryDirectory() as tmp:
            app = _App()
            app.current_project_path = str(Path(tmp) / "renamed_elsewhere.sdproj")

            with self.assertRaisesRegex(RuntimeError, "no longer exists"):
                project_workflow.save_project(app)

        self.assertEqual(calls, [])

    def test_resolve_project_image_paths_prefers_project_directory_over_cwd(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "project"
            cwd_dir = root / "cwd"
            project_image = project_dir / "images" / "frame.tif"
            cwd_image = cwd_dir / "images" / "frame.tif"
            project_image.parent.mkdir(parents=True)
            cwd_image.parent.mkdir(parents=True)
            project_image.write_bytes(b"project")
            cwd_image.write_bytes(b"cwd")
            stale_absolute = root / "old-drive" / "frame.tif"
            stale_absolute.parent.mkdir()
            stale_absolute.write_bytes(b"stale")
            loaded = SimpleNamespace(
                embedded_image_paths={},
                images_manifest={
                    "images": [
                        {
                            "id": "frame-1",
                            "absolute_path": str(stale_absolute),
                            "relative_path": "images/frame.tif",
                        }
                    ]
                },
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(cwd_dir)
                resolved = project_workflow.resolve_project_image_paths(
                    SimpleNamespace(current_project_path=None),
                    loaded,
                    project_path=project_dir / "analysis.swell",
                )
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(resolved, [str(project_image.resolve())])

if __name__ == "__main__":
    unittest.main()
