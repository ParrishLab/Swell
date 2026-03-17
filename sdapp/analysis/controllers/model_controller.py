from __future__ import annotations

import os
from pathlib import Path
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from sdapp.shared.services.checkpoint_runtime_service import is_managed_uri


class AnalysisModelController:
    def __init__(self, app) -> None:
        self.app = app

    def browse_model(self):
        resource_root = Path(getattr(self.app, "resource_root", self.app.app_root))
        initialdir = str((resource_root / "models").resolve())
        current_text = ""
        try:
            current_text = str(self.app.entry_model.get() or "").strip()
        except Exception:
            current_text = ""

        current_abs = ""
        if current_text:
            p = Path(current_text)
            if is_managed_uri(current_text):
                p = Path(initialdir)
            elif not p.is_absolute():
                p = resource_root / p
            current_abs = str(p.resolve())

        if current_text:
            try:
                p = Path(current_text)
                if is_managed_uri(current_text):
                    p = Path(initialdir)
                elif not p.is_absolute():
                    p = resource_root / p
                if p.exists():
                    initialdir = str((p.parent if p.is_file() else p).resolve())
            except Exception:
                pass

        selected = filedialog.askopenfilename(
            parent=self.app.root,
            title="Select SAM2 Model",
            initialdir=initialdir,
            filetypes=[
                ("PyTorch model", "*.pt *.pth"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return

        selected_abs = str(Path(selected).resolve())
        if selected_abs == current_abs:
            self.app.log_info("Model", "Selected model is unchanged; skipping reload.")
            return

        self.app.entry_model.delete(0, tk.END)
        self.app.entry_model.insert(0, selected_abs)
        self.app._manual_model_override = selected_abs
        self.app.log_info("Model", f"Model changed to: {Path(selected_abs).name}. Reloading...")
        self.app.start_model_initialization(reason="browse_model")

    def open_checkpoint_manager(self):
        service = getattr(self.app, "checkpoint_runtime", None)
        if service is None:
            messagebox.showwarning("Checkpoints", "Checkpoint runtime service is unavailable.", parent=self.app.root)
            return
        descriptors = list(service.load_catalog())
        if not descriptors:
            messagebox.showwarning(
                "Checkpoints",
                "No checkpoint catalog entries are available in checkpoints_catalog.json.",
                parent=self.app.root,
            )
            return

        dialog = tk.Toplevel(self.app.root)
        dialog.title("Manage Checkpoints")
        dialog.transient(self.app.root)
        dialog.resizable(True, False)
        dialog.grab_set()

        shell = ttk.Frame(dialog, padding=10)
        shell.pack(fill="both", expand=True)
        managed_dir = service.managed_models_dir()
        ttk.Label(shell, text=f"Managed folder: {managed_dir}").pack(anchor="w", pady=(0, 6))

        tree = ttk.Treeview(shell, columns=("filename", "status"), show="headings", height=min(6, max(3, len(descriptors))))
        tree.heading("filename", text="Filename")
        tree.heading("status", text="Status")
        tree.column("filename", width=280, anchor="w")
        tree.column("status", width=120, anchor="center")
        tree.pack(fill="x")

        status_var = tk.StringVar(value="Select a checkpoint and choose an action.")
        ttk.Label(shell, textvariable=status_var).pack(anchor="w", pady=(6, 0))

        btn_row = ttk.Frame(shell)
        btn_row.pack(fill="x", pady=(8, 0))
        download_btn = ttk.Button(btn_row, text="Download Selected")
        use_btn = ttk.Button(btn_row, text="Use Selected")
        local_btn = ttk.Button(btn_row, text="Select Local...")
        close_btn = ttk.Button(btn_row, text="Close", command=dialog.destroy)
        download_btn.pack(side="left")
        use_btn.pack(side="left", padx=(6, 0))
        local_btn.pack(side="left", padx=(6, 0))
        close_btn.pack(side="right")

        descriptor_by_id = {d.checkpoint_id: d for d in descriptors}

        def _set_busy(is_busy: bool) -> None:
            state = "disabled" if is_busy else "normal"
            for button in (download_btn, use_btn, local_btn, close_btn):
                button.configure(state=state)

        def _apply_model_token(token: str, *, manual_override: str | None, reason: str) -> None:
            self.app.entry_model.delete(0, tk.END)
            self.app.entry_model.insert(0, str(token))
            self.app._manual_model_override = manual_override
            self.app.log_info("Model", reason)
            self.app.start_model_initialization(reason="checkpoint_manager")

        def _refresh_rows() -> None:
            selected_id = None
            current_token = str(self.app.entry_model.get() or "").strip()
            if is_managed_uri(current_token):
                selected_id = str(current_token).split("managed://", 1)[-1].strip() or None
            for item in tree.get_children():
                tree.delete(item)
            for descriptor in descriptors:
                installed = service.descriptor_path(descriptor).exists()
                status = "Installed" if installed else "Missing"
                tree.insert("", "end", iid=descriptor.checkpoint_id, values=(descriptor.filename, status))
            if selected_id and selected_id in descriptor_by_id:
                tree.selection_set(selected_id)
                tree.focus(selected_id)
            elif descriptors:
                tree.selection_set(descriptors[0].checkpoint_id)
                tree.focus(descriptors[0].checkpoint_id)

        def _selected_descriptor():
            selected = tree.selection()
            if not selected:
                return None
            return descriptor_by_id.get(str(selected[0]))

        def _download_selected():
            descriptor = _selected_descriptor()
            if descriptor is None:
                status_var.set("Select a checkpoint first.")
                return
            status_var.set(f"Downloading {descriptor.filename} ...")
            self.app.log_info("Model", f"Downloading checkpoint {descriptor.checkpoint_id}...")
            _set_busy(True)

            def _worker():
                try:
                    path = service.download_descriptor(descriptor)
                except Exception as exc:
                    self.app.root.after(
                        0,
                        lambda e=exc: (
                            status_var.set(f"Download failed: {e}"),
                            self.app.log_error("Model", f"Checkpoint download failed: {e}"),
                            _set_busy(False),
                            messagebox.showerror("Checkpoint Download Failed", str(e), parent=dialog),
                        ),
                    )
                    return
                self.app.root.after(
                    0,
                    lambda p=path, d=descriptor: (
                        _refresh_rows(),
                        _set_busy(False),
                        status_var.set(f"Downloaded {d.filename}."),
                        self.app.log_success("Model", f"Downloaded checkpoint {d.checkpoint_id}."),
                        messagebox.showinfo("Checkpoint Downloaded", f"Downloaded to:\n{p}", parent=dialog),
                        _apply_model_token(
                            f"managed://{d.checkpoint_id}",
                            manual_override=None,
                            reason=f"Using managed checkpoint {d.checkpoint_id}.",
                        ),
                    ),
                )

            threading.Thread(target=_worker, daemon=True).start()

        def _use_selected():
            descriptor = _selected_descriptor()
            if descriptor is None:
                status_var.set("Select a checkpoint first.")
                return
            managed_path = service.descriptor_path(descriptor)
            if not managed_path.exists():
                status_var.set("Selected checkpoint is not downloaded yet.")
                messagebox.showwarning(
                    "Checkpoint Missing",
                    "Download the selected checkpoint first.",
                    parent=dialog,
                )
                return
            status_var.set(f"Using {descriptor.filename}.")
            _apply_model_token(
                f"managed://{descriptor.checkpoint_id}",
                manual_override=None,
                reason=f"Using managed checkpoint {descriptor.checkpoint_id}.",
            )

        def _select_local():
            selected = filedialog.askopenfilename(
                parent=dialog,
                title="Select SAM2 Checkpoint",
                initialdir=str(managed_dir),
                filetypes=[("PyTorch model", "*.pt *.pth"), ("All files", "*.*")],
            )
            if not selected:
                return
            selected_abs = str(Path(selected).expanduser().resolve())
            status_var.set(f"Using local checkpoint: {Path(selected_abs).name}")
            _apply_model_token(
                selected_abs,
                manual_override=selected_abs,
                reason=f"Using local checkpoint {Path(selected_abs).name}.",
            )

        download_btn.configure(command=_download_selected)
        use_btn.configure(command=_use_selected)
        local_btn.configure(command=_select_local)
        _refresh_rows()
        dialog.update_idletasks()
        dialog.minsize(dialog.winfo_width(), dialog.winfo_height())

    def shutdown_model_resources(self):
        self.app.model_ready = False
        self.app.predictor = None
        self.app.inference_state = None
        if hasattr(self.app, "sam2_runtime") and self.app.sam2_runtime is not None:
            try:
                self.app.sam2_runtime.shutdown()
            except Exception:
                pass
        try:
            if self.app.temp_dir and os.path.exists(self.app.temp_dir):
                shutil.rmtree(self.app.temp_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
