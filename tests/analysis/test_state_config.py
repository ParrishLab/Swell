import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from swell.analysis.core.state import AppConfig


class AppConfigTests(unittest.TestCase):
    def test_load_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("swell.shared.config.get_runtime_root", return_value=root), patch(
                "swell.shared.config.get_app_root", return_value=root
            ), patch("swell.shared.config.get_resources_root", return_value=root):
                cfg = AppConfig.load()
            self.assertEqual(cfg.default_output, "output")
            self.assertEqual(cfg.default_baseline, 30)
            self.assertFalse(cfg.auto_check_enabled)
            self.assertEqual(cfg.release_channel, "stable")
            self.assertIsNone(cfg.appcast_url_for_platform("windows"))

    def test_load_from_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text(
                (
                    '{"default_output":"out","default_model":"models/m.pt","default_baseline":12,'
                    '"auto_check_enabled":false,"release_channel":"stable",'
                    '"last_update_check_at":"2026-03-22T12:00:00+00:00","ignored_version":"0.2.0"}'
                ),
                encoding="utf-8",
            )
            with patch("swell.shared.config.get_runtime_root", return_value=root), patch(
                "swell.shared.config.get_app_root", return_value=root
            ), patch("swell.shared.config.get_resources_root", return_value=root):
                cfg = AppConfig.load()
            self.assertEqual(cfg.default_output, "out")
            self.assertEqual(cfg.default_model, "models/m.pt")
            self.assertEqual(cfg.default_baseline, 12)
            self.assertFalse(cfg.auto_check_enabled)
            self.assertEqual(cfg.last_update_check_at, "2026-03-22T12:00:00+00:00")
            self.assertEqual(cfg.ignored_version, "0.2.0")

    def test_load_invalid_json_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text("{not-json", encoding="utf-8")
            with patch("swell.shared.config.get_runtime_root", return_value=root), patch(
                "swell.shared.config.get_app_root", return_value=root
            ), patch("swell.shared.config.get_resources_root", return_value=root):
                cfg = AppConfig.load()
            self.assertEqual(cfg.default_output, "output")
            self.assertEqual(cfg.default_baseline, 30)

    def test_loads_packaged_default_config_when_runtime_config_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            app_root = Path(tmp) / "app"
            resources_root = Path(tmp) / "resources"
            runtime_root.mkdir()
            app_root.mkdir()
            resources_root.mkdir()
            (resources_root / "default_config.json").write_text(
                '{"default_output":"packaged","default_model":"managed://sam2.1_hiera_base_plus","default_baseline":18}',
                encoding="utf-8",
            )
            with patch("swell.shared.config.get_runtime_root", return_value=runtime_root), patch(
                "swell.shared.config.get_app_root", return_value=app_root
            ), patch("swell.shared.config.get_resources_root", return_value=resources_root):
                cfg = AppConfig.load()
            self.assertEqual(cfg.default_output, "packaged")
            self.assertEqual(cfg.default_baseline, 18)

    def test_model_token_preserves_managed_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text(
                '{"default_output":"out","default_model":"managed://sam2.1_hiera_base_plus","default_baseline":12}',
                encoding="utf-8",
            )
            with patch("swell.shared.config.get_runtime_root", return_value=root), patch(
                "swell.shared.config.get_app_root", return_value=root
            ), patch("swell.shared.config.get_resources_root", return_value=root):
                cfg = AppConfig.load()
            self.assertEqual(cfg.model_token(), "managed://sam2.1_hiera_base_plus")

    def test_save_persists_updater_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = AppConfig(
                default_output="out",
                default_model="managed://sam2.1_hiera_base_plus",
                default_baseline=12,
                auto_check_enabled=False,
                release_channel="stable",
                last_update_check_at="2026-03-22T12:00:00+00:00",
                ignored_version="0.2.0",
            )
            with patch("swell.shared.config._runtime_config_dir", return_value=root):
                path = cfg.save()
            self.assertEqual(path, root / "config.json")
            saved = path.read_text(encoding="utf-8")
            self.assertIn('"auto_check_enabled": false', saved)
            self.assertIn('"ignored_version": "0.2.0"', saved)

    def test_mark_update_check_writes_iso_timestamp(self):
        cfg = AppConfig.load()
        ts = datetime(2026, 3, 23, 15, 0, tzinfo=timezone.utc)
        cfg.mark_update_check(ts)
        self.assertEqual(cfg.last_update_check_at, "2026-03-23T15:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
