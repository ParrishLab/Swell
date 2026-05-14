from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from sdapp.shared.model_copy import TITLE_MODEL_DOWNLOAD_FAILED, TITLE_MODEL_FILE_MISSING
from sdapp.shared.ui.background_task_runner import BackgroundTaskRunner
from sdapp.shared.ui.bootstrap import semantic_button_options


@dataclass(frozen=True)
class ManagedModelSelection:
    source: str
    descriptor: Any | None = None
    path: str | None = None


@dataclass(frozen=True)
class ManagedModelWorkflowOptions:
    title: str
    select_local_title: str
    unavailable_message: str
    empty_catalog_message: str
    selection_prompt: str = "Select a model entry and choose an action."
    show_download_success: Callable[[str, Any, object], None] | None = None
    review_only_label: str | None = None
    on_review_only: Callable[[], None] | None = None
    on_center_window: Callable[[object], None] | None = None


class ManagedModelWorkflow:
    def __init__(
        self,
        *,
        root,
        service,
        runner: BackgroundTaskRunner,
        options: ManagedModelWorkflowOptions,
        get_current_managed_id: Callable[[], str | None],
        on_log_info: Callable[[str], None],
        on_log_error: Callable[[str], None],
        activate_managed: Callable[[Any, str], bool],
        activate_local: Callable[[str, str], bool],
        prompt_select_local: Callable[[object, str], str | None],
    ) -> None:
        self._root = root
        self._service = service
        self._runner = runner
        self._options = options
        self._get_current_managed_id = get_current_managed_id
        self._on_log_info = on_log_info
        self._on_log_error = on_log_error
        self._activate_managed = activate_managed
        self._activate_local = activate_local
        self._prompt_select_local = prompt_select_local

    def _call_center_window(self, dialog) -> None:
        center_window = self._options.on_center_window
        if not callable(center_window):
            return
        try:
            center_window(dialog, width=680, height=360)
        except TypeError:
            center_window(dialog)

    @staticmethod
    def _call_dialog_method(dialog, name: str, *args) -> None:
        method = getattr(dialog, str(name), None)
        if callable(method):
            method(*args)

    def open_dialog(self, *, required: bool = False) -> dict[str, object]:
        from sdapp.shared.ui.theme import SPACING, apply_theme

        service = self._service
        if service is None:
            messagebox.showwarning("Models", self._options.unavailable_message, parent=self._root)
            return {"ok": False}

        descriptors = list(service.load_catalog())
        if not descriptors:
            messagebox.showwarning("Models", self._options.empty_catalog_message, parent=self._root)
            return {"ok": False}

        dialog = tk.Toplevel(self._root)
        self._call_dialog_method(dialog, "withdraw")
        dialog.title(self._options.title)
        dialog.transient(self._root)
        dialog.resizable(True, True)
        self._call_dialog_method(dialog, "geometry", "680x360")
        try:
            apply_theme(dialog)
        except Exception:
            pass

        shell = ttk.Frame(dialog, padding=SPACING.outer, style="AppShell.TFrame")
        shell.pack(fill="both", expand=True)
        managed_dir = service.managed_models_dir()
        ttk.Label(shell, text=f"Managed folder: {managed_dir}", style="AppMeta.TLabel").pack(anchor="w", pady=(0, SPACING.inner))

        tree_container = ttk.Frame(shell, style="AppInset.TFrame", padding=1)
        tree_container.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            tree_container,
            columns=("filename", "status"),
            show="headings",
            height=min(8, max(4, len(descriptors))),
        )
        tree.heading("filename", text="FILENAME")
        tree.heading("status", text="STATUS")
        tree.column("filename", width=320, anchor="w")
        tree.column("status", width=140, anchor="center")
        tree.pack(fill="both", expand=True)

        status_var = tk.StringVar(value=self._options.selection_prompt)
        ttk.Label(shell, textvariable=status_var, style="AppMeta.TLabel").pack(anchor="w", pady=(SPACING.inner, 0))

        btn_row = ttk.Frame(shell, style="AppShell.TFrame")
        btn_row.pack(fill="x", pady=(SPACING.inner, 0))
        
        download_btn = ttk.Button(btn_row, text="Download Selected", **semantic_button_options("secondary"))
        use_btn = ttk.Button(btn_row, text="Use Selected", **semantic_button_options("primary"))
        local_btn = ttk.Button(btn_row, text="Select Local...", **semantic_button_options("secondary"))
        close_btn = ttk.Button(btn_row, text="Close", command=dialog.destroy, **semantic_button_options("secondary"))
        
        download_btn.pack(side="left")
        use_btn.pack(side="left", padx=(SPACING.gap, 0))
        local_btn.pack(side="left", padx=(SPACING.gap, 0))
        close_btn.pack(side="right")
        
        review_btn = None
        if required and self._options.review_only_label and callable(self._options.on_review_only):
            review_btn = ttk.Button(
                btn_row, 
                text=self._options.review_only_label, 
                command=self._options.on_review_only,
                **semantic_button_options("secondary")
            )
            review_btn.pack(side="left", padx=(SPACING.gap, 0))

        descriptor_by_id = {d.checkpoint_id: d for d in descriptors}
        result: dict[str, object] = {"ok": False}

        def _set_busy(is_busy: bool) -> None:
            state = "disabled" if is_busy else "normal"
            for button in (download_btn, use_btn, local_btn, review_btn, close_btn):
                if button is None:
                    continue
                try:
                    button.configure(state=state)
                except Exception:
                    continue

        def _selected_descriptor():
            selected = tree.selection()
            if not selected:
                return None
            return descriptor_by_id.get(str(selected[0]))

        def _complete(success: bool) -> None:
            result["ok"] = bool(success)
            if success or required:
                dialog.destroy()

        def _refresh_rows() -> None:
            selected_id = self._get_current_managed_id()
            for item in tree.get_children():
                tree.delete(item)
            for descriptor in descriptors:
                installed = service.descriptor_path(descriptor).exists()
                status = "Installed" if installed else "Missing"
                tree.insert("", "end", iid=descriptor.checkpoint_id, values=(descriptor.filename, status))
            target_id = selected_id if selected_id in descriptor_by_id else descriptors[0].checkpoint_id
            tree.selection_set(target_id)
            tree.focus(target_id)

        def _download_selected() -> None:
            descriptor = _selected_descriptor()
            if descriptor is None:
                status_var.set("Select a model entry first.")
                return
            status_var.set(f"Downloading model file {descriptor.filename} ...")
            self._on_log_info(f"Downloading model file {descriptor.checkpoint_id}...")
            _set_busy(True)

            def _do_download():
                return service.download_descriptor(descriptor)

            def _on_download_success(path: str) -> None:
                _set_busy(False)
                _refresh_rows()
                status_var.set(f"Downloaded model file {descriptor.filename}.")
                if callable(self._options.show_download_success):
                    self._options.show_download_success(path, descriptor, dialog)
                if self._activate_managed(descriptor, "managed_download"):
                    _complete(True)
                else:
                    _complete(False)

            def _on_download_error(exc: Exception) -> None:
                _set_busy(False)
                status_var.set(f"Download failed: {exc}")
                self._on_log_error(f"Model download failed: {exc}")
                messagebox.showerror(TITLE_MODEL_DOWNLOAD_FAILED, str(exc), parent=dialog)

            self._runner.start(
                _do_download,
                on_success=_on_download_success,
                on_error=_on_download_error,
            )

        def _use_selected() -> None:
            descriptor = _selected_descriptor()
            if descriptor is None:
                status_var.set("Select a model entry first.")
                return
            managed_path = service.descriptor_path(descriptor)
            if not managed_path.exists():
                status_var.set("Selected model file is not downloaded yet.")
                messagebox.showwarning(
                    TITLE_MODEL_FILE_MISSING,
                    "Download the selected model file first.",
                    parent=dialog,
                )
                return
            if self._activate_managed(descriptor, "managed_select"):
                status_var.set(f"Using model file {descriptor.filename}.")
                _complete(True)
            else:
                status_var.set("Unable to activate selected model file.")
                _complete(False)

        def _select_local() -> None:
            self._call_center_window(dialog)
            selected = self._prompt_select_local(dialog, self._options.select_local_title)
            if not selected:
                return
            selected_abs = str(Path(selected).expanduser().resolve())
            if self._activate_local(selected_abs, "manual_override"):
                status_var.set(f"Using local model file: {Path(selected_abs).name}")
                _complete(True)
            else:
                status_var.set("Unable to activate selected local model file.")
                _complete(False)

        download_btn.configure(command=_download_selected)
        use_btn.configure(command=_use_selected)
        local_btn.configure(command=_select_local)
        _refresh_rows()
        dialog.update_idletasks()
        dialog.minsize(640, dialog.winfo_height())
        self._call_center_window(dialog)
        self._call_dialog_method(dialog, "deiconify")
        dialog.grab_set()
        self._root.wait_window(dialog)
        return result
