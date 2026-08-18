"""Pan modifiers and the navigation hint shown by the image dialogs.

Set ROI and Set Scale both pan and zoom a canvas, but nothing on screen said so and
the two disagreed on the modifier: Set Scale accepted Shift or Space, Set ROI only
Space. Both now share one predicate and one hint string.
"""

import gc
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import tkinter as tk
from tkinter import ttk

import numpy as np

from swell.shared.ui.bootstrap import VIEW_NAVIGATION_HINT, pan_modifier_active

SHIFT = 0x0001
CONTROL = 0x0004


def _event(state):
    return SimpleNamespace(state=state)


def test_plain_click_does_not_pan():
    assert not pan_modifier_active(_event(0), space_requested=False)


def test_shift_click_pans():
    assert pan_modifier_active(_event(SHIFT), space_requested=False)


def test_space_click_pans():
    assert pan_modifier_active(_event(0), space_requested=True)


def test_other_modifiers_do_not_pan():
    assert not pan_modifier_active(_event(CONTROL), space_requested=False)


def test_missing_or_bad_state_does_not_pan():
    assert not pan_modifier_active(SimpleNamespace(), space_requested=False)
    assert not pan_modifier_active(_event("not-a-number"), space_requested=False)


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


def _label_texts(widget, found):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label):
            try:
                found.append(str(child.cget("text")))
            except tk.TclError:
                pass
        _label_texts(child, found)
    return found


def _hint_shown(root, opener):
    captured = {}

    def _inspect():
        dialog = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        # These dialogs are modal; anything raised here would leave them spinning.
        try:
            dialog.update_idletasks()
            captured["shown"] = VIEW_NAVIGATION_HINT in _label_texts(dialog, [])
        except Exception as exc:
            captured["error"] = exc
        finally:
            dialog.destroy()

    root.after(100, _inspect)
    opener()
    if "error" in captured:
        raise AssertionError(f"could not inspect the dialog: {captured['error']!r}")
    return captured.get("shown", False)


def _image():
    return (np.arange(200 * 300, dtype=np.uint8).reshape(200, 300))


def test_roi_dialog_shows_navigation_hint(tk_root):
    from swell.analysis.ui.roi_dialog import open_roi_dialog

    assert _hint_shown(tk_root, lambda: open_roi_dialog(tk_root, _image(), context="analysis"))


def test_scale_dialog_shows_navigation_hint(tk_root):
    from swell.analysis.ui.scale_dialog import open_scale_dialog

    def _open():
        open_scale_dialog(
            tk_root,
            _image(),
            lambda *a, **k: (a[0] if a else None),
            lambda *a, **k: (a[0] if a else None),
            lambda *a, **k: 1.0,
        )

    assert _hint_shown(tk_root, _open)
