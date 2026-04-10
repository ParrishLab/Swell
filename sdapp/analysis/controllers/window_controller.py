from __future__ import annotations

from pathlib import Path
from tkinter import messagebox

import numpy as np

from sdapp.shared.services import MetricsSettingsResolver


class AnalysisWindowController:
    def __init__(self, app) -> None:
        self.app = app

    def _dialog_parent(self):
        return getattr(self.app, "root", None)

    def collect_current_metrics_settings(self) -> dict[str, object]:
        metrics: dict[str, object] = {}
        try:
            frames_per_sec = float(self.app.frames_per_sec_var.get())
            if frames_per_sec > 0:
                metrics["frames_per_sec"] = float(frames_per_sec)
        except Exception:
            pass
        try:
            if bool(getattr(self.app, "_scale_is_local_override", False)) and self.app.scale_px_per_mm is not None and float(self.app.scale_px_per_mm) > 0:
                metrics["scale_px_per_mm"] = float(self.app.scale_px_per_mm)
        except Exception:
            pass
        if bool(getattr(self.app, "_scale_is_local_override", False)) and isinstance(getattr(self.app, "scale_points", None), list):
            clean_scale_points: list[list[float]] = []
            for pt in list(self.app.scale_points)[:2]:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    try:
                        clean_scale_points.append([float(pt[0]), float(pt[1])])
                    except (TypeError, ValueError):
                        continue
            if len(clean_scale_points) == 2:
                metrics["scale_points"] = clean_scale_points
        if bool(getattr(self.app, "_scale_is_local_override", False)):
            metrics["scale_axis_lock"] = bool(getattr(self.app, "scale_axis_lock", True))
        if bool(getattr(self.app, "_scale_is_local_override", False)):
            scale_image_path = str(getattr(self.app, "_last_scale_image_path", "") or "").strip()
            if scale_image_path:
                metrics["scale_image_path"] = scale_image_path
        if bool(getattr(self.app, "_roi_is_local_override", False)) and isinstance(self.app.roi_points, list) and self.app.roi_points:
            clean_points: list[list[float]] = []
            for pt in self.app.roi_points:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    try:
                        clean_points.append([float(pt[0]), float(pt[1])])
                    except (TypeError, ValueError):
                        continue
            if clean_points:
                metrics["roi_points"] = clean_points
        if bool(getattr(self.app, "_roi_is_local_override", False)) and self.app.roi_mask is not None:
            try:
                roi_mask = np.asarray(self.app.roi_mask, dtype=bool)
                if roi_mask.ndim == 2:
                    metrics["roi_mask"] = roi_mask.copy()
            except Exception:
                pass
        return dict(MetricsSettingsResolver.normalize(metrics))

    def apply_host_metrics_settings(
        self,
        metrics_settings: dict | None,
        local_metrics_settings: dict | None = None,
        *_ignored_args,
        **_ignored_kwargs,
    ) -> None:
        normalized = MetricsSettingsResolver.normalize(metrics_settings if isinstance(metrics_settings, dict) else None)
        local_normalized = MetricsSettingsResolver.normalize(
            local_metrics_settings if isinstance(local_metrics_settings, dict) else None
        )
        self.app._scale_is_local_override = MetricsSettingsResolver.has_valid_scale(local_normalized)
        self.app._roi_is_local_override = MetricsSettingsResolver.has_valid_roi(local_normalized)
        if not normalized:
            return
        self.app._suppress_metrics_emit = True
        try:
            if "frames_per_sec" in normalized:
                try:
                    frames_per_sec = float(normalized.get("frames_per_sec"))
                    if frames_per_sec > 0 and hasattr(self.app, "frames_per_sec_var"):
                        self.app.frames_per_sec_var.set(float(frames_per_sec))
                except (TypeError, ValueError):
                    pass
            if "scale_px_per_mm" in normalized:
                try:
                    scale_value = float(normalized.get("scale_px_per_mm"))
                    if scale_value > 0:
                        self.app.scale_px_per_mm = float(scale_value)
                    else:
                        self.app.scale_px_per_mm = None
                except (TypeError, ValueError):
                    self.app.scale_px_per_mm = None
            if "scale_points" in normalized and isinstance(normalized.get("scale_points"), list):
                cleaned_scale_points: list[list[float]] = []
                for pt in list(normalized.get("scale_points", []))[:2]:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        try:
                            cleaned_scale_points.append([float(pt[0]), float(pt[1])])
                        except (TypeError, ValueError):
                            continue
                self.app.scale_points = cleaned_scale_points if len(cleaned_scale_points) == 2 else []
            elif not self.app._scale_is_local_override:
                self.app.scale_points = []
            if "scale_axis_lock" in normalized:
                self.app.scale_axis_lock = bool(normalized.get("scale_axis_lock"))
            elif not self.app._scale_is_local_override:
                self.app.scale_axis_lock = True
            if "scale_image_path" in normalized:
                self.app._last_scale_image_path = str(normalized.get("scale_image_path", "") or "").strip()
            elif not self.app._scale_is_local_override:
                self.app._last_scale_image_path = ""
            if "roi_points" in normalized and isinstance(normalized.get("roi_points"), list):
                cleaned_points: list[list[float]] = []
                for pt in list(normalized.get("roi_points", [])):
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        try:
                            cleaned_points.append([float(pt[0]), float(pt[1])])
                        except (TypeError, ValueError):
                            continue
                self.app.roi_points = cleaned_points
            elif not self.app._roi_is_local_override:
                self.app.roi_points = []
            if "roi_mask" in normalized and normalized.get("roi_mask") is not None:
                try:
                    roi_mask = np.asarray(normalized.get("roi_mask"), dtype=bool)
                    if roi_mask.ndim == 2:
                        self.app.roi_mask = roi_mask.copy()
                except Exception:
                    pass
            elif not self.app._roi_is_local_override:
                self.app.roi_mask = None
        finally:
            self.app._suppress_metrics_emit = False
        if self.app._ui_alive():
            self.app.update_display()

    def emit_host_metrics_update(self, reason: str) -> dict[str, object] | None:
        if bool(getattr(self.app, "_suppress_metrics_emit", False)):
            return None
        if not bool(getattr(self.app, "_host_mode", False)):
            return None
        updater = getattr(self.app, "_host_metrics_updater", None)
        if not callable(updater):
            return None
        event_id = str(getattr(self.app, "active_event_id", "") or "")
        if not event_id:
            return None
        payload = {
            "event_id": event_id,
            "metrics_settings": self.collect_current_metrics_settings(),
            "reason": str(reason or ""),
        }
        try:
            result = updater(payload)
        except Exception as exc:
            self.app.log_warn("HostSync", f"Direct host update failed: {exc}")
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": str(exc)}
        if isinstance(result, dict) and not bool(result.get("ok", False)):
            code = str(result.get("code", "PAYLOAD_INVALID"))
            message = str(result.get("message", "Host rejected metrics update."))
            self.app.log_warn("HostSync", f"Host rejected metrics update [{code}]: {message}")
        return result if isinstance(result, dict) else {"ok": True}

    def emit_host_global_metrics_update(self, reason: str, metrics_settings: dict[str, object]) -> dict[str, object] | None:
        if bool(getattr(self.app, "_suppress_metrics_emit", False)):
            return None
        if not bool(getattr(self.app, "_host_mode", False)):
            return {"ok": True, "changed": False}
        updater = getattr(self.app, "_host_global_metrics_updater", None)
        if not callable(updater):
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": "Host global metrics updater is unavailable."}
        payload = {
            "metrics_settings": dict(MetricsSettingsResolver.normalize(metrics_settings)),
            "reason": str(reason or ""),
        }
        try:
            result = updater(payload)
        except Exception as exc:
            self.app.log_warn("HostSync", f"Direct host global metrics update failed: {exc}")
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": str(exc)}
        if isinstance(result, dict) and not bool(result.get("ok", False)):
            code = str(result.get("code", "PAYLOAD_INVALID"))
            message = str(result.get("message", "Host rejected global metrics update."))
            self.app.log_warn("HostSync", f"Host rejected global metrics update [{code}]: {message}")
        return result if isinstance(result, dict) else {"ok": True}

    def clear_local_metrics_override(self, reason: str, keys: list[str]) -> dict[str, object] | None:
        if bool(getattr(self.app, "_suppress_metrics_emit", False)):
            return None
        if not bool(getattr(self.app, "_host_mode", False)):
            return {"ok": True, "changed": False}
        updater = getattr(self.app, "_host_metrics_updater", None)
        if not callable(updater):
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": "Host metrics updater is unavailable."}
        event_id = str(getattr(self.app, "active_event_id", "") or "")
        if not event_id:
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": "No active event is selected."}
        payload = {
            "event_id": event_id,
            "metrics_settings": {},
            "clear_local_metric_keys": [str(key) for key in list(keys or []) if str(key).strip()],
            "reason": str(reason or ""),
        }
        try:
            result = updater(payload)
        except Exception as exc:
            self.app.log_warn("HostSync", f"Direct host metric-reset failed: {exc}")
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": str(exc)}
        if isinstance(result, dict) and not bool(result.get("ok", False)):
            code = str(result.get("code", "PAYLOAD_INVALID"))
            message = str(result.get("message", "Host rejected metric reset."))
            self.app.log_warn("HostSync", f"Host rejected metric reset [{code}]: {message}")
        return result if isinstance(result, dict) else {"ok": True}

    def on_metrics_settings_changed(self, reason: str) -> None:
        self.app._mark_project_dirty(reason=str(reason or "metrics_changed"))
        self.emit_host_metrics_update(reason=str(reason or "metrics_changed"))

    def on_frames_per_sec_commit(self, _event=None):
        self.app._mark_project_dirty(reason="frames_per_sec")
        self.emit_host_metrics_update(reason="frames_per_sec")
        return None

    def autosave_project_after_metrics_commit(self, reason: str) -> dict[str, object]:
        if not bool(getattr(self.app, "_host_mode", False)):
            return {"ok": True, "autosaved": False}
        self.sync_project_path_from_host()
        try:
            self.app.save_project()
        except Exception as exc:
            return {
                "ok": False,
                "code": "SAVE_FAILED",
                "message": f"Project change was applied, but autosave failed: {exc}",
            }
        current_project_path = str(getattr(self.app, "current_project_path", "") or "").strip()
        if not current_project_path or bool(getattr(self.app, "project_dirty", False)):
            return {
                "ok": False,
                "code": "SAVE_INCOMPLETE",
                "message": "Project change was applied, but autosave did not complete.",
            }
        return {"ok": True, "autosaved": True, "project_path": current_project_path, "reason": str(reason or "")}

    def sync_project_path_from_host(self) -> None:
        if not bool(getattr(self.app, "_host_mode", False)):
            return
        provider = getattr(self.app, "_host_project_path_provider", None)
        if not callable(provider):
            return
        try:
            host_path = provider()
        except Exception:
            host_path = None
        if isinstance(host_path, str) and host_path.strip():
            try:
                self.app.current_project_path = str(Path(host_path).expanduser().resolve())
            except Exception as exc:
                logger = getattr(self.app, "log_warn", None)
                if callable(logger):
                    logger("Project", f"Ignoring invalid host project path {host_path!r}: {exc}")

    def analysis_payload_has_saved_masks(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        masks_committed = payload.get("masks_committed")
        if masks_committed is not None:
            if isinstance(masks_committed, dict):
                for mask in masks_committed.values():
                    if mask is not None and np.any(np.asarray(mask)):
                        return True
            else:
                arr = np.asarray(masks_committed)
                if arr.size > 0 and np.any(arr):
                    return True
        masks_draft = payload.get("masks_draft")
        if masks_draft is not None:
            if isinstance(masks_draft, dict):
                for mask in masks_draft.values():
                    if mask is not None and np.any(np.asarray(mask)):
                        return True
            else:
                arr = np.asarray(masks_draft)
                if arr.size > 0 and np.any(arr):
                    return True
        return False

    def event_has_saved_masks_in_project(self) -> bool:
        event_id = str(getattr(self.app, "active_event_id", "") or "")
        if not event_id:
            return False
        return bool(dict(getattr(self.app, "_saved_project_masks_by_event", {}) or {}).get(event_id, False))

    def mark_active_event_saved_masks_present(self) -> None:
        event_id = str(getattr(self.app, "active_event_id", "") or "")
        if event_id:
            if not isinstance(getattr(self.app, "_saved_project_masks_by_event", None), dict):
                self.app._saved_project_masks_by_event = {}
            self.app._saved_project_masks_by_event[str(event_id)] = True

    def show_masks_saved_popup(self) -> None:
        target = str(getattr(self.app, "current_project_path", "") or "").strip()
        if target:
            name = Path(target).name
            messagebox.showinfo("Masks Saved", f"Current masks were saved to:\n{name}", parent=self._dialog_parent())
            return
        messagebox.showinfo("Masks Saved", "Current masks were saved.", parent=self._dialog_parent())

    def _has_masks_ready_to_save(self) -> bool:
        seg_state = getattr(self.app, "seg_state", None)
        invalidate = getattr(seg_state, "invalidate_final_mask_frames", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                pass

        if seg_state is not None:
            try:
                for mask in dict(getattr(seg_state, "masks_cache", {}) or {}).values():
                    if mask is not None and np.any(np.asarray(mask)):
                        return True
            except Exception:
                pass
            try:
                for layer in dict(getattr(seg_state, "paint_layers", {}) or {}).values():
                    if not isinstance(layer, dict):
                        continue
                    plus = layer.get("plus")
                    minus = layer.get("minus")
                    if (plus is not None and np.any(np.asarray(plus))) or (minus is not None and np.any(np.asarray(minus))):
                        return True
            except Exception:
                pass

        try:
            if bool(self.app._collect_nonempty_final_mask_frames()):
                return True
        except Exception:
            pass

        workspace = getattr(self.app, "analysis_workspace", None)
        export_payload = getattr(workspace, "export_active_event_analysis_payload", None)
        if callable(export_payload):
            try:
                payload = export_payload()
                if self.analysis_payload_has_saved_masks(payload):
                    return True
            except Exception:
                pass
        return False

    def save_current_masks(self) -> None:
        if not self._has_masks_ready_to_save():
            messagebox.showwarning("No Masks", "Please generate masks first.", parent=self._dialog_parent())
            return
        if bool(getattr(self.app, "_host_mode", False)):
            try:
                self.app._emit_host_sync("save_current_masks")
            except Exception as exc:
                self.app.log_error("Project", f"Save current masks failed during host sync: {exc}")
                messagebox.showerror("Save Current Masks", str(exc), parent=self._dialog_parent())
                return
        self.emit_host_metrics_update(reason="save_current_masks")
        self.sync_project_path_from_host()
        if not self.app.current_project_path:
            self.app.log_info("Project", "No host project is active. Prompting Save Project As for mask save.")
            try:
                self.app.save_project_as()
            except Exception as exc:
                self.app.log_error("Project", f"Save current masks failed: {exc}")
                messagebox.showerror("Save Current Masks", str(exc), parent=self._dialog_parent())
                return
            if self.app.current_project_path and not bool(getattr(self.app, "project_dirty", False)):
                self.mark_active_event_saved_masks_present()
                self.show_masks_saved_popup()
            return
        if self.event_has_saved_masks_in_project():
            overwrite = messagebox.askyesno(
                "Overwrite Existing Masks?",
                "Masks already exist for this SD event. Saving will overwrite the stored masks in this project.\n\nContinue?",
                parent=self._dialog_parent(),
            )
            if not overwrite:
                self.app.log_info("Project", "Save current masks canceled by user (overwrite declined).")
                return
        try:
            self.app.save_project()
        except Exception as exc:
            self.app.log_error("Project", f"Save current masks failed: {exc}")
            messagebox.showerror("Save Current Masks", str(exc), parent=self._dialog_parent())
            return
        if self.app.current_project_path and not bool(getattr(self.app, "project_dirty", False)):
            self.mark_active_event_saved_masks_present()
            self.show_masks_saved_popup()
