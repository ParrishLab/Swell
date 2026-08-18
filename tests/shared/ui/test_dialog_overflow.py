"""Overflowing dialogs must stay on screen with their action buttons reachable.

Both dialogs covered here previously sized themselves from their natural content
height with no scroll and no resize, so a long message or a long list of gap ranges
pushed the buttons past the screen edge.
"""

import gc
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import tkinter as tk

from swell.shared.ui.bootstrap import screen_work_area


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
        # Collect the discarded Tk widgets now, on the main thread. Left to a later
        # arbitrary collection they can be finalized while another test's worker
        # threads are running, and Tcl aborts the interpreter when that happens.
        gc.collect()


def _scrollbar_shown(canvas) -> bool:
    """Whether the scroll region's scrollbar is currently gridded.

    `winfo_ismapped` is useless here: the test root is withdrawn, so nothing in the
    dialog ever maps. `grid_remove()` clears grid_info(), which is what the auto-hide
    actually toggles.
    """
    scrollbar = [w for w in canvas.master.winfo_children() if isinstance(w, tk.ttk.Scrollbar)][0]
    return bool(scrollbar.grid_info())


def _make_dialog(root, message):
    from swell.shared.ui.dialogs import CustomDialog

    dlg = CustomDialog(
        root,
        "Test",
        message,
        dialog_type="error",
        buttons=[("OK", True, "primary")],
        default_button="OK",
        cancel_button="OK",
    )
    dlg.update_idletasks()
    return dlg


def test_custom_dialog_is_resizable(tk_root):
    dlg = _make_dialog(tk_root, "short message")
    try:
        assert dlg.resizable() == (True, True)
    finally:
        dlg.destroy()


def test_custom_dialog_clamps_long_message_to_work_area(tk_root):
    dlg = _make_dialog(tk_root, "Traceback: something went wrong.\n" * 800)
    try:
        _, work_h = screen_work_area(dlg)
        height = int(dlg.geometry().split("x", 1)[1].split("+", 1)[0])
        assert height <= work_h
    finally:
        dlg.destroy()


def test_custom_dialog_keeps_buttons_on_screen(tk_root):
    """The buttons must land on the display, not merely inside the window.

    Comparing against the window is meaningless here: the pre-fix dialog grew to
    ~9700px tall, so its buttons sat "inside" a window that itself extended far
    below the screen edge.
    """
    dlg = _make_dialog(tk_root, "Traceback: something went wrong.\n" * 800)
    try:
        dlg.update_idletasks()
        buttons = dlg.btn_widgets
        assert buttons
        screen_bottom = dlg.winfo_screenheight()
        for btn in buttons:
            assert btn.winfo_rooty() + btn.winfo_height() <= screen_bottom
    finally:
        dlg.destroy()


def test_custom_dialog_hides_scrollbar_when_message_fits(tk_root):
    dlg = _make_dialog(tk_root, "short message")
    try:
        dlg.update_idletasks()
        assert not _scrollbar_shown(dlg._message_scroll_canvas)
    finally:
        dlg.destroy()


def test_custom_dialog_shows_scrollbar_when_message_overflows(tk_root):
    dlg = _make_dialog(tk_root, "Traceback: something went wrong.\n" * 800)
    try:
        dlg.update_idletasks()
        assert _scrollbar_shown(dlg._message_scroll_canvas)
    finally:
        dlg.destroy()


def _propagation_payload(range_count: int) -> dict:
    frame_count = range_count * 4 + 8
    frame_indices = list(range(frame_count))
    values = [1.0] * frame_count
    runs = []
    for i in range(range_count):
        start = i * 4 + 2
        runs.append([start, start + 1])
        values[start] = None
        values[start + 1] = None
    return {
        "event_label": "Halo(Light Off) 1",
        "warning_kind": "gap",
        "gap_frame_runs": runs,
        "preview_frame_indices": frame_indices,
        "preview_speed_values": values,
    }


def _open_propagation_dialog(root, range_count):
    """Open the warning dialog, capture its widget state, then cancel it."""
    from types import SimpleNamespace

    from swell.host.controllers.host_window_controller import HostWindowController

    controller = HostWindowController(SimpleNamespace(root=root))
    captured = {}

    def _inspect():
        dialog = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        # The dialog runs a modal wait_window(); anything raised here would leave it
        # spinning forever, so it is destroyed unconditionally.
        try:
            dialog.update_idletasks()
            shell = dialog.winfo_children()[0]
            # shell children: the scroll container and the pinned footer.
            containers = shell.winfo_children()
            footer = [f for f in containers if any(isinstance(c, tk.ttk.Button) for c in f.winfo_children())][0]
            canvas = None
            for frame in containers:
                found = [c for c in frame.winfo_children() if isinstance(c, tk.Canvas)]
                if found:
                    canvas = found[0]
                    break
            captured["resizable"] = dialog.resizable()
            captured["dialog_bottom"] = dialog.winfo_rooty() + dialog.winfo_height()
            captured["screen_bottom"] = dialog.winfo_screenheight()
            captured["footer_bottom"] = footer.winfo_rooty() + footer.winfo_height()
            captured["scrollbar_shown"] = canvas is not None and _scrollbar_shown(canvas)
            captured["footer_height"] = footer.winfo_height()
            captured["button_heights"] = [c.winfo_height() for c in footer.winfo_children()]
        except Exception as exc:
            captured["error"] = exc
        finally:
            dialog.destroy()

    root.after(50, _inspect)
    controller.prompt_propagation_gap_action(_propagation_payload(range_count))
    if "error" in captured:
        raise AssertionError(f"could not inspect the dialog: {captured['error']!r}")
    return captured


def test_propagation_warning_is_resizable(tk_root):
    captured = _open_propagation_dialog(tk_root, 3)
    assert captured["resizable"] == (True, True)


def test_propagation_warning_keeps_footer_usable_with_many_ranges(tk_root):
    """The footer must keep real height, not be squeezed away by the range rows.

    Before the fix, 40 ranges collapsed the footer to 1px tall (buttons included)
    and parked it at the top of the dialog, so Confirm/Cancel were unclickable.
    """
    captured = _open_propagation_dialog(tk_root, 40)

    assert captured["footer_bottom"] <= captured["screen_bottom"]
    assert captured["footer_bottom"] <= captured["dialog_bottom"]
    assert captured["button_heights"], "footer had no buttons"
    for height in captured["button_heights"]:
        assert height > 10, f"footer button squeezed to {height}px"


def test_propagation_warning_scrolls_with_many_ranges(tk_root):
    captured = _open_propagation_dialog(tk_root, 40)
    assert captured["scrollbar_shown"]


def test_propagation_warning_hides_scrollbar_with_one_range(tk_root):
    captured = _open_propagation_dialog(tk_root, 1)
    assert not captured["scrollbar_shown"]


def test_dialogs_never_map_during_tests(tk_root):
    """Guards the conftest suppression: a test run must not flash windows on screen.

    Uses update_idletasks rather than update: Tk spins forever on idle events for a
    canvas window item inside a withdrawn toplevel, which is plain Tk behaviour and
    reproduces with no Swell code involved.
    """
    dlg = _make_dialog(tk_root, "short message")
    try:
        dlg.update_idletasks()
        assert not dlg.winfo_ismapped(), "dialog became visible during the test run"
    finally:
        dlg.destroy()
