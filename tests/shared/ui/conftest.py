"""Keep real-Tk dialog tests invisible without changing their layout lifecycle.

The dialogs in this directory are driven through production code that calls
``deiconify()`` and ``grab_set()``. A withdrawn toplevel does not receive its final
allocated geometry consistently across Tk platforms: Windows, in particular, can
leave its child widgets and canvases at 1px until the window is mapped. Replacing
``deiconify()`` with a no-op therefore made the tests inspect a layout users never
see.

Map the root and dialogs nearly transparent instead. Transient dialogs may remain
unmapped while their root is withdrawn, and Windows can skip final geometry for a
fully transparent window. A tiny nonzero alpha lets Tk and the window manager run
the production geometry lifecycle without a perceptible flash.
"""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(autouse=True)
def keep_dialogs_offscreen(monkeypatch):
    invisible_alpha = 0.01
    real_root_deiconify = tk.Tk.deiconify
    real_deiconify = tk.Toplevel.deiconify

    def invisibly_keep_root_mapped(window):
        window.attributes("-alpha", invisible_alpha)
        window.geometry("1x1+0+0")
        real_root_deiconify(window)

    def invisibly_deiconify(window):
        # Alpha is a window-manager attribute, so set it before mapping to avoid a
        # one-frame flash. Keep it nonzero so Windows performs normal mapped-window
        # geometry negotiation.
        window.attributes("-alpha", invisible_alpha)
        real_deiconify(window)

    # The local Tk fixtures call withdraw() immediately after construction. Keep
    # their roots mapped invisibly so transient child dialogs can also become mapped.
    monkeypatch.setattr(tk.Tk, "withdraw", invisibly_keep_root_mapped, raising=False)
    monkeypatch.setattr(tk.Tk, "wm_withdraw", invisibly_keep_root_mapped, raising=False)
    monkeypatch.setattr(tk.Toplevel, "deiconify", invisibly_deiconify, raising=False)
    monkeypatch.setattr(tk.Toplevel, "wm_deiconify", invisibly_deiconify, raising=False)
    # A modal grab is irrelevant to programmatic tests and can steal focus from the
    # developer even when the mapped window is transparent.
    monkeypatch.setattr(tk.Toplevel, "grab_set", lambda self: None, raising=False)
    monkeypatch.setattr(tk.Toplevel, "focus_force", lambda self: None, raising=False)
    yield
