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
from sdapp.shared.ui import BackgroundTaskRunner, ManagedModelWorkflow, ManagedModelWorkflowOptions


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

        workflow = ManagedModelWorkflow(
            root=self.app.root,
            service=service,
            runner=self._task_runner(),
            options=ManagedModelWorkflowOptions(
                title=TITLE_MANAGE_MODELS,
                select_local_title="Select SAM2 Model File",
                unavailable_message="Model runtime service is unavailable.",
                empty_catalog_message="No model catalog entries are available in checkpoints_catalog.json.",
                review_only_label="Review-only" if required else None,
                on_review_only=(lambda: self._set_review_only("User selected review-only mode from model manager."))
                if required
                else None,
                on_center_window=self._center,
            ),
            get_current_managed_id=self._current_managed_id,
            on_log_info=self.app._log_info,
            on_log_error=self.app._log_error,
            activate_managed=self._activate_managed_descriptor,
            activate_local=self._activate_local_path,
            prompt_select_local=lambda parent, title: self._prompt_select_local_file(parent=parent, title=title),
        )
        result = workflow.open_dialog(required=required)
        if required and not bool(result.get("ok")) and not bool(self.app._model_setup_disabled):
            if not list(service.load_catalog()):
                self._set_review_only("Model catalog is unavailable; model tools are disabled.")
        result["ready"] = bool(self.app._model_setup_ready)
        result["disabled"] = bool(self.app._model_setup_disabled)
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

    def _current_managed_id(self) -> str | None:
        current_token = str(getattr(self.app, "_active_model_token", "") or "").strip()
        if not current_token.startswith("managed://"):
            return None
        return str(current_token).split("managed://", 1)[-1].strip() or None

    def _task_runner(self) -> BackgroundTaskRunner:
        runner = getattr(self.app, "_background_task_runner", None)
        if isinstance(runner, BackgroundTaskRunner):
            return runner
        runner = BackgroundTaskRunner(self.app.root)
        self.app._background_task_runner = runner
        return runner

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
