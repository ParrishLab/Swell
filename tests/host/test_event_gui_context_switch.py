from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from swell.host.controllers.project_lifecycle_controller import HostProjectLifecycleController
from swell.host.event_gui import SwellHostApp


class _Mgr:
    def __init__(self, refs):
        self._refs = list(refs)
        self.closed = False
        self.close_force = None
        self.results = [SimpleNamespace(closed=True)]

    def list_windows(self):
        return list(self._refs)

    def close_all(self, *, force=False):
        self.closed = True
        self.close_force = bool(force)
        if self.close_force:
            self._refs = []
        return list(self.results)


class _Root:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


def _app_with_refs(refs):
    app = SwellHostApp.__new__(SwellHostApp)
    app.analysis_window_manager = _Mgr(refs)
    app._analysis_windows = []
    app._show_warning = lambda *_args, **_kwargs: None
    app.root = _Root()
    app._instance_bridge = None
    app.browser_controller = SimpleNamespace(session=SimpleNamespace(state=lambda: SimpleNamespace(dirty=False)))
    app.save_host_session = lambda path=None: SimpleNamespace(project_path=path or "/tmp/test.sdproj")
    app.project_controller = HostProjectLifecycleController(app)
    return app


def test_close_analysis_windows_cancel_aborts():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=None):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is False
    assert app.analysis_window_manager.closed is False


def test_close_analysis_windows_no_save_closes_all():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=False):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is True
    assert app.analysis_window_manager.closed is True
    assert app.analysis_window_manager.close_force is True


def test_close_analysis_windows_save_then_continue_closes_all():
    def _save():
        dirty.project_dirty = False

    dirty = SimpleNamespace(project_dirty=True, save_project=_save)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=True):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is True
    assert app.analysis_window_manager.closed is True
    assert app.analysis_window_manager.close_force is True


def test_close_analysis_windows_save_canceled_aborts():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=True):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is False
    assert result["reason"] == "save_canceled"
    assert app.analysis_window_manager.closed is False


def test_close_analysis_windows_force_close_failure_aborts():
    app = _app_with_refs([SimpleNamespace(app=SimpleNamespace(project_dirty=False))])
    app.analysis_window_manager.results = [SimpleNamespace(closed=False)]

    result = app.close_analysis_windows_with_prompt()

    assert result["ok"] is False
    assert result["reason"] == "close_canceled"


def test_host_root_close_analysis_cancel_keeps_host_open():
    app = _app_with_refs([])
    app._get_project_controller = lambda: SimpleNamespace(request_host_close=lambda: {"ok": False, "reason": "canceled"})

    app._on_root_close()

    assert app.root.destroyed is False


def test_host_root_close_dirty_analysis_cancel_keeps_children_tracked():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    app._analysis_windows = [("window", dirty)]

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=None):
        result = app.project_controller.request_host_close()

    assert result["ok"] is False
    assert app.root.destroyed is False
    assert app.analysis_window_manager.list_windows() == [ref]


def test_host_root_close_dirty_analysis_no_save_closes_without_child_reprompt():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    app._analysis_windows = [("window", dirty)]

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=False):
        result = app.project_controller.request_host_close()

    assert result["ok"] is True
    assert app.root.destroyed is True
    assert app.analysis_window_manager.close_force is True


def test_host_root_close_dirty_analysis_save_then_continue_closes_host():
    def _save():
        dirty.project_dirty = False

    dirty = SimpleNamespace(project_dirty=True, save_project=_save)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=True):
        result = app.project_controller.request_host_close()

    assert result["ok"] is True
    assert app.root.destroyed is True


def test_host_root_close_dirty_analysis_save_failure_aborts():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    warnings = []
    app._show_warning = lambda *args, **kwargs: warnings.append((args, kwargs))

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=True):
        result = app.project_controller.request_host_close()

    assert result["ok"] is False
    assert result["reason"] == "save_failed"
    assert app.root.destroyed is False
    assert warnings


def test_host_root_close_dirty_host_cancel_aborts():
    app = _app_with_refs([])
    app.browser_controller = SimpleNamespace(session=SimpleNamespace(state=lambda: SimpleNamespace(dirty=True)))

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=None):
        result = app.project_controller.request_host_close()

    assert result["ok"] is False
    assert result["reason"] == "host_canceled"
    assert app.root.destroyed is False


def test_host_root_close_dirty_host_no_save_closes():
    app = _app_with_refs([])
    app.browser_controller = SimpleNamespace(session=SimpleNamespace(state=lambda: SimpleNamespace(dirty=True)))

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=False):
        result = app.project_controller.request_host_close()

    assert result["ok"] is True
    assert app.root.destroyed is True


def test_host_root_close_dirty_host_save_then_close():
    app = _app_with_refs([])
    dirty_state = SimpleNamespace(dirty=True)
    app.browser_controller = SimpleNamespace(session=SimpleNamespace(state=lambda: dirty_state))

    def _save(_path=None):
        dirty_state.dirty = False
        return SimpleNamespace(project_path="/tmp/test.sdproj")

    app.save_host_session = _save

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=True):
        result = app.project_controller.request_host_close()

    assert result["ok"] is True
    assert app.root.destroyed is True


