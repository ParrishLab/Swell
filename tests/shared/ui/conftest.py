"""Keep real-Tk dialog tests invisible without changing their layout lifecycle.

The dialogs in this directory are driven through production code that calls
``deiconify()`` and ``grab_set()``. A withdrawn toplevel does not receive its final
allocated geometry consistently across Tk platforms: Windows, in particular, can
leave its child widgets and canvases at 1px until the window is mapped. Replacing
``deiconify()`` with a no-op therefore made the tests inspect a layout users never
see.

Map the dialogs fully transparent instead. This lets Tk perform the same geometry
negotiation as production while preventing flashes and focus-stealing grabs.
"""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(autouse=True)
def keep_dialogs_offscreen(monkeypatch):
    real_deiconify = tk.Toplevel.deiconify

    def invisibly_deiconify(window):
        # Alpha is a window-manager attribute, so set it before mapping to avoid a
        # one-frame flash. Tk supports it on the platforms exercised by these tests.
        window.attributes("-alpha", 0.0)
        real_deiconify(window)

    monkeypatch.setattr(tk.Toplevel, "deiconify", invisibly_deiconify, raising=False)
    monkeypatch.setattr(tk.Toplevel, "wm_deiconify", invisibly_deiconify, raising=False)
    # A modal grab is irrelevant to programmatic tests and can steal focus from the
    # developer even when the mapped window is transparent.
    monkeypatch.setattr(tk.Toplevel, "grab_set", lambda self: None, raising=False)
    yield
