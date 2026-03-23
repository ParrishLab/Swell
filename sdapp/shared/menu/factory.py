from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable

from sdapp.shared.model_copy import MENU_MANAGE_MODELS

MenuCommand = Callable[[], None]


def _resolve_command(app, candidates: Iterable[str]) -> MenuCommand | None:
    for name in candidates:
        fn = getattr(app, name, None)
        if callable(fn):
            return fn
    return None


def build_shared_menu(root, app, *, mode: str, host_mode: bool = False) -> tk.Menu:
    """Build a unified menu bar for both host and analysis windows."""
    menu = tk.Menu(root)
    file_menu = tk.Menu(menu, tearoff=False)
    config_menu = tk.Menu(menu, tearoff=False)
    help_menu = tk.Menu(menu, tearoff=False)

    if mode == "analysis":
        file_items = [
            ("Save SD Project", ("save_project", "_save_project", "save_session")),
            ("Save SD Project As...", ("save_project_as", "_save_project_as")),
            ("Import External Masks...", ("import_external_masks",)),
            (None, None),
            ("Exit", ("_on_root_close", "on_close")),
        ]
    else:
        file_items = [
            ("New Project", ("new_project", "_new_project")),
            ("Open SD Project...", ("open_project", "_open_project_dialog", "open_session")),
            ("Save SD Project", ("save_project", "_save_project", "save_session")),
            ("Save SD Project As...", ("save_project_as", "_save_project_as")),
            (None, None),
            ("Exit", ("_on_root_close", "on_close")),
        ]
    config_items = [
        (MENU_MANAGE_MODELS, ("open_model_manager", "open_checkpoint_manager")),
        ("Set Model Path...", ("on_browse_model",)),
        ("Load Model", ("load_model_from_menu",)),
        ("Validate Assets", ("validate_assets_from_menu", "_validate_assets")),
    ]
    mode_allow = {
        "Import External Masks...": {"analysis"},
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

    config_allow = {
        MENU_MANAGE_MODELS: {"analysis", "host"},
        "Set Model Path...": {"analysis"},
        "Load Model": {"analysis"},
        "Validate Assets": {"analysis"},
    }
    for label, names in config_items:
        allowed = config_allow.get(label, {"analysis"})
        if mode not in allowed:
            config_menu.add_command(label=label, state="disabled")
            continue
        command = _resolve_command(app, names or ())
        if command is None:
            config_menu.add_command(label=label, state="disabled")
            continue
        config_menu.add_command(label=label, command=command)

    menu.add_cascade(label="Model", menu=config_menu)

    help_items = [
        ("Check for Updates...", ("check_for_updates",)),
    ]
    help_allow = {
        "Check for Updates...": {"host"},
    }
    added_help_items = False
    for label, names in help_items:
        allowed = help_allow.get(label, {"host"})
        if mode not in allowed:
            continue
        command = _resolve_command(app, names or ())
        if command is None:
            help_menu.add_command(label=label, state="disabled")
        else:
            help_menu.add_command(label=label, command=command)
        added_help_items = True
    if added_help_items:
        menu.add_cascade(label="Help", menu=help_menu)

    root.config(menu=menu)
    return menu
