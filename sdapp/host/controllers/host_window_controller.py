from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from sdapp.analysis.core.metrics import compute_scale
from sdapp.analysis.ui.roi_dialog import open_roi_dialog
from sdapp.analysis.ui.scale_dialog import open_scale_dialog
from sdapp.host.exporter import analysis_image_cache_key, export_analysis
from sdapp.shared.services import MetricsSettingsResolver


class HostWindowController:
    def __init__(self, app) -> None:
        self.app = app

    def _global_metrics_defaults_state(self) -> tuple[float, float | None, list[list[float]], list[list[float]], np.ndarray | None]:
        defaults = dict(self.app.browser_controller.get_global_metrics_defaults() or {})
        fps_initial = defaults.get("frames_per_sec", 1.0)
        try:
            fps_initial = float(fps_initial)
            if fps_initial <= 0:
                fps_initial = 1.0
        except (TypeError, ValueError):
            fps_initial = 1.0

        scale_value = defaults.get("scale_px_per_mm")
        try:
            scale_value = float(scale_value) if scale_value is not None else None
            if scale_value is not None and scale_value <= 0:
                scale_value = None
        except (TypeError, ValueError):
            scale_value = None
        scale_points = list(defaults.get("scale_points", [])) if isinstance(defaults.get("scale_points"), list) else []
        roi_points = list(defaults.get("roi_points", [])) if isinstance(defaults.get("roi_points"), list) else []
        roi_mask = defaults.get("roi_mask")
        if roi_mask is not None:
            try:
                roi_mask = np.asarray(roi_mask, dtype=bool).copy()
                if roi_mask.ndim != 2:
                    roi_mask = None
            except Exception:
                roi_mask = None
        return float(fps_initial), scale_value, scale_points, roi_points, roi_mask

    def refresh_open_metrics_popup(self) -> None:
        dialog = getattr(self.app, "_open_metrics_dialog", None)
        refresher = getattr(self.app, "_refresh_open_metrics_dialog", None)
        if dialog is None or refresher is None:
            return
        try:
            if not bool(dialog.winfo_exists()):
                return
        except Exception:
            return
        if callable(refresher):
            refresher()

    def has_binary_masks_for_events(self, event_ids: list[str]) -> bool:
        try:
            sidecar = dict(self.app.browser_controller.session.state().analysis_sidecar or {})
        except Exception:
            return False
        for event_id in [str(v) for v in event_ids]:
            payload = sidecar.get(event_id)
            if not isinstance(payload, dict):
                continue
            masks = payload.get("masks_committed")
            if masks is None:
                continue
            if isinstance(masks, dict):
                for mask in masks.values():
                    arr = np.asarray(mask, dtype=bool)
                    if arr.ndim == 2 and np.any(arr):
                        return True
                continue
            arr = np.asarray(masks)
            if arr.ndim == 3 and arr.size > 0 and np.any(arr):
                return True
        return False

    @staticmethod
    def _has_valid_scale(metrics_settings: dict) -> bool:
        return MetricsSettingsResolver.has_valid_scale(metrics_settings)

    @staticmethod
    def _has_valid_roi(metrics_settings: dict) -> bool:
        return MetricsSettingsResolver.has_valid_roi(metrics_settings)

    def resolve_export_metric_prerequisites(self, event_ids: list[str]) -> dict[str, dict[str, object]]:
        return MetricsSettingsResolver.prerequisites_for_events(
            event_ids=list(event_ids or []),
            metrics_loader=lambda event_id: self.app.browser_controller.resolve_event_metrics_settings(event_id),
        )

    def _analysis_image_export_cache(self) -> OrderedDict:
        cache = getattr(self.app, "_analysis_image_export_cache", None)
        if isinstance(cache, OrderedDict):
            return cache
        cache = OrderedDict()
        self.app._analysis_image_export_cache = cache
        return cache

    def _cache_analysis_image_stack(self, key: tuple, frames_viz: np.ndarray) -> None:
        cache = self._analysis_image_export_cache()
        cache[key] = np.asarray(frames_viz, dtype=np.uint8)
        cache.move_to_end(key)
        while len(cache) > 4:
            cache.popitem(last=False)

    def _seed_analysis_image_export_cache(self, export_events: list[object], baseline_pre_frames: int) -> OrderedDict:
        cache = self._analysis_image_export_cache()
        by_event_id = {str(getattr(event, "event_id", "")): event for event in list(export_events or [])}
        for event_id, event in by_event_id.items():
            ref = self.app.analysis_window_manager.get("__project__", event_id)
            if ref is None:
                continue
            analysis_app = getattr(ref, "app", None)
            frames_viz = getattr(analysis_app, "frames_sub_viz", None)
            try:
                frame_count = len(frames_viz) if frames_viz is not None else 0
            except Exception:
                frame_count = 0
            if frame_count <= 0:
                continue
            try:
                stack = np.asarray([np.asarray(frames_viz[idx], dtype=np.uint8).copy() for idx in range(frame_count)], dtype=np.uint8)
            except Exception:
                continue
            cache_key = analysis_image_cache_key(event, default_baseline_pre_frames=int(baseline_pre_frames))
            self._cache_analysis_image_stack(cache_key, stack)
        return cache

    @staticmethod
    def attach_disabled_tooltip(parent, widget, message: str) -> None:
        tip = tk.Toplevel(parent)
        tip.withdraw()
        tip.overrideredirect(True)
        tip_label = ttk.Label(tip, text=str(message), padding=6, relief="solid")
        tip_label.pack()

        def _show_tip(event) -> None:
            x = int(event.x_root) + 10
            y = int(event.y_root) + 10
            tip.geometry(f"+{x}+{y}")
            tip.deiconify()
            tip.lift()

        def _hide_tip(_event=None) -> None:
            tip.withdraw()

        widget.bind("<Enter>", _show_tip)
        widget.bind("<Leave>", _hide_tip)
        widget.bind("<Destroy>", lambda _e: tip.destroy())

    def prompt_export_options(self, event_ids: list[str]) -> dict[str, bool] | None:
        dialog = tk.Toplevel(self.app.root)
        dialog.title("Export Options")
        dialog.transient(self.app.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.geometry("+%d+%d" % (self.app.root.winfo_rootx() + 120, self.app.root.winfo_rooty() + 120))

        include_event_var = tk.BooleanVar(value=True)
        include_baseline_var = tk.BooleanVar(value=True)
        include_analysis_var = tk.BooleanVar(value=False)
        include_masks_var = tk.BooleanVar(value=True)
        include_mask_overlay_var = tk.BooleanVar(value=True)
        include_metric_speed_var = tk.BooleanVar(value=True)
        include_metric_area_var = tk.BooleanVar(value=True)
        include_metric_rel_area_var = tk.BooleanVar(value=True)
        output_dir_var = tk.StringVar(value=self.app.output_var.get().strip())
        result: dict[str, str | bool] | None = None
        has_masks = self.has_binary_masks_for_events(event_ids)
        metric_ready = self.resolve_export_metric_prerequisites(event_ids)

        shell = ttk.Frame(dialog, padding=12)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text=f"Choose export items for {len(event_ids)} event(s):").pack(anchor="w")

        output_row = ttk.Frame(shell)
        output_row.pack(fill="x", pady=(6, 10))
        ttk.Label(output_row, text="Output Folder").pack(side="left")
        output_entry = ttk.Entry(output_row, textvariable=output_dir_var)
        output_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))

        def _browse_output_dir() -> None:
            initial = output_dir_var.get().strip() or self.app.output_var.get().strip() or str(Path.cwd())
            folder = filedialog.askdirectory(parent=dialog, title="Select Export Folder", initialdir=initial)
            if folder:
                output_dir_var.set(str(folder))

        ttk.Button(output_row, text="Browse...", command=_browse_output_dir).pack(side="left")

        checks = ttk.Frame(shell)
        checks.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(checks, text="Event Images", variable=include_event_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="Baseline Images", variable=include_baseline_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="Analysis Images", variable=include_analysis_var).pack(anchor="w")
        masks_check = ttk.Checkbutton(checks, text="Binary Masks", variable=include_masks_var)
        masks_check.pack(anchor="w")
        overlay_check = ttk.Checkbutton(checks, text="Mask Overlay Images", variable=include_mask_overlay_var)
        overlay_check.pack(anchor="w")
        if not has_masks:
            include_masks_var.set(False)
            masks_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, masks_check, "No binary masks exist for the selected events.")
            include_mask_overlay_var.set(False)
            overlay_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, overlay_check, "No binary masks exist for the selected events.")

        ttk.Separator(checks, orient="horizontal").pack(fill="x", pady=(6, 4))
        ttk.Label(checks, text="Metrics").pack(anchor="w")
        metric_speed_check = ttk.Checkbutton(checks, text="Propagation Speed", variable=include_metric_speed_var)
        metric_speed_check.pack(anchor="w")
        metric_area_check = ttk.Checkbutton(checks, text="Area Recruited", variable=include_metric_area_var)
        metric_area_check.pack(anchor="w")
        metric_rel_area_check = ttk.Checkbutton(
            checks, text="Relative Area Recruited", variable=include_metric_rel_area_var
        )
        metric_rel_area_check.pack(anchor="w")

        if not bool(metric_ready["propagation_speed"]["enabled"]):
            include_metric_speed_var.set(False)
            metric_speed_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, metric_speed_check, str(metric_ready["propagation_speed"]["reason"]))
        if not bool(metric_ready["area_recruited"]["enabled"]):
            include_metric_area_var.set(False)
            metric_area_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, metric_area_check, str(metric_ready["area_recruited"]["reason"]))
        if not bool(metric_ready["relative_area_recruited"]["enabled"]):
            include_metric_rel_area_var.set(False)
            metric_rel_area_check.configure(state="disabled")
            self.attach_disabled_tooltip(
                dialog,
                metric_rel_area_check,
                str(metric_ready["relative_area_recruited"]["reason"]),
            )

        buttons = ttk.Frame(shell)
        buttons.pack(fill="x")

        def _cancel() -> None:
            dialog.destroy()

        def _confirm() -> None:
            nonlocal result
            include_any = (
                bool(include_event_var.get())
                or bool(include_baseline_var.get())
                or bool(include_analysis_var.get())
                or bool(include_masks_var.get())
                or bool(include_mask_overlay_var.get())
                or bool(include_metric_speed_var.get())
                or bool(include_metric_area_var.get())
                or bool(include_metric_rel_area_var.get())
            )
            if not include_any:
                messagebox.showwarning("Export Options", "Select at least one export target.", parent=dialog)
                return
            out = output_dir_var.get().strip()
            if not out:
                messagebox.showwarning("Export Options", "Select an output folder.", parent=dialog)
                return
            result = {
                "output_dir": out,
                "include_event_images": bool(include_event_var.get()),
                "include_baseline_images": bool(include_baseline_var.get()),
                "include_analysis_images": bool(include_analysis_var.get()),
                "include_binary_masks": bool(include_masks_var.get()),
                "include_mask_overlay_images": bool(include_mask_overlay_var.get()),
                "include_metric_propagation_speed": bool(include_metric_speed_var.get()),
                "include_metric_area_recruited": bool(include_metric_area_var.get()),
                "include_metric_relative_area_recruited": bool(include_metric_rel_area_var.get()),
            }
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(buttons, text="Export", command=_confirm).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        dialog.wait_window()
        return result

    def prompt_propagation_gap_action(self, payload: dict[str, object]) -> str:
        result = {"action": "ignore"}
        dialog = tk.Toplevel(self.app.root)
        dialog.title("Propagation Speed Warning")
        dialog.transient(self.app.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.geometry("+%d+%d" % (self.app.root.winfo_rootx() + 140, self.app.root.winfo_rooty() + 140))

        shell = ttk.Frame(dialog, padding=12)
        shell.pack(fill="both", expand=True)
        event_id = str(payload.get("event_id", "") or "")
        runs = list(payload.get("gap_frame_runs", []) or [])
        run_labels = ", ".join(
            f"{int(run[0])}" if int(run[0]) == int(run[1]) else f"{int(run[0])}-{int(run[1])}"
            for run in runs
            if isinstance(run, (list, tuple)) and len(run) >= 2
        )
        ttk.Label(
            shell,
            text=(
                f"Propagation speed gaps were detected for {event_id or 'the current event'}.\n"
                f"Frames: {run_labels or 'unknown'}"
            ),
            justify="left",
        ).pack(anchor="w")
        ttk.Label(
            shell,
            text="Choose how export should handle those propagation-speed gaps for this export run.",
            justify="left",
        ).pack(anchor="w", pady=(8, 10))

        def _finish(action: str) -> None:
            result["action"] = str(action)
            dialog.destroy()

        buttons = ttk.Frame(shell)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Ignore", command=lambda: _finish("ignore")).pack(side="left")
        ttk.Button(buttons, text="Stop There", command=lambda: _finish("stop")).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Average Between Frames", command=lambda: _finish("interpolate")).pack(
            side="left", padx=(8, 0)
        )
        dialog.protocol("WM_DELETE_WINDOW", lambda: _finish("ignore"))
        self.center_window_on_screen(dialog)
        dialog.wait_window()
        return str(result["action"])

    @staticmethod
    def center_window_on_screen(window) -> None:
        try:
            window.update_idletasks()
            width = int(window.winfo_width())
            height = int(window.winfo_height())
            if width <= 1:
                width = int(window.winfo_reqwidth())
            if height <= 1:
                height = int(window.winfo_reqheight())
            width = max(1, width)
            height = max(1, height)
            x = max(0, int((int(window.winfo_screenwidth()) - width) / 2))
            y = max(0, int((int(window.winfo_screenheight()) - height) / 2))
            window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            return

    def open_generate_metrics_popup(self) -> None:
        if self.app.reader is None or self.app.stack_info is None:
            self.app._show_warning("Open Metrics", "Load a stack first.")
            return
        existing = getattr(self.app, "_open_metrics_dialog", None)
        try:
            if existing is not None and bool(existing.winfo_exists()):
                self.refresh_open_metrics_popup()
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass

        fps_initial, scale_value, scale_points, roi_points, roi_mask = self._global_metrics_defaults_state()

        dialog = tk.Toplevel(self.app.root)
        dialog.title("Open Metrics")
        dialog.transient(self.app.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        self.app._open_metrics_dialog = dialog

        shell = ttk.Frame(dialog, padding=12)
        shell.pack(fill="both", expand=True)
        ttk.Label(
            shell,
            text="Configure global Frames/sec, Scale, and ROI defaults for this project.",
        ).pack(anchor="w")

        fps_row = ttk.Frame(shell)
        fps_row.pack(fill="x", pady=(10, 6))
        ttk.Label(fps_row, text="Frames/sec").pack(side="left")
        fps_var = tk.StringVar(value=f"{fps_initial:.6g}")
        ttk.Entry(fps_row, textvariable=fps_var, width=10).pack(side="left", padx=(8, 0))

        scale_status_var = tk.StringVar()
        roi_status_var = tk.StringVar()

        def _refresh_labels() -> None:
            if scale_value is None:
                scale_status_var.set("Scale: Not set")
            else:
                scale_status_var.set(f"Scale: {float(scale_value):.6g} px/mm")
            if roi_mask is not None:
                roi_status_var.set(f"ROI: {len(roi_points)} points ({int(np.count_nonzero(roi_mask))} px)")
            elif roi_points:
                roi_status_var.set(f"ROI: {len(roi_points)} points")
            else:
                roi_status_var.set("ROI: Not set")

        def _refresh_from_host() -> None:
            nonlocal scale_value, scale_points, roi_points, roi_mask
            _fps_value, scale_value, scale_points, roi_points, roi_mask = self._global_metrics_defaults_state()
            _refresh_labels()

        self.app._refresh_open_metrics_dialog = _refresh_from_host

        controls = ttk.Frame(shell)
        controls.pack(fill="x", pady=(6, 6))

        def _set_scale() -> None:
            nonlocal scale_value, scale_points
            img_u8 = self.app._pick_metrics_reference_image_u8(parent=dialog, purpose="Scale")
            if img_u8 is None:
                return
            result = open_scale_dialog(
                root=dialog,
                img_u8=img_u8,
                snap_scale_points_axis=self.app._snap_scale_points_axis,
                refine_scale_bar_points=self.app._refine_scale_bar_points,
                compute_scale=compute_scale,
                initial_scale_points=scale_points,
            )
            if not isinstance(result, dict):
                return
            try:
                scale_value = float(result.get("px_per_mm"))
                if scale_value <= 0:
                    scale_value = None
            except (TypeError, ValueError):
                scale_value = None
            scale_points = [
                [float(pt[0]), float(pt[1])]
                for pt in list(result.get("scale_points", []))[:2]
                if isinstance(pt, (list, tuple)) and len(pt) >= 2
            ]
            _refresh_labels()

        def _set_roi() -> None:
            nonlocal roi_points, roi_mask
            img_u8 = self.app._pick_metrics_reference_image_u8(parent=dialog, purpose="ROI")
            if img_u8 is None:
                return
            result = open_roi_dialog(
                root=dialog,
                img_u8=img_u8,
                initial_roi_points=list(roi_points),
            )
            if not isinstance(result, dict):
                return
            roi_points = list(result.get("roi_points", []))
            raw_mask = result.get("roi_mask")
            if raw_mask is None:
                roi_mask = None
            else:
                try:
                    roi_mask = np.asarray(raw_mask, dtype=bool).copy()
                    if roi_mask.ndim != 2:
                        roi_mask = None
                except Exception:
                    roi_mask = None
            _refresh_labels()

        ttk.Button(controls, text="Set Scale", command=_set_scale).pack(side="left")
        ttk.Button(controls, text="Draw ROI", command=_set_roi).pack(side="left", padx=(8, 0))

        ttk.Label(shell, textvariable=scale_status_var).pack(anchor="w", pady=(2, 2))
        ttk.Label(shell, textvariable=roi_status_var).pack(anchor="w", pady=(0, 8))
        _refresh_labels()

        actions = ttk.Frame(shell)
        actions.pack(fill="x")

        def _cancel() -> None:
            dialog.destroy()

        def _apply() -> None:
            try:
                frames_per_sec = float(str(fps_var.get()).strip())
                if frames_per_sec <= 0:
                    raise ValueError("Frames/sec must be greater than zero.")
            except (TypeError, ValueError):
                self.app._show_warning("Open Metrics", "Frames/sec must be a positive number.")
                return

            payload: dict[str, object] = {"frames_per_sec": float(frames_per_sec)}
            if scale_value is not None:
                payload["scale_px_per_mm"] = float(scale_value)
            if len(scale_points) == 2:
                payload["scale_points"] = [[float(pt[0]), float(pt[1])] for pt in scale_points]
            if roi_points:
                payload["roi_points"] = [[float(pt[0]), float(pt[1])] for pt in roi_points]
            if roi_mask is not None:
                payload["roi_mask"] = np.asarray(roi_mask, dtype=bool).copy()

            self.app.browser_controller.set_global_metrics_defaults(payload)
            materialized = self.app.browser_controller.materialize_metrics_defaults_to_events()
            self.app._set_status("Global metrics defaults updated.")
            self.app._log_info(
                "Updated global metrics defaults and applied missing values to "
                f"{materialized} event(s)."
            )
            dialog.destroy()

        ttk.Button(actions, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(actions, text="Apply", command=_apply).pack(side="right", padx=(0, 8))

        def _on_destroy(_event=None) -> None:
            if getattr(self.app, "_open_metrics_dialog", None) is dialog:
                self.app._open_metrics_dialog = None
                self.app._refresh_open_metrics_dialog = None

        dialog.bind("<Destroy>", _on_destroy)
        self.center_window_on_screen(dialog)
        dialog.wait_window()

    def run_export(self, event_ids: list[str], *, options: dict[str, object]) -> None:
        if self.app.reader is None:
            self.app._log_warn("Export blocked: load a stack first.")
            messagebox.showwarning("Export", "Load a stack first.", parent=self.app.root)
            return

        output_dir = str(options.get("output_dir", self.app.output_var.get().strip())).strip()
        if not output_dir:
            self.app._log_warn("Export blocked: no output folder selected.")
            messagebox.showwarning("Export", "Select an output folder.", parent=self.app.root)
            return
        self.app.output_var.set(output_dir)

        baseline_pre = int(self.app.baseline_pre_frames)
        self.app._set_status("Exporting...")
        self.app._export_progress_bucket = -1
        self.app._last_export_analysis_prepare_key = None
        self.app._log_info(
            "Started export to "
            f"{output_dir} for {len(event_ids)} event(s), baseline_pre_frames={baseline_pre}, "
            f"event_images={bool(options.get('include_event_images'))}, "
            f"baseline_images={bool(options.get('include_baseline_images'))}, "
            f"analysis_images={bool(options.get('include_analysis_images'))}, "
            f"binary_masks={bool(options.get('include_binary_masks'))}, "
            f"mask_overlay_images={bool(options.get('include_mask_overlay_images'))}, "
            f"metric_propagation_speed={bool(options.get('include_metric_propagation_speed'))}, "
            f"metric_area_recruited={bool(options.get('include_metric_area_recruited'))}, "
            f"metric_relative_area_recruited={bool(options.get('include_metric_relative_area_recruited'))}."
        )
        gap_policy_cache: dict[str, str] = {}

        def worker() -> None:
            try:
                assert self.app.reader is not None
                export_events = self.app.browser_controller.export_candidates(event_ids)
                analysis_image_cache = None
                if bool(options.get("include_analysis_images")):
                    analysis_image_cache = self._seed_analysis_image_export_cache(export_events, baseline_pre)
                sidecar = self.app.browser_controller.session.state().analysis_sidecar
                metadata = self.app.browser_controller.session.state().metadata

                def _notify_progress(payload: dict) -> None:
                    if not hasattr(self.app, "root") or self.app.root is None:
                        self.app._on_export_progress(dict(payload or {}))
                        return
                    progress_payload = dict(payload or {})
                    self.app.root.after(0, lambda p=progress_payload: self.app._on_export_progress(p))

                def _resolve_gap_decision(payload: dict[str, object]) -> str:
                    cached = gap_policy_cache.get("action")
                    if cached:
                        return str(cached)
                    response: dict[str, str] = {"action": "ignore"}
                    wait_event = threading.Event()

                    def _ask() -> None:
                        try:
                            response["action"] = str(self.prompt_propagation_gap_action(dict(payload or {})) or "ignore")
                        finally:
                            wait_event.set()

                    self.app.root.after(0, _ask)
                    wait_event.wait()
                    action = str(response.get("action", "ignore") or "ignore")
                    gap_policy_cache["action"] = action
                    self.app._log_warn(
                        f"Propagation speed gap detected during export; applying action='{action}' for remaining exports."
                    )
                    return action

                result = export_analysis(
                    reader=self.app.reader,
                    events=export_events,
                    output_dir=output_dir,
                    baseline_pre_frames=baseline_pre,
                    trace=self.app.trace,
                    selected_event_ids=event_ids,
                    progress_callback=_notify_progress,
                    include_event_images=bool(options.get("include_event_images")),
                    include_baseline_images=bool(options.get("include_baseline_images")),
                    include_analysis_images=bool(options.get("include_analysis_images")),
                    include_binary_masks=bool(options.get("include_binary_masks")),
                    include_mask_overlay_images=bool(options.get("include_mask_overlay_images")),
                    analysis_sidecar=sidecar,
                    analysis_image_cache=analysis_image_cache,
                    include_metric_propagation_speed=bool(options.get("include_metric_propagation_speed")),
                    include_metric_area_recruited=bool(options.get("include_metric_area_recruited")),
                    include_metric_relative_area_recruited=bool(options.get("include_metric_relative_area_recruited")),
                    project_metadata=metadata,
                    propagation_gap_decision=_resolve_gap_decision,
                )
                self.app.root.after(0, lambda: self.app._on_export_done(result))
            except Exception as exc:
                self.app.root.after(0, lambda: self.app._set_status(f"Export failed: {exc}"))
                self.app._log_error(f"Export failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()
