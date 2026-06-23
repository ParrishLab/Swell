from __future__ import annotations

from swell.analysis.app import SwellAnalysisApp


class _TreeStub:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []
        self.seen = None

    def insert(self, _parent: str, _index: str, text: str):
        item_id = f"item-{len(self.rows)}"
        self.rows.append((item_id, text))
        return item_id

    def get_children(self, _item: str = ""):
        return [item_id for item_id, _text in self.rows]

    def delete(self, item_id: str) -> None:
        self.rows = [(current_id, text) for current_id, text in self.rows if current_id != item_id]

    def see(self, item_id: str) -> None:
        self.seen = item_id


def test_logger_message_updates_log_buffer_and_host_forwarder() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app._analysis_log_buffer_limit = 2
    app._analysis_log_entries = []
    app.log_tree = _TreeStub()
    forwarded: list[tuple[str, str, str]] = []
    app._host_log_notifier = lambda level, context, body: forwarded.append((level, context, body))

    app._on_logger_message("[INFO][Model] Ready", False)
    app._on_logger_message("[WARN][Propagation] Processing frame 2", True)
    app._on_logger_message("[ERROR][Import] Failed to read stack", False)

    assert forwarded == [
        ("INFO", "Model", "Ready"),
        ("WARN", "Propagation", "Processing frame 2"),
        ("ERROR", "Import", "Failed to read stack"),
    ]
    assert app._analysis_log_entries == [
        "[WARN] [Propagation] Processing frame 2",
        "[ERROR] [Import] Failed to read stack",
    ]
    assert [text for _item_id, text in app.log_tree.rows] == app._analysis_log_entries
