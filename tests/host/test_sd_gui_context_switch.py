from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sdapp.host.sd_gui import SDAnalyzerApp


class _Mgr:
    def __init__(self, refs):
        self._refs = list(refs)
        self.closed = False

    def list_windows(self):
        return list(self._refs)

    def close_all(self):
        self.closed = True


def _app_with_refs(refs):
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.analysis_window_manager = _Mgr(refs)
    app._analysis_windows = []
    app._show_warning = lambda *_args, **_kwargs: None
    return app


def test_close_analysis_windows_cancel_aborts():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=None):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is False
    assert app.analysis_window_manager.closed is False


def test_close_analysis_windows_no_save_closes_all():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=False):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is True
    assert app.analysis_window_manager.closed is True


def test_close_analysis_windows_save_then_continue_closes_all():
    def _save():
        dirty.project_dirty = False

    dirty = SimpleNamespace(project_dirty=True, save_project=_save)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=True):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is True
    assert app.analysis_window_manager.closed is True


def test_close_analysis_windows_save_canceled_aborts():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=True):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is False
    assert result["reason"] == "save_canceled"
    assert app.analysis_window_manager.closed is False


def test_center_window_on_screen_positions_geometry_to_screen_center():
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)

    class _Window:
        def __init__(self):
            self.last_geometry = ""

        def update_idletasks(self):
            return None

        def winfo_width(self):
            return 1000

        def winfo_height(self):
            return 700

        def winfo_reqwidth(self):
            return 1000

        def winfo_reqheight(self):
            return 700

        def winfo_screenwidth(self):
            return 2560

        def winfo_screenheight(self):
            return 1440

        def geometry(self, spec: str):
            self.last_geometry = str(spec)

    win = _Window()
    app._center_window_on_screen(win)
    assert win.last_geometry == "1000x700+780+370"


def test_rename_selected_event_updates_label() -> None:
    event = SimpleNamespace(event_id="event_0001", label="Old Label", flags={}, end_idx=3)
    tree = SimpleNamespace(
        selection=lambda: ["event_0001"],
        exists=lambda _iid: True,
        selection_set=lambda _iid: None,
        see=lambda _iid: None,
    )
    calls: dict[str, object] = {}
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.tree = tree
    app.root = object()
    app.stack_info = SimpleNamespace(frame_count=10)
    app.browser_controller = SimpleNamespace(
        update_event=lambda event_id, **kwargs: calls.setdefault(
            "update",
            {"event_id": event_id, **kwargs},
        )
        or event
    )
    app._get_event_by_id = lambda _event_id: event
    app._sync_event_projections = lambda: calls.__setitem__("synced", True)
    app._set_active_event_id = lambda event_id: calls.__setitem__("active", event_id)
    app._set_status = lambda message: calls.__setitem__("status", message)
    app._log_info = lambda message: calls.__setitem__("log", message)
    app._log_warn = lambda _message: None
    app._show_warning = lambda *_args, **_kwargs: None

    def _update_event(event_id, **kwargs):
        calls["update"] = {"event_id": event_id, **kwargs}
        return SimpleNamespace(event_id=event_id)

    app.browser_controller = SimpleNamespace(update_event=_update_event)

    with patch("sdapp.host.app.simpledialog.askstring", return_value="Renamed Event"):
        app._rename_selected_event()

    assert calls["update"]["event_id"] == "event_0001"
    assert calls["update"]["label"] == "Renamed Event"
    assert calls["active"] == "event_0001"


def test_event_tree_context_menu_selects_clicked_row_and_returns_break() -> None:
    selected: list[str] = []
    focused: list[str] = []
    popup_calls: list[tuple[int, int]] = []

    class _Tree:
        def identify_row(self, _y):
            return "event_0002"

        def selection_set(self, iid):
            selected.append(str(iid))

        def focus(self, iid):
            focused.append(str(iid))

    class _Menu:
        def __init__(self, *_args, **_kwargs):
            self.commands = []

        def add_command(self, **kwargs):
            self.commands.append(kwargs)

        def add_separator(self):
            self.commands.append({"separator": True})

        def tk_popup(self, x_root, y_root):
            popup_calls.append((int(x_root), int(y_root)))

        def grab_release(self):
            return None

    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.root = object()
    app.tree = _Tree()
    app._on_event_select = lambda _event=None: None
    app._rename_selected_event = lambda: None
    app._edit_selected = lambda: None
    app._delete_selected_events = lambda: None

    event = SimpleNamespace(x=4, y=8, x_root=40, y_root=80)
    with patch("sdapp.host.app.tk.Menu", _Menu):
        result = app._on_event_tree_context_menu(event)

    assert result == "break"
    assert selected == ["event_0002"]
    assert focused == ["event_0002"]
    assert popup_calls == [(40, 80)]
