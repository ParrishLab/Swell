"""The auto-height dialogs must scroll rather than clip on a short display.

Each of these sized itself from its natural content height and was then clamped to
the work area, so anything past the bottom -- including the action buttons -- was
simply cut off. They now cap the body and scroll the remainder.

`screen_work_area` is patched to fake a short display: on a large monitor these
dialogs fit outright and the scrolling path would never be exercised.
"""

import gc
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import tkinter as tk
from tkinter import ttk

import swell.shared.ui.bootstrap as bootstrap


@pytest.fixture()
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
        # Finalize Tk widgets on the main thread; a later collection can otherwise
        # run while another test's worker threads are live, which aborts Tcl.
        gc.collect()


@pytest.fixture()
def short_screen(monkeypatch):
    """Pretend the display only has 260px of usable height."""
    monkeypatch.setattr(bootstrap, "screen_work_area", lambda _w: (1430, 260))
    return 260


def _descendants(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_descendants(child, cls))
    return found


def _probe(root, opener):
    """Open a dialog, capture its layout, then close it."""
    captured = {}

    def _inspect():
        dialog = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        # These dialogs run a modal wait_window(); anything raised here would leave
        # them spinning forever, so the dialog is destroyed unconditionally.
        try:
            dialog.update_idletasks()
            shell = dialog.winfo_children()[0]
            rows = shell.winfo_children()
            canvas = next(
                (c for r in rows for c in r.winfo_children() if isinstance(c, tk.Canvas)), None
            )
            scrollbar = next(
                (c for r in rows for c in r.winfo_children() if isinstance(c, ttk.Scrollbar)), None
            )
            buttons = [b for r in rows for b in r.winfo_children() if isinstance(b, ttk.Button)]
            captured["height"] = int(dialog.geometry().split("x")[1].split("+")[0])
            captured["content"] = canvas.bbox("all")[3] if canvas and canvas.bbox("all") else 0
            captured["canvas"] = canvas.winfo_height() if canvas else 0
            captured["scrollbar_shown"] = bool(scrollbar.grid_info()) if scrollbar else False
            captured["button_heights"] = [b.winfo_height() for b in buttons]
        except Exception as exc:
            captured["error"] = exc
        finally:
            dialog.destroy()

    root.after(80, _inspect)
    opener()
    if "error" in captured:
        raise AssertionError(f"could not inspect the dialog: {captured['error']!r}")
    return captured


def _host_controller(root):
    from swell.host.controllers.host_window_controller import HostWindowController

    app = SimpleNamespace(
        root=root,
        reader=object(),
        stack_info=object(),
        output_var=SimpleNamespace(get=lambda: "/tmp/out"),
        browser_controller=SimpleNamespace(
            get_global_metrics_defaults=lambda: {},
            resolve_event_metrics_settings=lambda _e: {},
            event_display_name=lambda e: str(e),
            get_event=lambda _e: None,
        ),
        _open_metrics_dialog=None,
        _refresh_open_metrics_dialog=None,
        _show_warning=lambda *_a: None,
        _set_status=lambda *_a: None,
        _log_info=lambda *_a: None,
        _log_error=lambda *_a: None,
    )
    return HostWindowController(app)


def _dc_controller(root):
    from swell.host.controllers.dc_trace_controller import HostDCTraceController

    controller = HostDCTraceController.__new__(HostDCTraceController)
    controller.app = SimpleNamespace(root=root, _show_warning=lambda *_a: None)
    return controller


def _analysis_controller(root):
    from swell.host.controllers.analysis_launch_controller import AnalysisLaunchController

    controller = AnalysisLaunchController.__new__(AnalysisLaunchController)
    controller.app = SimpleNamespace(
        root=root,
        browser_controller=SimpleNamespace(
            event_display_name=lambda e: str(e), get_event=lambda _e: None
        ),
    )
    return controller


DIALOGS = {
    "export_options": lambda root: (
        lambda: _host_controller(root).prompt_export_options(["event_0001", "event_0002"])
    ),
    "open_metrics": lambda root: (lambda: _host_controller(root).open_generate_metrics_popup()),
    "import_dc_trace": lambda root: (
        lambda: _dc_controller(root)._open_import_dialog(
            {
                "source_path": "/tmp/trace.abf",
                "sweep_count": 3,
                "sample_rate_hz": 10000.0,
                "duration_s": 12.5,
                "channel_names": ["Ch0", "Ch1"],
                "channel_units": ["mV", "mV"],
            }
        )
    ),
    "analysis_open_options": lambda root: (
        lambda: _analysis_controller(root).prompt_analysis_open_options(
            event_id="event_0001", event_start=10, event_end=60
        )
    ),
}


@pytest.mark.parametrize("name", sorted(DIALOGS))
def test_dialog_fits_the_display(tk_root, short_screen, name):
    captured = _probe(tk_root, DIALOGS[name](tk_root))
    assert captured["height"] <= short_screen


@pytest.mark.parametrize("name", sorted(DIALOGS))
def test_dialog_scrolls_overflowing_content(tk_root, short_screen, name):
    captured = _probe(tk_root, DIALOGS[name](tk_root))
    assert captured["content"] > captured["canvas"], "content did not overflow; test is vacuous"
    assert captured["scrollbar_shown"]


@pytest.mark.parametrize("name", sorted(DIALOGS))
def test_dialog_keeps_buttons_usable(tk_root, short_screen, name):
    captured = _probe(tk_root, DIALOGS[name](tk_root))
    assert captured["button_heights"], "dialog had no buttons"
    for height in captured["button_heights"]:
        assert height > 10, f"button squeezed to {height}px"
