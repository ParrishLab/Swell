from __future__ import annotations

import os
from pathlib import Path
import shutil
from tkinter import filedialog, messagebox

from sdapp.shared.model_copy import (
    TITLE_MANAGE_MODELS,
    TITLE_MODEL_DOWNLOADED,
)
from sdapp.shared.services.checkpoint_runtime_service import is_managed_uri
from sdapp.shared.ui import BackgroundTaskRunner, ManagedModelWorkflow, ManagedModelWorkflowOptions


class AnalysisModelController:
    def __init__(self, app) -> None:
        self.app = app

    def update_project_model_to_active(self) -> None:
        if bool(getattr(self.app, "_host_mode", False)):
            host_updater = getattr(self.app, "_host_checkpoint_updater", None)
            if callable(host_updater):
                active_meta = dict(getattr(self.app, "_active_checkpoint_metadata", {}) or {})
                if not active_meta:
                    self.app.log_warn("Model", "No active model metadata available to record.")
                    messagebox.showwarning("Models", "No active model metadata available to record.", parent=self.app.root)
                    return
                self.app.log_info("Model", "Requesting host to update project model to active...")
                try:
                    host_updater({"model_checkpoint": dict(active_meta)})
                    self.app.log_success("Model", "Host project model updated.")
                except Exception as exc:
                    self.app.log_error("Model", f"Failed to request host model update: {exc}")
                    messagebox.showwarning("Models", f"Failed to update host model:\n{exc}", parent=self.app.root)
                return

    def browse_model(self):
        resource_root = Path(getattr(self.app, "resource_root", self.app.app_root))
        initialdir = str((resource_root / "models").resolve())
        current_text = ""
        try:
            current_text = str(self.app.get_model_token() or "").strip()
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

        center_window = getattr(self.app, "_center_window", None)
        if callable(center_window):
            center_window(self.app.root)
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

        self.app.set_model_token(selected_abs)
        self.app._manual_model_override = selected_abs
        self.app.log_info("Model", f"Model changed to: {Path(selected_abs).name}. Reloading...")
        self.app.start_model_initialization(reason="browse_model")

    def open_model_manager(self):
        if bool(getattr(self.app, "_host_mode", False)):
            host_opener = getattr(self.app, "_host_open_model_manager", None)
            if callable(host_opener):
                self.app.log_info("Model", "Opening host model manager...")
                try:
                    host_opener()
                except Exception as exc:
                    messagebox.showwarning("Models", f"Unable to open host model manager:\n{exc}", parent=self.app.root)
                return

        service = getattr(self.app, "checkpoint_runtime", None)
        if service is None:
            messagebox.showwarning("Models", "Model runtime service is unavailable.", parent=self.app.root)
            return
        workflow = ManagedModelWorkflow(
            root=self.app.root,
            service=service,
            runner=self._task_runner(),
            options=ManagedModelWorkflowOptions(
                title=TITLE_MANAGE_MODELS,
                select_local_title="Select SAM2 Model File",
                unavailable_message="Model runtime service is unavailable.",
                empty_catalog_message="No model catalog entries are available in checkpoints_catalog.json.",
                show_download_success=self._show_download_success,
                on_center_window=getattr(self.app, "_center_window", None),
            ),
            get_current_managed_id=self._current_managed_id,
            on_log_info=lambda message: self.app.log_info("Model", message),
            on_log_error=lambda message: self.app.log_error("Model", message),
            activate_managed=self._activate_managed_descriptor,
            activate_local=self._activate_local_path,
            prompt_select_local=self._prompt_select_local,
        )
        workflow.open_dialog(required=False)

    def open_checkpoint_manager(self):
        # Backward-compatible alias for existing callbacks.
        self.open_model_manager()

    def shutdown_model_resources(self):
        self.app.model_ready = False
        self.app.predictor = None
        self.app.inference_state = None
        if hasattr(self.app, "inference_manager") and self.app.inference_manager is not None:
            try:
                self.app.inference_manager.on_model_unloaded()
            except Exception:
                pass
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

    def _activate_managed_descriptor(self, descriptor, source: str) -> bool:
        self._apply_model_token(
            f"managed://{descriptor.checkpoint_id}",
            manual_override=None,
            reason=f"Using managed model file {descriptor.checkpoint_id}.",
        )
        return True

    def _activate_local_path(self, path: str, source: str) -> bool:  # noqa: ARG002
        selected_abs = str(Path(path).expanduser().resolve())
        self._apply_model_token(
            selected_abs,
            manual_override=selected_abs,
            reason=f"Using local model file {Path(selected_abs).name}.",
        )
        return True

    def _apply_model_token(self, token: str, *, manual_override: str | None, reason: str) -> None:
        self.app.set_model_token(str(token))
        self.app._manual_model_override = manual_override
        self.app.log_info("Model", reason)
        self.app.start_model_initialization(reason="model_manager")

    def _current_managed_id(self) -> str | None:
        current_token = str(self.app.get_model_token() or "").strip()
        if not is_managed_uri(current_token):
            return None
        return str(current_token).split("managed://", 1)[-1].strip() or None

    def _prompt_select_local(self, parent, title: str) -> str | None:
        center_window = getattr(self.app, "_center_window", None)
        if callable(center_window):
            center_window(parent)
        selected = filedialog.askopenfilename(
            parent=parent,
            title=title,
            initialdir=str(self.app.checkpoint_runtime.managed_models_dir()),
            filetypes=[("PyTorch model", "*.pt *.pth"), ("All files", "*.*")],
        )
        if not selected:
            return None
        return str(Path(selected).expanduser().resolve())

    def _show_download_success(self, path: str, descriptor, dialog) -> None:
        self.app.log_success("Model", f"Downloaded model file {descriptor.checkpoint_id}.")
        messagebox.showinfo(TITLE_MODEL_DOWNLOADED, f"Downloaded to:\n{path}", parent=dialog)

    def _task_runner(self) -> BackgroundTaskRunner:
        runner = getattr(self.app, "_background_task_runner", None)
        if isinstance(runner, BackgroundTaskRunner):
            return runner
        runner = BackgroundTaskRunner(self.app.root)
        self.app._background_task_runner = runner
        return runner
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
