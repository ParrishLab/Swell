from unittest.mock import patch
import tkinter as tk

import pytest

from swell.analysis.ui.layout import LayoutBuilder
from swell.analysis.ui.tooltips import TooltipManager


def _build_tk_or_skip(factory):
    """Construct an object that needs a real Tk root, skipping when Tk is
    unavailable (e.g. headless or misconfigured CI runners)."""
    try:
        return factory()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")


class _FakeRoot:
    def __init__(self):
        self.jobs = {}
        self.cancelled = []
        self.next_job = 1

    def after(self, delay, callback):
        job = f"job-{self.next_job}"
        self.next_job += 1
        self.jobs[job] = (int(delay), callback)
        return job

    def after_cancel(self, job):
        self.cancelled.append(job)
        self.jobs.pop(job, None)

    def run_jobs(self):
        jobs = list(self.jobs.items())
        self.jobs.clear()
        for _job, (_delay, callback) in jobs:
            callback()

    def winfo_screenwidth(self):
        return 100

    def winfo_screenheight(self):
        return 80


class _FakeWidget:
    def __init__(self, root, *, x=10, y=10):
        self.root = root
        self.x = x
        self.y = y
        self.bindings = {}

    def bind(self, sequence, callback, add=None):  # noqa: ARG002
        self.bindings.setdefault(sequence, []).append(callback)

    def winfo_toplevel(self):
        return self.root

    def winfo_rootx(self):
        return self.x

    def winfo_rooty(self):
        return self.y

    def fire(self, sequence, event=None):
        event = event or _FakeEvent(widget=self)
        for callback in self.bindings.get(sequence, []):
            callback(event)


class _FakeEvent:
    def __init__(self, *, x_root=10, y_root=10, widget=None):
        self.x_root = x_root
        self.y_root = y_root
        self.widget = widget


class _FakeTop:
    def __init__(self, _root):
        self.visible = False
        self.geometry_value = ""
        self.req_w = 40
        self.req_h = 20

    def withdraw(self):
        self.visible = False

    def overrideredirect(self, _value):
        return None

    def update_idletasks(self):
        return None

    def winfo_reqwidth(self):
        return self.req_w

    def winfo_reqheight(self):
        return self.req_h

    def geometry(self, value):
        self.geometry_value = value

    def deiconify(self):
        self.visible = True

    def lift(self):
        return None


class _FakeFrame:
    def __init__(self, _parent, **_kwargs):
        pass

    def grid(self, **_kwargs):
        return None


class _FakeLabel:
    def __init__(self, _parent, **_kwargs):
        self.config = {}

    def grid(self, **_kwargs):
        return None

    def configure(self, **kwargs):
        self.config.update(kwargs)


def _manager(root, *, clock=lambda: 0.0):
    return TooltipManager(root, clock=clock, toplevel_factory=_FakeTop)


def _patch_widgets():
    return (
        patch("swell.analysis.ui.tooltips.ttk.Frame", _FakeFrame),
        patch("swell.analysis.ui.tooltips.ttk.Label", _FakeLabel),
    )


def test_hover_tooltip_schedules_delayed_show_without_immediate_window() -> None:
    root = _FakeRoot()
    widget = _FakeWidget(root)
    manager = _manager(root)
    manager.attach(widget, "Select (V)")

    widget.fire("<Enter>")

    assert list(root.jobs.values())[0][0] == 600
    assert manager.create_count == 0
    assert getattr(widget, "_analysis_tooltip_text") == "Select (V)"


def test_leave_before_delay_cancels_pending_show() -> None:
    root = _FakeRoot()
    widget = _FakeWidget(root)
    manager = _manager(root)
    manager.attach(widget, "Select (V)")

    widget.fire("<Enter>")
    widget.fire("<Leave>")

    assert root.jobs == {}
    assert root.cancelled
    assert manager.create_count == 0


def test_scheduled_blank_tooltip_does_not_create_window() -> None:
    root = _FakeRoot()
    widget = _FakeWidget(root)
    manager = _manager(root)

    manager.schedule(widget, "   ")
    root.run_jobs()

    assert root.jobs == {}
    assert manager.create_count == 0


def test_rapid_tooltip_switches_reuse_one_window() -> None:
    root = _FakeRoot()
    first = _FakeWidget(root, x=10, y=10)
    second = _FakeWidget(root, x=20, y=20)
    manager = _manager(root)
    manager.attach(first, "First")
    manager.attach(second, "Second")

    first.fire("<Enter>", _FakeEvent(x_root=10, y_root=10, widget=first))
    second.fire("<Enter>", _FakeEvent(x_root=20, y_root=20, widget=second))
    with _patch_widgets()[0], _patch_widgets()[1]:
        root.run_jobs()
        manager.show_at_event(_FakeEvent(x_root=30, y_root=30, widget=first), "First")

    assert manager.create_count == 1


