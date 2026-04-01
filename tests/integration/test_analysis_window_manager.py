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
        self.forced = False

    def on_close(self):
        self.closed = True
        self.win.destroy()

    def force_close(self):
        self.forced = True
        self.win.destroy()


class CancelingApp:
    def __init__(self, win: FakeWindow) -> None:
        self.win = win
        self.closed = False

    def on_close(self):
        self.closed = True


def test_window_manager_single_registration_focus_and_close() -> None:
    manager = AnalysisWindowManager()
    win = FakeWindow()
    app = FakeApp(win)
    manager.open_event_window("project", "event_0001", win, app)
    assert manager.focus_event_window("project", "event_0001") is True
    assert win.lifted is True
    assert win.focused is True
    result = manager.close_event_window("project", "event_0001")
    assert result.closed is True
    assert app.closed is True
    assert manager.get("project", "event_0001") is None


def test_window_manager_prompted_close_preserves_registration_when_child_cancels() -> None:
    manager = AnalysisWindowManager()
    win = FakeWindow()
    app = CancelingApp(win)
    manager.open_event_window("project", "event_0001", win, app)

    result = manager.close_event_window("project", "event_0001")

    assert result.closed is False
    assert app.closed is True
    assert manager.get("project", "event_0001") is not None
    assert win.destroyed is False


def test_window_manager_forced_close_does_not_clear_registry_early() -> None:
    manager = AnalysisWindowManager()
    win = FakeWindow()
    app = FakeApp(win)
    manager.open_event_window("project", "event_0001", win, app)

    results = manager.close_all(force=True)

    assert len(results) == 1
    assert results[0].closed is True
    assert results[0].forced is True
    assert app.forced is True
    assert manager.get("project", "event_0001") is None


def test_window_manager_close_results_match_actual_window_state() -> None:
    manager = AnalysisWindowManager()
    closing_win = FakeWindow()
    canceled_win = FakeWindow()
    manager.open_event_window("project", "event_0001", closing_win, FakeApp(closing_win))
    manager.open_event_window("project", "event_0002", canceled_win, CancelingApp(canceled_win))

    results = manager.close_all()

    by_key = {result.key: result for result in results}
    assert by_key[("project", "event_0001")].closed is True
    assert by_key[("project", "event_0002")].closed is False
    assert manager.get("project", "event_0001") is None
    assert manager.get("project", "event_0002") is not None
