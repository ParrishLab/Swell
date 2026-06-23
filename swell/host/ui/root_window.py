from __future__ import annotations

from typing import TYPE_CHECKING

from swell.shared.app_metadata import format_window_title

if TYPE_CHECKING:
    from swell.shared.services import SingleInstanceBridge


def run_host_app(
    *,
    initial_project_path: str | None = None,
    instance_bridge: SingleInstanceBridge | None = None,
) -> None:
    from swell.shared.ui.theme import apply_theme
    from swell.shared.ui.bootstrap import center_window_on_screen, create_root_window, ttk

    root = create_root_window(themename="darkly")
    apply_theme(root)
    root.title(format_window_title("Swell"))
    root.geometry("480x220")
    center_window_on_screen(root, width=480, height=220)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    splash = ttk.Frame(root, padding=24, style="AppShell.TFrame")
    splash.grid(row=0, column=0, sticky="nsew")
    splash.columnconfigure(0, weight=1)
    splash.rowconfigure(0, weight=1)

    splash_card = ttk.Frame(splash, padding=24, style="AppCard.TFrame")
    splash_card.grid(row=0, column=0, sticky="nsew")
    splash_card.columnconfigure(0, weight=1)

    ttk.Label(splash_card, text="Starting Swell...", style="AppSectionTitle.TLabel", anchor="center").grid(
        row=0,
        column=0,
        pady=(12, 8),
    )
    ttk.Label(
        splash_card,
        text="Loading the packaged runtime and UI modules.",
        style="AppMeta.TLabel",
        justify="center",
        anchor="center",
    ).grid(row=1, column=0)
    try:
        root.update_idletasks()
        root.update()
    except Exception:
        pass

    from swell.host.app import SwellHostApp

    splash.destroy()
    SwellHostApp(root, initial_project_path=initial_project_path, instance_bridge=instance_bridge)
    root.mainloop()