def test_escape_hides_visible_tooltip() -> None:
    root = _FakeRoot()
    widget = _FakeWidget(root)
    manager = _manager(root)
    manager.attach(widget, "Select (V)")

    with _patch_widgets()[0], _patch_widgets()[1]:
        manager.show_at_event(_FakeEvent(x_root=10, y_root=10, widget=widget), "Select (V)")
        assert manager._window.visible
        widget.fire("<Escape>")

    assert not manager._window.visible


def test_focus_tooltip_uses_shorter_focus_delay() -> None:
    root = _FakeRoot()
    widget = _FakeWidget(root)
    manager = _manager(root)
    manager.attach(widget, "Select (V)")

    widget.fire("<FocusIn>")

    assert list(root.jobs.values())[0][0] == 300


def test_cooldown_prevents_immediate_reschedule_after_hide() -> None:
    now = [0.0]
    root = _FakeRoot()
    widget = _FakeWidget(root)
    manager = _manager(root, clock=lambda: now[0])

    manager.hide()
    now[0] = 0.1
    manager.schedule(widget, "Hidden")
    assert root.jobs == {}

    now[0] = 0.3
    manager.schedule(widget, "Visible later")
    assert root.jobs


def test_tooltip_geometry_clamps_to_screen_bounds() -> None:
    root = _FakeRoot()
    manager = _manager(root)
    top = _FakeTop(root)

    assert manager._clamp_geometry(95, 75, top) == (52, 52)


def _find_label_text(widget, text):
    for child in widget.winfo_children():
        try:
            if child.cget("text") == text:
                return child
        except Exception:
            pass
        found = _find_label_text(child, text)
        if found is not None:
            return found
    return None


def test_dock_section_tooltip_is_limited_to_header_title() -> None:
    root = _build_tk_or_skip(tk.Tk)
    root.withdraw()
    try:
        app = LayoutBuilder()
        app.root = root
        parent = tk.Frame(root)
        section, _body = app._build_dock_section(parent, row=0, title="Regions", tooltip="Regions constrain final masks and exports; they do not seed propagation.")
        title = _find_label_text(section, "Regions")
        assert title is not None
        assert getattr(title, "_analysis_tooltip_text") == "Regions constrain final masks and exports; they do not seed propagation."
        assert not hasattr(section, "_analysis_tooltip_text")
    finally:
        root.destroy()


def test_tool_rail_keeps_shortcut_tooltips() -> None:
    class _App(LayoutBuilder):
        def __init__(self):
            self.root = tk.Tk()

        def _sync_tool_mode_buttons(self):
            return None

        def _sync_tool_options(self):
            return None

        def update_display(self):
            return None

        def clear_current_frame_data(self):
            return None

    app = _build_tk_or_skip(_App)
    app.root.withdraw()
    try:
        parent = tk.Frame(app.root)
        app._build_tools_group(parent, 0, vertical=True)
        assert getattr(app.btn_tool_select, "_analysis_tooltip_text") == "Select (V)"
        assert getattr(app.btn_tool_box, "_analysis_tooltip_text") == "Box (K)"
        assert not hasattr(app, "btn_tool_region")
        assert getattr(app.btn_tool_region_include, "_analysis_tooltip_text") == "Include Region (R)"
        assert getattr(app.btn_tool_region_exclude, "_analysis_tooltip_text") == "Exclude Region (Shift+R)"
    finally:
        app.root.destroy()


def test_view_controls_do_not_add_redundant_text_button_tooltips() -> None:
    class _App(LayoutBuilder):
        def __init__(self):
            self.root = tk.Tk()
            self.ghost_outlines_enabled_var = tk.BooleanVar(value=False)
            self.ghost_range_var = tk.IntVar(value=2)
            self.leverage_visibility_var = tk.BooleanVar(value=True)

        def update_display(self):
            return None

        def _redraw_slider_overlay(self):
            return None

        def jump_to_suggested_correction(self):
            return None

        def toggle_ground_truth_current_frame(self):
            return None

    app = _build_tk_or_skip(_App)
    app.root.withdraw()
    try:
        parent = tk.Frame(app.root)
        app._build_view_section(parent, row=0)
        assert not hasattr(app.chk_ghost, "_analysis_tooltip_text")
        assert not hasattr(app.chk_leverage_vis, "_analysis_tooltip_text")
        assert not hasattr(app.btn_jump_suggested, "_analysis_tooltip_text")
        assert not hasattr(app.btn_ground_truth, "_analysis_tooltip_text")
    finally:
        app.root.destroy()
