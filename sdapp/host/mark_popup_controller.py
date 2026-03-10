from __future__ import annotations


class MarkPopupController:
    """Popup orchestration boundary.

    The GUI app still owns widget construction and rendering internals; this controller
    centralizes popup lifecycle entrypoints so a future refactor can move implementation
    details out of the Tk host incrementally.
    """

    def __init__(self, app) -> None:
        self.app = app

    def open_new(self) -> None:
        self.app._open_mark_popup(mode="new", event_id=None)

    def open_edit_selected(self) -> None:
        selected = list(self.app.tree.selection())
        if not selected:
            self.app._log_warn("Edit Selected blocked: no event selected.")
            self.app._show_warning("Event", "Select one event first.")
            return
        if len(selected) != 1:
            self.app._log_warn("Edit Selected blocked: multiple events selected.")
            self.app._show_warning("Event", "Select exactly one event to edit.")
            return
        self.app._open_mark_popup(mode="edit", event_id=selected[0])
