import inspect

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core import project_workflow


def test_set_busy_does_not_require_btn_import() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    status_updates: list[dict] = []
    loading_updates: list[tuple[bool, str]] = []
    save_states: list[str | None] = []

    app.lbl_status = type("L", (), {"configure": lambda self, **kwargs: status_updates.append(dict(kwargs))})()
    app._set_loading_indicator = lambda is_busy, text: loading_updates.append((bool(is_busy), str(text)))
    app.btn_save_masks = type(
        "B",
        (),
        {"configure": lambda self, **kwargs: save_states.append(kwargs.get("state"))},
    )()
    app._has_loaded_stack = lambda: False

    app._set_busy(True, "Status: Loading...", "orange")
    app._set_busy(False, "Status: Idle", "gray")

    assert len(status_updates) == 2
    assert status_updates[0]["text"] == "Status: Loading..."
    assert status_updates[1]["text"] == "Status: Idle"
    assert loading_updates == [(True, "Loading..."), (False, "Idle")]
    assert save_states == ["disabled", "disabled"]


def test_project_load_restore_no_longer_references_removed_analysis_spinboxes() -> None:
    source = inspect.getsource(project_workflow.apply_loaded_project_plan)
    assert "spin_analysis_start" not in source
    assert "spin_analysis_end" not in source
