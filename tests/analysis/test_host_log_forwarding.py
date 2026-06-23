from __future__ import annotations

from swell.analysis.app import SwellAnalysisApp


def test_log_messages_forward_to_host_notifier_in_host_mode() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app._is_release_branch = False
    app._host_mode = True
    calls: list[tuple[str, str, str]] = []
    app._host_log_notifier = lambda level, context, message: calls.append((str(level), str(context), str(message)))
    app._set_loading_indicator = lambda *_args, **_kwargs: None

    app.log_warn("Model", "Model tools remain disabled.")
    app.log_info("Import", "Started import")

    assert calls[0] == ("WARN", "Model", "Model tools remain disabled.")
    assert calls[1] == ("INFO", "Import", "Started import")
