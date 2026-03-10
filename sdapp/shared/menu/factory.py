from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable

MenuCommand = Callable[[], None]


def _resolve_command(app, candidates: Iterable[str]) -> MenuCommand | None:
    for name in candidates:
        fn = getattr(app, name, None)
        if callable(fn):
            return fn
    return None


def build_shared_menu(root, app, *, mode: str) -> tk.Menu:
    """Build a unified menu bar for both host and analysis windows."""
    menu = tk.Menu(root)
    file_menu = tk.Menu(menu, tearoff=False)
    config_menu = tk.Menu(menu, tearoff=False)

    file_items = [
        ("New Project", ("new_project", "_new_project")),
        ("Open Project...", ("open_project", "_open_project_dialog", "open_session")),
        ("Save Project", ("save_project", "_save_project", "save_session")),
        ("Save Project As...", ("save_project_as", "_save_project_as")),
        ("Convert to Project...", ("convert_to_project",)),
        ("Import External Masks...", ("import_external_masks",)),
        ("Recover Autosave...", ("recover_autosave",)),
        (None, None),
        ("Import Folder...", ("_load_stack",)),
        ("Export Folder...", ("_browse_output", "browse_output")),
        (None, None),
        ("Exit", ("_on_root_close", "on_close")),
    ]
    config_items = [
        ("Set Model Path...", ("on_browse_model",)),
        ("Load Model", ("load_model_from_menu",)),
        ("Validate Assets", ("validate_assets_from_menu", "_validate_assets")),
    ]
    mode_allow = {
        "Convert to Project...": {"analysis"},
        "Import External Masks...": {"analysis"},
        "Recover Autosave...": {"analysis"},
        "Import Folder...": {"host"},
        "Export Folder...": {"host"},
    }
    for label, names in file_items:
        if label is None:
            file_menu.add_separator()
            continue
        allowed = mode_allow.get(label)
        if allowed is not None and mode not in allowed:
            file_menu.add_command(label=label, state="disabled")
            continue
        command = _resolve_command(app, names or ())
        if command is None:
            file_menu.add_command(label=label, state="disabled")
            continue
        file_menu.add_command(label=label, command=command)

    menu.add_cascade(label="File", menu=file_menu)

    for label, names in config_items:
        allowed = {"analysis"}
        if mode not in allowed:
            config_menu.add_command(label=label, state="disabled")
            continue
        command = _resolve_command(app, names or ())
        if command is None:
            config_menu.add_command(label=label, state="disabled")
            continue
        config_menu.add_command(label=label, command=command)

    menu.add_cascade(label="Config", menu=config_menu)
    root.config(menu=menu)
    return menu
