from __future__ import annotations

from pathlib import Path
from tkinter import messagebox

import numpy as np

from sdapp.shared.services import MetricsSettingsResolver


class AnalysisWindowController:
    def __init__(self, app) -> None:
        self.app = app

    def collect_current_metrics_settings(self) -> dict[str, object]:
        metrics: dict[str, object] = {}
        try:
            frames_per_sec = float(self.app.frames_per_sec_var.get())
            if frames_per_sec > 0:
                metrics["frames_per_sec"] = float(frames_per_sec)
        except Exception:
            pass
        try:
            if self.app.scale_px_per_mm is not None and float(self.app.scale_px_per_mm) > 0:
                metrics["scale_px_per_mm"] = float(self.app.scale_px_per_mm)
        except Exception:
            pass
        if isinstance(self.app.roi_points, list) and self.app.roi_points:
            clean_points: list[list[float]] = []
            for pt in self.app.roi_points:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    try:
                        clean_points.append([float(pt[0]), float(pt[1])])
                    except (TypeError, ValueError):
                        continue
            if clean_points:
                metrics["roi_points"] = clean_points
        if self.app.roi_mask is not None:
            try:
                roi_mask = np.asarray(self.app.roi_mask, dtype=bool)
                if roi_mask.ndim == 2:
                    metrics["roi_mask"] = roi_mask.copy()
            except Exception:
                pass
        return dict(MetricsSettingsResolver.normalize(metrics))

    def apply_host_metrics_settings(self, metrics_settings: dict | None) -> None:
        normalized = MetricsSettingsResolver.normalize(metrics_settings if isinstance(metrics_settings, dict) else None)
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
                except (TypeError, ValueError):
                    pass
            if "roi_points" in normalized and isinstance(normalized.get("roi_points"), list):
                cleaned_points: list[list[float]] = []
                for pt in list(normalized.get("roi_points", [])):
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        try:
                            cleaned_points.append([float(pt[0]), float(pt[1])])
                        except (TypeError, ValueError):
                            continue
                self.app.roi_points = cleaned_points
            if "roi_mask" in normalized and normalized.get("roi_mask") is not None:
                try:
                    roi_mask = np.asarray(normalized.get("roi_mask"), dtype=bool)
                    if roi_mask.ndim == 2:
                        self.app.roi_mask = roi_mask.copy()
                except Exception:
                    pass
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

    def on_metrics_settings_changed(self, reason: str) -> None:
        self.app._mark_project_dirty(reason=str(reason or "metrics_changed"))
        self.emit_host_metrics_update(reason=str(reason or "metrics_changed"))

    def on_frames_per_sec_commit(self, _event=None):
        self.app._mark_project_dirty(reason="frames_per_sec")
        self.emit_host_metrics_update(reason="frames_per_sec")
        return None

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
            self.app.current_project_path = str(Path(host_path).expanduser().resolve())

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
            messagebox.showinfo("Masks Saved", f"Current masks were saved to:\n{name}")
            return
        messagebox.showinfo("Masks Saved", "Current masks were saved.")

    def save_current_masks(self) -> None:
        if not self.app._collect_nonempty_final_mask_frames():
            messagebox.showwarning("No Masks", "Please generate masks first.")
            return
        self.emit_host_metrics_update(reason="save_current_masks")
        self.sync_project_path_from_host()
        if not self.app.current_project_path:
            self.app.log_info("Project", "No host project is active. Prompting Save Project As for mask save.")
            try:
                self.app.save_project_as()
            except RuntimeError as exc:
                self.app.log_error("Project", f"Save current masks failed: {exc}")
                messagebox.showerror("Save Current Masks", str(exc))
                return
            if self.app.current_project_path and not bool(getattr(self.app, "project_dirty", False)):
                self.mark_active_event_saved_masks_present()
                self.show_masks_saved_popup()
            return
        if self.event_has_saved_masks_in_project():
            overwrite = messagebox.askyesno(
                "Overwrite Existing Masks?",
                "Masks already exist for this SD event. Saving will overwrite the stored masks in this project.\n\nContinue?",
            )
            if not overwrite:
                self.app.log_info("Project", "Save current masks canceled by user (overwrite declined).")
                return
        try:
            self.app.save_project()
        except RuntimeError as exc:
            self.app.log_error("Project", f"Save current masks failed: {exc}")
            messagebox.showerror("Save Current Masks", str(exc))
            return
        if self.app.current_project_path and not bool(getattr(self.app, "project_dirty", False)):
            self.mark_active_event_saved_masks_present()
            self.show_masks_saved_popup()