def test_host_root_close_dirty_host_save_leaves_dirty_aborts():
    app = _app_with_refs([])
    dirty_state = SimpleNamespace(dirty=True)
    app.browser_controller = SimpleNamespace(session=SimpleNamespace(state=lambda: dirty_state))
    app.save_host_session = lambda _path=None: SimpleNamespace(project_path="/tmp/test.sdproj")

    with patch.object(app.project_controller, "_prompt_three_way_action", return_value=True):
        result = app.project_controller.request_host_close()

    assert result["ok"] is False
    assert result["reason"] == "host_save_canceled"
    assert app.root.destroyed is False


def test_center_window_on_screen_positions_geometry_to_screen_center():
    app = SwellHostApp.__new__(SwellHostApp)

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


def test_startup_preflight_reschedules_while_host_modal_is_open() -> None:
    app = SwellHostApp.__new__(SwellHostApp)
    calls: dict[str, object] = {"after": [], "preflight": 0}

    class _Root:
        def after(self, delay, callback):
            calls["after"].append((int(delay), callback))

    app.root = _Root()
    app._host_modal_dialog_depth = 1
    app._startup_preflight_completed = False
    app._get_model_setup_controller = lambda: SimpleNamespace(
        run_startup_preflight=lambda: calls.__setitem__("preflight", calls["preflight"] + 1)
    )

    app._run_model_startup_preflight()

    assert calls["preflight"] == 0
    assert calls["after"][0][0] == 250
    assert app._startup_preflight_completed is False


def test_startup_preflight_runs_once_when_no_host_modal_is_open() -> None:
    app = SwellHostApp.__new__(SwellHostApp)
    calls = {"preflight": 0}
    app._host_modal_dialog_depth = 0
    app._startup_preflight_completed = False
    app._get_model_setup_controller = lambda: SimpleNamespace(
        run_startup_preflight=lambda: calls.__setitem__("preflight", calls["preflight"] + 1)
    )

    app._run_model_startup_preflight()
    app._run_model_startup_preflight()

    assert calls["preflight"] == 1
    assert app._startup_preflight_completed is True


def test_rename_selected_event_updates_label() -> None:
    event = SimpleNamespace(event_id="event_0001", label="Old Label", flags={}, end_idx=3)
    tree = SimpleNamespace(
        selection=lambda: ["event_0001"],
        exists=lambda _iid: True,
        selection_set=lambda _iid: None,
        see=lambda _iid: None,
    )
    calls: dict[str, object] = {}
    app = SwellHostApp.__new__(SwellHostApp)
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

    with patch("swell.host.app.simpledialog.askstring", return_value="Renamed Event"):
        app._rename_selected_event()

    assert calls["update"]["event_id"] == "event_0001"
    assert calls["update"]["label"] == "Renamed Event"
    assert calls["active"] == "event_0001"
    assert calls["status"] == "Renamed Renamed Event."
    assert calls["log"] == "Renamed event_0001 to 'Renamed Event'."


def test_refresh_event_table_uses_visible_label_and_preserves_selection() -> None:
    inserts: list[dict[str, object]] = []
    reselections: list[str] = []

    class _Tree:
        def selection(self):
            return ["event_0002"]

        def get_children(self):
            return ["event_0001", "event_0002"]

        def delete(self, *_items):
            return None

        def insert(self, _parent, _index, iid, values):
            inserts.append({"iid": iid, "values": tuple(values)})

        def exists(self, iid):
            return str(iid) == "event_0002"

        def selection_add(self, iid):
            reselections.append(str(iid))

    app = SwellHostApp.__new__(SwellHostApp)
    app.tree = _Tree()

    app.refresh_event_table(
        [
            SimpleNamespace(event_id="event_0001", label="Visible Event", start_idx=1, end_idx=3, duration_frames=3),
            SimpleNamespace(event_id="event_0002", label="", start_idx=4, end_idx=5, duration_frames=2),
        ]
    )

    assert inserts == [
        {"iid": "event_0001", "values": ("Visible Event", 1, 3, 3)},
        {"iid": "event_0002", "values": ("event_0002", 4, 5, 2)},
    ]
    assert reselections == ["event_0002"]


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

    app = SwellHostApp.__new__(SwellHostApp)
    app.root = object()
    app.tree = _Tree()
    app._on_event_select = lambda _event=None: None
    app._rename_selected_event = lambda: None
    app._edit_selected = lambda: None
    app._delete_selected_events = lambda: None

    event = SimpleNamespace(x=4, y=8, x_root=40, y_root=80)
    with patch("swell.host.app.tk.Menu", _Menu):
        result = app._on_event_tree_context_menu(event)

    assert result == "break"
    assert selected == ["event_0002"]
    assert focused == ["event_0002"]
    assert popup_calls == [(40, 80)]
