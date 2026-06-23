from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from swell.host.browser_controller import BrowserController


def test_host_context_for_event_annotates_saved_sidecar_origins() -> None:
    controller = BrowserController()
    event = SimpleNamespace(
        event_id="event_0001",
        label="event_0001",
        start_idx=1264,
        end_idx=1297,
        flags={
            "analysis_scope_start_idx": 1234,
            "analysis_scope_end_idx": 1297,
            "analysis_local_event_start_idx": 30,
            "analysis_local_event_end_idx": 63,
        },
    )
    controller.events = SimpleNamespace(get_event=lambda _event_id: event)
    controller.session = SimpleNamespace(
        state=lambda: SimpleNamespace(
            project_path="/tmp/example.sdproj",
            metadata={},
            analysis_sidecar={
                "event_0001": {
                    "prompts": {"event_id": "event_0001", "frames": {"34": {"points": [{"x": 1.0, "y": 2.0, "label": 1}]}}},
                    "masks_committed": np.zeros((64, 10, 10), dtype=np.uint8),
                }
            },
        ),
        get_session_id=lambda: "session_x",
        get_stack_id=lambda: "stack_x",
    )
    controller.load_event_metrics_settings = lambda _event_id: None
    controller.resolve_event_metrics_settings = lambda _event_id: {}

    context = controller.host_context_for_event("event_0001")

    analysis_state = context["analysis_state"]
    assert analysis_state["prompts_frame_origin"] == "analysis_scope_local"
    assert analysis_state["masks_committed_frame_origin"] == "analysis_scope_local"
