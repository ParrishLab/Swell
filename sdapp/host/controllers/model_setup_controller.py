from __future__ import annotations

import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from sdapp.shared.model_copy import (
    STATUS_MODEL_DISABLED,
    STATUS_MODEL_ERROR,
    STATUS_MODEL_FILE_MISSING,
    STATUS_MODEL_READY,
    TITLE_MANAGE_MODELS,
    TITLE_MODEL_DOWNLOAD_FAILED,
    TITLE_MODEL_FILE_MISSING,
    TITLE_MODEL_METADATA_MISMATCH,
    mismatch_body,
    onboarding_body,
)
from sdapp.shared.services import CheckpointResolution, MODEL_CHECKPOINT_METADATA_KEY


class HostModelSetupController:
    def __init__(self, app) -> None:
        self.app = app

    def run_startup_preflight(self) -> dict[str, object]:
        resolution = self._resolve_active_model(project_metadata=None)
        if bool(getattr(resolution, "ok", False)) and self._apply_resolution(resolution, reason="startup"):
            return {"ok": True, "ready": True, "source": getattr(resolution, "source", "resolved")}
        self._set_gate_state(
            ready=False,
            disabled=False,
            reason=STATUS_MODEL_FILE_MISSING,
        )
        return self._run_guided_startup_setup()

    def open_model_manager(self, *, required: bool = False) -> dict[str, object]:
        service = getattr(self.app, "checkpoint_runtime", None)
        if service is None:
            messagebox.showwarning("Models", "Model runtime service is unavailable.", parent=self.app.root)
            self._set_gate_state(ready=False, disabled=True, reason=STATUS_MODEL_ERROR)
            return {"ok": False, "ready": False, "disabled": True}

        descriptors = list(service.load_catalog())
        if not descriptors:
            messagebox.showwarning(
                "Models",
                "No model catalog entries are available in checkpoints_catalog.json.",
                parent=self.app.root,
            )
            if required:
                self._set_review_only("Model catalog is unavailable; model tools are disabled.")
            return {"ok": False, "ready": bool(self.app._model_setup_ready), "disabled": bool(self.app._model_setup_disabled)}

        dialog = tk.Toplevel(self.app.root)
        dialog.title(TITLE_MANAGE_MODELS)
        dialog.transient(self.app.root)
        dialog.resizable(True, False)
        dialog.grab_set()

        shell = ttk.Frame(dialog, padding=10)
        shell.pack(fill="both", expand=True)
        managed_dir = service.managed_models_dir()
        ttk.Label(shell, text=f"Managed folder: {managed_dir}").pack(anchor="w", pady=(0, 6))

        tree = ttk.Treeview(
            shell,
            columns=("filename", "status"),
            show="headings",
            height=min(6, max(3, len(descriptors))),
        )
        tree.heading("filename", text="Filename")
        tree.heading("status", text="Status")
        tree.column("filename", width=320, anchor="w")
        tree.column("status", width=140, anchor="center")
        tree.pack(fill="x")

        status_var = tk.StringVar(value="Select a model entry and choose an action.")
        ttk.Label(shell, textvariable=status_var).pack(anchor="w", pady=(6, 0))

        btn_row = ttk.Frame(shell)
        btn_row.pack(fill="x", pady=(8, 0))
        download_btn = ttk.Button(btn_row, text="Download Selected")
        use_btn = ttk.Button(btn_row, text="Use Selected")
        local_btn = ttk.Button(btn_row, text="Select Local...")
        review_btn = ttk.Button(btn_row, text="Review-only")
        close_btn = ttk.Button(btn_row, text="Close", command=dialog.destroy)
        download_btn.pack(side="left")
        use_btn.pack(side="left", padx=(6, 0))
        local_btn.pack(side="left", padx=(6, 0))
        if required:
            review_btn.pack(side="left", padx=(6, 0))
        close_btn.pack(side="right")

        descriptor_by_id = {d.checkpoint_id: d for d in descriptors}
        result: dict[str, object] = {"ok": False, "ready": bool(self.app._model_setup_ready), "disabled": bool(self.app._model_setup_disabled)}

        def _set_busy(is_busy: bool) -> None:
            state = "disabled" if is_busy else "normal"
            for button in (download_btn, use_btn, local_btn, review_btn, close_btn):
                try:
                    button.configure(state=state)
                except Exception:
                    pass

        def _refresh_rows() -> None:
            selected_id = None
            current_token = str(getattr(self.app, "_active_model_token", "") or "").strip()
            if current_token.startswith("managed://"):
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

        def _complete(success: bool) -> None:
            result["ok"] = bool(success)
            result["ready"] = bool(self.app._model_setup_ready)
            result["disabled"] = bool(self.app._model_setup_disabled)
            if success or required:
                dialog.destroy()

        def _download_selected() -> None:
            descriptor = _selected_descriptor()
            if descriptor is None:
                status_var.set("Select a model entry first.")
                return
            status_var.set(f"Downloading model file {descriptor.filename} ...")
            self.app._log_info(f"Downloading model file {descriptor.checkpoint_id}...")
            _set_busy(True)

            def _worker() -> None:
                try:
                    service.download_descriptor(descriptor)
                except Exception as exc:
                    self.app.root.after(
                        0,
                        lambda e=exc: (
                            status_var.set(f"Download failed: {e}"),
                            self.app._log_error(f"Model download failed: {e}"),
                            _set_busy(False),
                            messagebox.showerror(TITLE_MODEL_DOWNLOAD_FAILED, str(e), parent=dialog),
                        ),
                    )
                    return

                def _on_done() -> None:
                    _set_busy(False)
                    _refresh_rows()
                    status_var.set(f"Downloaded model file {descriptor.filename}.")
                    if self._activate_managed_descriptor(descriptor, source="managed_download"):
                        self.app._log_info(f"Downloaded and activated model file {descriptor.filename}.")
                        _complete(True)
                    else:
                        _complete(False)

                self.app.root.after(0, _on_done)

            threading.Thread(target=_worker, daemon=True).start()

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
            if self._activate_managed_descriptor(descriptor, source="managed_select"):
                status_var.set(f"Using model file {descriptor.filename}.")
                _complete(True)
            else:
                status_var.set("Unable to activate selected model file.")
                _complete(False)

        def _select_local() -> None:
            selected = self._prompt_select_local_file(parent=dialog, title="Select SAM2 Model File")
            if not selected:
                return
            if self._activate_local_path(selected, source="manual_override"):
                status_var.set(f"Using local model file: {Path(selected).name}")
                _complete(True)
            else:
                status_var.set("Unable to activate selected local model file.")
                _complete(False)

        def _review_only() -> None:
            self._set_review_only("User selected review-only mode from model manager.")
            _complete(False)

        download_btn.configure(command=_download_selected)
        use_btn.configure(command=_use_selected)
        local_btn.configure(command=_select_local)
        review_btn.configure(command=_review_only)
        _refresh_rows()
        dialog.update_idletasks()
        dialog.minsize(dialog.winfo_width(), dialog.winfo_height())
        self._center(dialog)
        self.app.root.wait_window(dialog)
        return result

    def resolve_project_model_mismatch(self, project_metadata: dict | None) -> dict[str, object]:
        project_meta = dict(project_metadata or {})
        recorded = project_meta.get(MODEL_CHECKPOINT_METADATA_KEY)
        if not isinstance(recorded, dict):
            return {"ok": True, "action": "no_project_recorded_model"}

        active_meta = dict(getattr(self.app, "_active_model_metadata", {}) or {})
        if not active_meta:
            active_path = str(getattr(self.app, "_active_model_path", "") or "").strip()
            if active_path:
                active_meta = self.app.checkpoint_runtime.build_checkpoint_metadata(
                    checkpoint_id=str(getattr(self.app, "_active_checkpoint_id", "") or "").strip() or None,
                    path=active_path,
                    source="host_active",
                )
        if not active_meta:
            return {"ok": False, "action": "missing_active_model", "message": "No active model metadata available."}

        match, detail = self.app.checkpoint_runtime.compare_checkpoint_metadata(recorded, active_meta)
        if match:
            return {"ok": True, "action": "match"}

        response = messagebox.askyesnocancel(
            TITLE_MODEL_METADATA_MISMATCH,
            mismatch_body(detail),
            parent=self.app.root,
        )
        if response is None:
            self._set_review_only("Model tools disabled due model mismatch decision.")
            return {"ok": False, "action": "disabled"}
        if response is False:
            return {"ok": True, "action": "continue_current"}

        recorded_path = str(recorded.get("path", "") or "").strip()
        if recorded_path and Path(recorded_path).expanduser().exists():
            if self._activate_local_path(recorded_path, source="project_recorded"):
                return {"ok": True, "action": "switched_project_recorded"}

        selected = self._prompt_select_local_file(parent=self.app.root, title="Select Project-Recorded Model File")
        if not selected:
            return {"ok": False, "action": "switch_canceled"}
        if self._activate_local_path(selected, source="project_recorded_override"):
            return {"ok": True, "action": "switched_project_override"}
        return {"ok": False, "action": "switch_failed"}

    def build_host_model_context(self) -> dict[str, object]:
        return {
            "model_token": str(getattr(self.app, "_active_model_token", "") or ""),
            "manual_model_override": str(getattr(self.app, "_manual_model_override", "") or ""),
            "active_model_metadata": dict(getattr(self.app, "_active_model_metadata", {}) or {}),
            "ready": bool(getattr(self.app, "_model_setup_ready", False)),
            "disabled": bool(getattr(self.app, "_model_setup_disabled", False)),
            "reason": str(getattr(self.app, "_model_setup_reason", "") or ""),
        }

    def is_analysis_allowed(self) -> tuple[bool, str]:
        ready = bool(getattr(self.app, "_model_setup_ready", False))
        disabled = bool(getattr(self.app, "_model_setup_disabled", False))
        reason = str(getattr(self.app, "_model_setup_reason", "") or "")
        if ready and not disabled:
            return True, STATUS_MODEL_READY
        if disabled:
            return False, reason or STATUS_MODEL_DISABLED
        return False, reason or STATUS_MODEL_FILE_MISSING

    def _run_guided_startup_setup(self) -> dict[str, object]:
        while True:
            response = messagebox.askyesnocancel(
                "Model Setup Required",
                onboarding_body(),
                parent=self.app.root,
            )
            if response is None:
                self._set_review_only("Startup model setup skipped. Running in review-only mode.")
                return {"ok": False, "ready": False, "disabled": True, "source": "startup_review_only"}
            if response is True:
                descriptor = self.app.checkpoint_runtime.default_descriptor()
                if descriptor is None:
                    messagebox.showerror(
                        TITLE_MODEL_DOWNLOAD_FAILED,
                        "No default model descriptor is available in the catalog.",
                        parent=self.app.root,
                    )
                    continue
                try:
                    self.app.checkpoint_runtime.download_descriptor(descriptor)
                except Exception as exc:
                    self.app._log_error(f"Model download failed during startup setup: {exc}")
                    messagebox.showerror(TITLE_MODEL_DOWNLOAD_FAILED, str(exc), parent=self.app.root)
                    continue
                if self._activate_managed_descriptor(descriptor, source="startup_download"):
                    return {"ok": True, "ready": True, "disabled": False, "source": "startup_download"}
                continue

            selected = self._prompt_select_local_file(parent=self.app.root, title="Select SAM2 Model File")
            if not selected:
                continue
            if self._activate_local_path(selected, source="startup_manual_override"):
                return {"ok": True, "ready": True, "disabled": False, "source": "startup_manual_override"}

    def _resolve_active_model(self, project_metadata: dict | None) -> CheckpointResolution:
        project_checkpoint_meta = None
        if isinstance(project_metadata, dict):
            raw = project_metadata.get(MODEL_CHECKPOINT_METADATA_KEY)
            if isinstance(raw, dict):
                project_checkpoint_meta = raw
        return self.app.checkpoint_runtime.resolve_checkpoint(
            project_checkpoint_meta=project_checkpoint_meta,
            configured_model=str(getattr(self.app, "_active_model_token", "") or ""),
            manual_override=str(getattr(self.app, "_manual_model_override", "") or ""),
        )

    def _activate_managed_descriptor(self, descriptor, *, source: str) -> bool:
        managed_path = self.app.checkpoint_runtime.descriptor_path(descriptor)
        if not managed_path.exists():
            self._set_gate_state(ready=False, disabled=False, reason=STATUS_MODEL_FILE_MISSING)
            return False
        resolution = CheckpointResolution(
            ok=True,
            path=str(managed_path.resolve()),
            source=str(source or "managed"),
            checkpoint_id=str(descriptor.checkpoint_id),
            descriptor=descriptor,
            message=None,
        )
        return self._apply_resolution(resolution, reason=source)

    def _activate_local_path(self, path: str | Path, *, source: str) -> bool:
        selected_path = str(Path(path).expanduser().resolve())
        if not Path(selected_path).exists():
            self._set_gate_state(ready=False, disabled=False, reason=STATUS_MODEL_FILE_MISSING)
            return False
        inferred_id = self.app.checkpoint_runtime.infer_checkpoint_id_from_path(selected_path)
        descriptor = self.app.checkpoint_runtime.find_descriptor(inferred_id)
        resolution = CheckpointResolution(
            ok=True,
            path=selected_path,
            source=str(source or "manual_override"),
            checkpoint_id=inferred_id,
            descriptor=descriptor,
            message=None,
        )
        return self._apply_resolution(resolution, reason=source)

    def _apply_resolution(self, resolution: CheckpointResolution, *, reason: str) -> bool:
        if not bool(getattr(resolution, "ok", False)):
            self._set_gate_state(ready=False, disabled=False, reason=STATUS_MODEL_FILE_MISSING)
            return False
        model_path = str(getattr(resolution, "path", "") or "").strip()
        if not model_path or not os.path.exists(model_path):
            self._set_gate_state(ready=False, disabled=False, reason=STATUS_MODEL_FILE_MISSING)
            return False

        descriptor = getattr(resolution, "descriptor", None)
        checkpoint_id = str(getattr(resolution, "checkpoint_id", "") or "").strip() or None
        if checkpoint_id is None:
            checkpoint_id = self.app.checkpoint_runtime.infer_checkpoint_id_from_path(model_path)
        token = str(model_path)
        if descriptor is not None and getattr(descriptor, "checkpoint_id", None):
            token = f"managed://{descriptor.checkpoint_id}"

        manual_override = None if token.startswith("managed://") else model_path
        self.app._active_model_token = token
        self.app._manual_model_override = manual_override
        self.app._active_model_path = str(Path(model_path).expanduser().resolve())
        self.app._active_checkpoint_id = checkpoint_id

        try:
            metadata = self.app.checkpoint_runtime.build_checkpoint_metadata(
                checkpoint_id=checkpoint_id,
                path=self.app._active_model_path,
                source=str(getattr(resolution, "source", "") or reason or "resolved"),
            )
        except Exception:
            metadata = {
                "checkpoint_id": checkpoint_id,
                "filename": Path(self.app._active_model_path).name,
                "path": self.app._active_model_path,
                "sha256": None,
                "source": str(getattr(resolution, "source", "") or reason or "resolved"),
            }
        self.app._active_model_metadata = dict(metadata)
        try:
            self.app.browser_controller.set_model_checkpoint_metadata(dict(metadata))
        except Exception:
            pass

        self._set_gate_state(ready=True, disabled=False, reason=STATUS_MODEL_READY)
        self.app._set_status(f"{STATUS_MODEL_READY}: {Path(self.app._active_model_path).name}")
        self.app._log_info(f"Active model ready: {Path(self.app._active_model_path).name}.")
        return True

    def _set_review_only(self, reason: str) -> None:
        self._set_gate_state(ready=False, disabled=True, reason=reason or STATUS_MODEL_DISABLED)
        self.app._set_status(STATUS_MODEL_DISABLED)
        self.app._log_warn(reason or "Model tools disabled (review-only mode).")

    def _set_gate_state(self, *, ready: bool, disabled: bool, reason: str) -> None:
        self.app._model_setup_ready = bool(ready)
        self.app._model_setup_disabled = bool(disabled)
        self.app._model_setup_reason = str(reason or "")
        refresh = getattr(self.app, "_refresh_model_gate_ui", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass

    def _prompt_select_local_file(self, *, parent, title: str) -> str | None:
        self._center(parent)
        initialdir = str(self.app.checkpoint_runtime.managed_models_dir())
        selected = filedialog.askopenfilename(
            parent=parent,
            title=title,
            initialdir=initialdir,
            filetypes=[("PyTorch model", "*.pt *.pth"), ("All files", "*.*")],
        )
        if not selected:
            return None
        return str(Path(selected).expanduser().resolve())

    def _center(self, window) -> None:
        center = getattr(self.app, "_center_window_on_screen", None)
        if callable(center):
            center(window)

