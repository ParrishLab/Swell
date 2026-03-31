from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from sdapp.host.browser_controller import BrowserController
from sdapp.host.controllers.project_lifecycle_controller import HostProjectLifecycleController
from sdapp.host.config import FrameRef


class _FakeReader:
    def __init__(self) -> None:
        self._frames = [np.zeros((8, 9), dtype=np.uint8) for _ in range(6)]
        self._refs = [
            FrameRef(i, source_path=Path(f"/tmp/f_{i}.tif"), page_index=None, source_ext=".tif", frame_name=f"f_{i}.tif")
            for i in range(6)
        ]

    def get_frame_count(self) -> int:
        return len(self._frames)

    def get_stack_info(self):
        class _Info:
            frame_height = 8
            frame_width = 9

        return _Info()

    def get_frame_name(self, idx: int) -> str:
        return self._refs[idx].frame_name

    def get_frame_ref(self, idx: int):
        return self._refs[idx]

    def read_frame(self, idx: int, use_cache: bool = True):  # noqa: ARG002
        return self._frames[idx]


class _FakeStackInfo:
    def __init__(self) -> None:
        self.input_dir = "/tmp/in"
        self.frame_count = 6
        self.frame_height = 8
        self.frame_width = 9
        self.dtype = "uint8"


def test_global_metrics_update_sets_defaults_and_preserves_existing_local_overrides() -> None:
    browser = BrowserController()
    browser.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    event_1 = browser.create_event(start_idx=0, end_idx=1, frame_count=6)
    event_2 = browser.create_event(start_idx=2, end_idx=4, frame_count=6)
    browser.upsert_event_metrics_settings(event_1.event_id, {"scale_px_per_mm": 12.0}, merge_missing_only=False)

    logs: list[str] = []
    statuses: list[str] = []
    refresh_calls: list[str] = []
    window_controller = SimpleNamespace(refresh_open_metrics_popup=lambda: refresh_calls.append("refresh"))
    app = SimpleNamespace(
        browser_controller=browser,
        _set_status=lambda text: statuses.append(str(text)),
        _log_info=lambda text: logs.append(str(text)),
        _get_window_controller=lambda: window_controller,
    )
    controller = HostProjectLifecycleController(app)
    roi_mask = np.ones((8, 9), dtype=bool)

    result = controller.on_analysis_global_metrics_update(
        {
            "metrics_settings": {
                "scale_px_per_mm": 7.5,
                "roi_points": [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0]],
                "roi_mask": roi_mask,
            }
        }
    )

    assert result["ok"] is True
    defaults = browser.get_global_metrics_defaults()
    assert float(defaults["scale_px_per_mm"]) == 7.5
    event_1_metrics = browser.load_event_metrics_settings(event_1.event_id)
    event_2_metrics = browser.load_event_metrics_settings(event_2.event_id)
    assert event_1_metrics is not None and float(event_1_metrics["scale_px_per_mm"]) == 12.0
    assert event_2_metrics is not None and float(event_2_metrics["scale_px_per_mm"]) == 7.5
    assert np.array_equal(np.asarray(event_2_metrics["roi_mask"], dtype=bool), roi_mask)
    assert refresh_calls == ["refresh"]
