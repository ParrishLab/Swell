import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.state import AppConfig


class AppConfigTests(unittest.TestCase):
    def test_load_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.core.state.get_runtime_root", return_value=root), patch(
                "app.core.state.get_app_root", return_value=root
            ):
                cfg = AppConfig.load()
            self.assertEqual(cfg.default_output, "output")
            self.assertEqual(cfg.default_baseline, 30)

    def test_load_from_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text(
                '{"default_output":"out","default_model":"models/m.pt","default_baseline":12}',
                encoding="utf-8",
            )
            with patch("app.core.state.get_runtime_root", return_value=root), patch(
                "app.core.state.get_app_root", return_value=root
            ):
                cfg = AppConfig.load()
            self.assertEqual(cfg.default_output, "out")
            self.assertEqual(cfg.default_model, "models/m.pt")
            self.assertEqual(cfg.default_baseline, 12)

    def test_load_invalid_json_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text("{not-json", encoding="utf-8")
            with patch("app.core.state.get_runtime_root", return_value=root), patch(
                "app.core.state.get_app_root", return_value=root
            ):
                cfg = AppConfig.load()
            self.assertEqual(cfg.default_output, "output")
            self.assertEqual(cfg.default_baseline, 30)


if __name__ == "__main__":
    unittest.main()
