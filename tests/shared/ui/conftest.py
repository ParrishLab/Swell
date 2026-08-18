"""Keep real-Tk dialog tests off the developer's screen.

The dialogs in this directory are driven through production code that calls
`deiconify()` and `grab_set()`, so without this the test run flashes real windows
onto the display and steals keyboard focus.

Suppressing both keeps every window withdrawn. Tk still runs the geometry manager
for unmapped windows, so sizes, grid state and widget heights -- everything these
tests assert on -- are computed exactly as they would be on screen. Nothing here
asserts on `winfo_ismapped`, which is the one thing that would differ.
"""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(autouse=True)
def keep_dialogs_offscreen(monkeypatch):
    monkeypatch.setattr(tk.Toplevel, "deiconify", lambda self: None, raising=False)
    monkeypatch.setattr(tk.Toplevel, "wm_deiconify", lambda self: None, raising=False)
    # A withdrawn window is not viewable, and Tk refuses to set a grab on one.
    monkeypatch.setattr(tk.Toplevel, "grab_set", lambda self: None, raising=False)
    yield
