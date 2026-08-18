"""The Model Manager list must stay reachable when the catalog outgrows the view.

The Treeview is capped at 8 visible rows, so before the scrollbar was added a longer
catalog left the trailing models unreachable.
"""

import gc
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import tkinter as tk
from tkinter import ttk

from swell.shared.ui.managed_model_workflow import (
    ManagedModelWorkflow,
    ManagedModelWorkflowOptions,
)


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


class _MissingPath:
    def exists(self) -> bool:
        return False


def _service(model_count, tmp_path):
    descriptors = [
        SimpleNamespace(checkpoint_id=f"ckpt_{i}", filename=f"model_{i}.pt")
        for i in range(model_count)
    ]
    return SimpleNamespace(
        load_catalog=lambda: descriptors,
        managed_models_dir=lambda: tmp_path,
        descriptor_path=lambda _d: _MissingPath(),
        download_descriptor=lambda _d: "",
    )


def _open_manager(root, model_count, tmp_path):
    """Open the real dialog, capture its scrollbar state, then close it."""
    workflow = ManagedModelWorkflow(
        root=root,
        service=_service(model_count, tmp_path),
        runner=SimpleNamespace(),
        options=ManagedModelWorkflowOptions(
            title="Model Manager",
            select_local_title="Select Local Model",
            unavailable_message="unavailable",
            empty_catalog_message="empty",
        ),
        get_current_managed_id=lambda: None,
        on_log_info=lambda _m: None,
        on_log_error=lambda _m: None,
        activate_managed=lambda _d, _s: True,
        activate_local=lambda _p, _s: True,
        prompt_select_local=lambda _d, _t: None,
    )

    captured = {}

    def _inspect():
        dialog = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        # The dialog runs a modal wait_window(); anything raised here would leave it
        # spinning forever, so it is destroyed unconditionally.
        try:
            dialog.update_idletasks()
            trees = _descendants_of_type(dialog, ttk.Treeview)
            scrollbars = _descendants_of_type(dialog, ttk.Scrollbar)
            captured["tree_count"] = len(trees)
            captured["scrollbar_count"] = len(scrollbars)
            if trees:
                captured["yscrollcommand"] = str(trees[0].cget("yscrollcommand"))
        except Exception as exc:
            captured["error"] = exc
        finally:
            dialog.destroy()

    root.after(50, _inspect)
    workflow.open_dialog()
    if "error" in captured:
        raise AssertionError(f"could not inspect the dialog: {captured['error']!r}")
    return captured


def _descendants_of_type(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_descendants_of_type(child, cls))
    return found


def test_model_manager_tree_has_a_scrollbar(tk_root, tmp_path):
    captured = _open_manager(tk_root, 5, tmp_path)
    assert captured["tree_count"] == 1
    assert captured["scrollbar_count"] == 1


def test_model_manager_wires_the_scrollbar_to_the_tree(tk_root, tmp_path):
    captured = _open_manager(tk_root, 60, tmp_path)
    assert captured["yscrollcommand"], "tree has no yscrollcommand"


class _RecordingScrollbar:
    def __init__(self) -> None:
        self.fractions = None
        self.gridded = True

    def set(self, first, last) -> None:
        self.fractions = (first, last)

    def grid(self, **_kwargs) -> None:
        self.gridded = True

    def grid_remove(self) -> None:
        self.gridded = False


def test_scroll_setter_hides_scrollbar_when_every_row_fits():
    scrollbar = _RecordingScrollbar()
    setter = ManagedModelWorkflow._make_treeview_scroll_setter(scrollbar)

    setter("0.0", "1.0")

    assert scrollbar.fractions == ("0.0", "1.0")
    assert not scrollbar.gridded


def test_scroll_setter_shows_scrollbar_when_rows_overflow():
    scrollbar = _RecordingScrollbar()
    setter = ManagedModelWorkflow._make_treeview_scroll_setter(scrollbar)

    setter("0.0", "1.0")
    assert not scrollbar.gridded

    # 60 models in an 8-row view: only a third of the list is visible.
    setter("0.0", "0.32")

    assert scrollbar.fractions == ("0.0", "0.32")
    assert scrollbar.gridded
