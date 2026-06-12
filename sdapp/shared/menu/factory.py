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
    masks_menu = tk.Menu(menu, tearoff=False)
    config_menu = tk.Menu(menu, tearoff=False)

    if mode == "analysis":
        file_items = [
            ("Save SD Project", ("save_project", "_save_project", "save_session")),
            ("Save SD Project As...", ("save_project_as", "_save_project_as")),
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
            ("Import DC Trace...", ("import_dc_trace", "_import_dc_trace")),
            ("Remove DC Trace", ("remove_dc_trace", "_remove_dc_trace")),
            (None, None),
            ("Exit", ("_on_root_close", "on_close")),
        ]
    config_items = [
        (MENU_MANAGE_MODELS, ("open_model_manager", "open_checkpoint_manager")),
        ("Set Model Path...", ("on_browse_model",)),
        ("Load Model", ("load_model_from_menu",)),
        ("Update Project Model", ("update_project_model_to_active",)),
        ("Validate Assets", ("validate_assets_from_menu", "_validate_assets")),
    ]
    mode_allow = {
        "Import External Masks...": {"analysis"},
    }
    embed_var = getattr(app, "embed_images_menu_var", None)
    embed_cmd = _resolve_command(app, ("toggle_embed_source_images",))
    embed_available = mode != "analysis" and embed_var is not None and embed_cmd is not None

    def _add_embed_checkbutton() -> None:
        file_menu.add_checkbutton(
            label="Embed Source Images In Project File",
            variable=embed_var,
            command=embed_cmd,
        )

    for label, names in file_items:
        # Insert the embed toggle just above the DC trace section, between dividers.
        if embed_available and label == "Import DC Trace...":
            _add_embed_checkbutton()
            file_menu.add_separator()
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

    if mode == "analysis":
        command = _resolve_command(app, ("import_external_masks",))
        if command is None:
            masks_menu.add_command(label="Import External Masks...", state="disabled")
        else:
            masks_menu.add_command(label="Import External Masks...", command=command)
        menu.add_cascade(label="Masks", menu=masks_menu)

    config_allow = {
        MENU_MANAGE_MODELS: {"analysis", "host"},
        "Set Model Path...": {"analysis", "host"},
        "Load Model": {"analysis", "host"},
        "Update Project Model": {"analysis", "host"},
        "Validate Assets": {"analysis", "host"},
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

    root.config(menu=menu)
    return menu
