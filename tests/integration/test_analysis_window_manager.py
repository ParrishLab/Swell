from __future__ import annotations

from sdapp.shared.services import AnalysisWindowManager


class FakeWindow:
    def __init__(self) -> None:
        self._exists = True
        self.focused = False
        self.lifted = False
        self.destroyed = False

    def winfo_exists(self):
        return self._exists

    def lift(self):
        self.lifted = True

    def focus_force(self):
        self.focused = True

    def destroy(self):
        self.destroyed = True
        self._exists = False


class FakeApp:
    def __init__(self, win: FakeWindow) -> None:
        self.win = win
        self.closed = False

    def on_close(self):
        self.closed = True
        self.win.destroy()


def test_window_manager_single_registration_focus_and_close() -> None:
    manager = AnalysisWindowManager()
    win = FakeWindow()
    app = FakeApp(win)
    manager.open_event_window("project", "event_0001", win, app)
    assert manager.focus_event_window("project", "event_0001") is True
    assert win.lifted is True
    assert win.focused is True
    manager.close_event_window("project", "event_0001")
    assert app.closed is True
    assert manager.get("project", "event_0001") is None
