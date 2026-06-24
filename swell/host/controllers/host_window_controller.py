from __future__ import annotations

from collections import OrderedDict
import importlib.util
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog
from swell.shared.ui import dialogs as messagebox

import numpy as np

from swell.analysis.core.metrics import compute_scale
from swell.analysis.ui.roi_dialog import _call_preserving_geometry, open_roi_dialog
from swell.analysis.ui.scale_dialog import open_scale_dialog
from swell.shared.ui.theme import SPACING, apply_theme
from swell.host.exporter import analysis_image_cache_key, export_analysis
from swell.shared.models import clone_analysis_payload
from swell.shared.services import MetricsSettingsResolver
from swell.shared.ui.bootstrap import center_window_on_screen as center_window, semantic_button_options, ttk


class HostWindowController:
    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def _masks_payload_equal(lhs, rhs) -> bool:
        if lhs is None and rhs is None:
            return True
        if isinstance(lhs, dict) and isinstance(rhs, dict):
            lhs_keys = {str(k) for k in lhs.keys()}
            rhs_keys = {str(k) for k in rhs.keys()}
            if lhs_keys != rhs_keys:
                return False
            for key in sorted(lhs_keys):
                left = np.asarray(lhs.get(key), dtype=bool)
                right = np.asarray(rhs.get(key), dtype=bool)
                if left.ndim != right.ndim or not np.array_equal(left, right):
                    return False
            return True
        left = np.asarray(lhs)
        right = np.asarray(rhs)
        if left.ndim != right.ndim:
            return False
        if left.ndim == 0 and right.ndim == 0:
            return bool(left == right)
        if left.ndim >= 1:
            return bool(np.array_equal(left, right))
        return False

    def _capture_export_sidecar_snapshot(self, event_ids: list[str]) -> dict[str, dict[str, object]]:
        snapshot: dict[str, dict[str, object]] = {}
        for event_id in [str(v) for v in list(event_ids or [])]:
            payload = self.app.browser_controller.session.load_analysis_sidecar(event_id)
            if not isinstance(payload, dict):
                continue
            snapshot[event_id] = clone_analysis_payload(payload)
        return snapshot

    def _restore_snapshot_if_masks_changed(self, snapshot: dict[str, dict[str, object]]) -> int:
        restored = 0
        for event_id, before_payload in dict(snapshot or {}).items():
            before_masks = dict(before_payload or {}).get("masks_committed")
            current_payload = self.app.browser_controller.session.load_analysis_sidecar(str(event_id)) or {}
            current_masks = dict(current_payload or {}).get("masks_committed")
            if self._masks_payload_equal(before_masks, current_masks):
                continue
            self.app.browser_controller.session.replace_analysis_sidecar(str(event_id), clone_analysis_payload(before_payload))
            restored += 1
        return int(restored)

    def _global_metrics_defaults_state(
        self,
    ) -> tuple[float, float | None, list[list[float]], bool, list[list[float]], list, np.ndarray | None]:
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
        scale_axis_lock = bool(defaults.get("scale_axis_lock", True))
        roi_points = list(defaults.get("roi_points", [])) if isinstance(defaults.get("roi_points"), list) else []
        roi_polygons = list(defaults.get("roi_polygons", [])) if isinstance(defaults.get("roi_polygons"), list) else []
        roi_mask = defaults.get("roi_mask")
        if roi_mask is not None:
            try:
                roi_mask = np.asarray(roi_mask, dtype=bool).copy()
                if roi_mask.ndim != 2:
                    roi_mask = None
            except Exception:
                roi_mask = None
        return float(fps_initial), scale_value, scale_points, scale_axis_lock, roi_points, roi_polygons, roi_mask

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

    def _save_project_after_metrics_apply(self) -> bool:
        project_path = str(getattr(self.app, "current_project_path", "") or "").strip()
        if not project_path:
            self.app._show_warning(
                "Open Metrics",
                "Metrics were updated in memory, but no .swell path is set. Save the project once, then apply metrics again.",
            )
            self.app._set_status("Metrics updated; project not saved.")
            return False
        try:
            state = self.app.save_host_session(project_path)
        except Exception as exc:
            self.app._show_warning("Open Metrics", f"Metrics were updated, but the project save failed:\n{exc}")
            self.app._set_status("Metrics updated; project save failed.")
            return False
        saved_path = str(getattr(state, "project_path", "") or project_path)
        self.app.current_project_path = saved_path
        try:
            self.app.browser_controller.session.set_project_path(saved_path)
        except Exception:
            pass
        self.app._log_info(f"Saved project after metrics update: {saved_path}.")
        self.app._set_status(f"Global metrics defaults updated and saved: {Path(saved_path).name}")
        return True

    def _propagation_gap_event_name(self, payload: dict[str, object]) -> str:
        event_label = str(payload.get("event_label", "") or "").strip()
        if event_label:
            return event_label
        event_id = str(payload.get("event_id", "") or "").strip()
        if not event_id:
            return "the current event"
        display_name = getattr(self.app.browser_controller, "event_display_name", None)
        if callable(display_name):
            return str(display_name(event_id) or event_id)
        try:
            event = self.app.browser_controller.get_event(event_id)
        except Exception:
            event = None
        label = str(getattr(event, "label", "") or "").strip() if event is not None else ""
        return label or event_id

    @staticmethod
    def _propagation_action_specs(warning_kind: str) -> list[dict[str, str]]:
        if str(warning_kind or "").strip().lower() == "zero_growth":
            return [
                {
                    "label": "Set To 0",
                    "action": "zero",
                    "semantic": "secondary",
                    "description": "Write zero speed for the affected frames.",
                },
                {
                    "label": "End Trace Here",
                    "action": "stop",
                    "semantic": "secondary",
                    "description": "Drop propagation-speed values from the first affected frame onward.",
                },
                {
                    "label": "Average Between Frames",
                    "action": "interpolate",
                    "semantic": "primary",
                    "description": "Linearly fill between the nearest valid frames on either side.",
                },
            ]
        return [
            {
                "label": "Leave Blank",
                "action": "ignore",
                "semantic": "secondary",
                "description": "Keep the affected frames undefined in the propagation-speed trace.",
            },
            {
                "label": "End Trace Here",
                "action": "stop",
                "semantic": "secondary",
                "description": "Drop propagation-speed values from the first affected frame onward.",
            },
            {
                "label": "Average Between Frames",
                "action": "interpolate",
                "semantic": "primary",
                "description": "Linearly fill between the nearest valid frames on either side.",
            },
        ]

    @staticmethod
    def _preview_series_from_payload(payload: dict[str, object]) -> tuple[list[int], np.ndarray]:
        frame_indices_raw = list(payload.get("preview_frame_indices", []) or [])
        values_raw = list(payload.get("preview_speed_values", []) or [])
        frame_indices: list[int] = []
        for raw in frame_indices_raw:
            try:
                frame_indices.append(int(raw))
            except Exception:
                continue
        if not frame_indices or len(frame_indices) != len(values_raw):
            return [], np.asarray([], dtype=np.float64)
        values = np.full(len(values_raw), np.nan, dtype=np.float64)
        for idx, raw in enumerate(values_raw):
            try:
                if raw is None:
                    continue
                values[idx] = float(raw)
            except Exception:
                continue
        return frame_indices, values

    @staticmethod
    def _preview_local_runs(frame_indices: list[int], payload: dict[str, object]) -> list[tuple[int, int]]:
        if not frame_indices:
            return []
        lookup = {int(frame_idx): pos for pos, frame_idx in enumerate(frame_indices)}
        runs: list[tuple[int, int]] = []
        for raw in list(payload.get("gap_frame_runs", []) or []):
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                continue
            try:
                start_global = int(raw[0])
                end_global = int(raw[1])
            except Exception:
                continue
            start = lookup.get(start_global)
            end = lookup.get(end_global)
            if start is None or end is None or end < start:
                continue
            runs.append((start, end))
        return runs

    @staticmethod
    def _apply_preview_action(values: np.ndarray, runs: list[tuple[int, int]], action: str) -> np.ndarray:
        arr = np.asarray(values, dtype=np.float64).copy()
        if arr.size == 0 or not runs:
            return arr
        normalized = str(action or "").strip().lower()
        if normalized == "stop":
            arr[runs[0][0] :] = np.nan
            return arr
        if normalized == "zero":
            for start, end in runs:
                arr[start : end + 1] = 0.0
            return arr
        if normalized == "interpolate":
            for start, end in runs:
                left_idx = start - 1
                right_idx = end + 1
                if left_idx < 0 or right_idx >= arr.size:
                    continue
                left_val = float(arr[left_idx])
                right_val = float(arr[right_idx])
                if not np.isfinite(left_val) or not np.isfinite(right_val):
                    continue
                span = right_idx - left_idx
                for idx in range(start, end + 1):
                    arr[idx] = left_val + ((right_val - left_val) * ((idx - left_idx) / float(span)))
            return arr
        return arr

    @staticmethod
    def _draw_propagation_preview(
        canvas: tk.Canvas,
        *,
        frame_indices: list[int],
        values: np.ndarray,
        affected_runs: list[tuple[int, int]],
        color: str,
    ) -> None:
        width = int(float(canvas.cget("width")))
        height = int(float(canvas.cget("height")))
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#11161d", outline="")
        if not frame_indices or values.size == 0:
            canvas.create_text(width / 2, height / 2, text="No preview", fill="#7e8794")
            return
        for start, end in affected_runs:
            x0 = 10 if len(frame_indices) <= 1 else 10 + ((width - 20) * (start / float(len(frame_indices) - 1)))
            x1 = 10 if len(frame_indices) <= 1 else 10 + ((width - 20) * (end / float(len(frame_indices) - 1)))
            canvas.create_rectangle(x0 - 3, 8, x1 + 3, height - 18, fill="#2b3c52", outline="")
        finite = np.isfinite(values)
        if not np.any(finite):
            canvas.create_text(width / 2, height / 2, text="No speed values", fill="#7e8794")
            return
        finite_values = values[finite]
        y_min = min(0.0, float(np.nanmin(finite_values)))
        y_max = float(np.nanmax(finite_values))
        if y_max <= y_min:
            y_max = y_min + 1.0

        def _x(pos: int) -> float:
            if len(frame_indices) <= 1:
                return width / 2
            return 10 + ((width - 20) * (pos / float(len(frame_indices) - 1)))

        def _y(val: float) -> float:
            return 10 + ((height - 30) * (1.0 - ((val - y_min) / (y_max - y_min))))

        zero_y = _y(0.0)
        canvas.create_line(10, zero_y, width - 10, zero_y, fill="#39424f", dash=(3, 3))

        segment: list[float] = []
        for pos, val in enumerate(values):
            if not np.isfinite(val):
                if len(segment) >= 4:
                    canvas.create_line(*segment, fill=color, width=2, smooth=True)
                segment = []
                continue
            segment.extend([_x(pos), _y(float(val))])
        if len(segment) >= 4:
            canvas.create_line(*segment, fill=color, width=2, smooth=True)

        canvas.create_text(10, height - 8, text=str(frame_indices[0]), fill="#7e8794", anchor="sw")
        canvas.create_text(width - 10, height - 8, text=str(frame_indices[-1]), fill="#7e8794", anchor="se")

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
        ready = MetricsSettingsResolver.prerequisites_for_events(
            event_ids=list(event_ids or []),
            metrics_loader=lambda event_id: self.app.browser_controller.resolve_event_metrics_settings(event_id),
        )
        intensity_ready = dict(ready.get("intensity", {}) or {})
        if bool(intensity_ready.get("enabled")):
            baseline_flags: list[bool] = []
            baseline_pre = int(getattr(self.app, "baseline_pre_frames", 0) or 0)
            for event_id in [str(v) for v in list(event_ids or [])]:
                try:
                    event = self.app.browser_controller.get_event(event_id)
                except Exception:
                    event = None
                try:
                    start_idx = int(getattr(event, "start_idx"))
                except Exception:
                    start_idx = -1
                baseline_flags.append(bool(baseline_pre > 0 and start_idx > 0))
            all_baseline = bool(baseline_flags) and all(baseline_flags)
            any_baseline = any(baseline_flags)
            if not all_baseline:
                intensity_ready["enabled"] = False
                intensity_ready["reason"] = (
                    "Some selected events are missing pre-event baseline frames."
                    if any_baseline
                    else "No selected events have pre-event baseline frames."
                )
                ready["intensity"] = intensity_ready
        return ready

    def _analysis_image_export_cache(self) -> OrderedDict:
        cache = getattr(self.app, "_analysis_image_export_cache", None)
        if isinstance(cache, OrderedDict):
            return cache
        cache = OrderedDict()
        self.app._analysis_image_export_cache = cache
        return cache

    def _cache_analysis_image_entry(self, key: tuple, entry: object) -> None:
        cache = self._analysis_image_export_cache()
        cache[key] = entry
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
            cache_key = analysis_image_cache_key(event, default_baseline_pre_frames=int(baseline_pre_frames))
            self._cache_analysis_image_entry(
                cache_key,
                {
                    "frames_viz": frames_viz,
                    "frame_count": int(frame_count),
                },
            )
        return cache

    @staticmethod
    def attach_disabled_tooltip(parent, widget, message: str) -> None:
        message = str(message or "").strip()
        if not message:
            return
        tip = tk.Toplevel(parent)
        tip.withdraw()
        tip.overrideredirect(True)
        apply_theme(tip)
        tip_label = ttk.Label(tip, text=message, padding=6, style="Card.TLabel", justify="left")
        tip_label.pack()

        def _show_tip(event) -> None:
            if not message:
                _hide_tip()
                return
            x = int(event.x_root) + 10
            y = int(event.y_root) + 10
            tip.geometry(f"+{x}+{y}")
            tip.deiconify()
            tip.lift()

        def _hide_tip(_event=None) -> None:
            tip.withdraw()

        widget.bind("<Enter>", _show_tip)
        widget.bind("<Leave>", _hide_tip)
        widget.bind("<ButtonPress>", _hide_tip, add="+")
        widget.bind("<FocusOut>", _hide_tip, add="+")
        widget.bind("<Destroy>", lambda _e: tip.destroy())

    @staticmethod
    def _can_export_combined_metric_spreadsheet(
        *,
        include_metric_propagation_speed: bool,
        include_metric_area_recruited: bool,
        include_metric_relative_area_recruited: bool,
        include_metric_intensity: bool = False,
        include_metric_lineage_object_metrics: bool = False,
    ) -> bool:
        return bool(
            importlib.util.find_spec("openpyxl") is not None
            and (
                include_metric_propagation_speed
                or include_metric_area_recruited
                or include_metric_relative_area_recruited
                or include_metric_intensity
                or include_metric_lineage_object_metrics
            )
        )

    def prompt_export_options(self, event_ids: list[str]) -> dict[str, bool] | None:
        dialog = tk.Toplevel(self.app.root)
        dialog.withdraw()
        dialog.title("Export Options")
        dialog.transient(self.app.root)
        dialog.resizable(True, True)
        dialog.geometry("680x1")
        apply_theme(dialog)

        include_event_var = tk.BooleanVar(value=True)
        include_baseline_var = tk.BooleanVar(value=True)
        include_analysis_var = tk.BooleanVar(value=False)
        include_masks_var = tk.BooleanVar(value=True)
        include_mask_overlay_var = tk.BooleanVar(value=True)
        include_analysis_overlay_var = tk.BooleanVar(value=False)
        include_contour_map_var = tk.BooleanVar(value=False)
        include_metric_speed_var = tk.BooleanVar(value=True)
        include_metric_area_var = tk.BooleanVar(value=True)
        include_metric_rel_area_var = tk.BooleanVar(value=True)
        include_metric_intensity_var = tk.BooleanVar(value=True)
        include_metric_lineage_var = tk.BooleanVar(value=False)
        include_metric_lineage_tables_var = tk.BooleanVar(value=False)
        include_metric_combined_spreadsheet_var = tk.BooleanVar(value=False)
        output_dir_var = tk.StringVar(value=self.app.output_var.get().strip())
        result: dict[str, str | bool] | None = None
        has_masks = self.has_binary_masks_for_events(event_ids)
        metric_ready = self.resolve_export_metric_prerequisites(event_ids)

        shell = ttk.Frame(dialog, padding=SPACING.outer, style="AppShell.TFrame")
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text=f"Choose export items for {len(event_ids)} event(s)", style="AppSectionTitle.TLabel").pack(anchor="w")

        output_row = ttk.Frame(shell, padding=SPACING.card, style="AppSurface.TFrame")
        output_row.pack(fill="x", pady=(6, 10))
        ttk.Label(output_row, text="Output Folder", style="AppMeta.TLabel").pack(side="left")
        output_entry = ttk.Entry(output_row, textvariable=output_dir_var, style="AppCompact.TEntry")
        output_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))

        def _browse_output_dir() -> None:
            initial = output_dir_var.get().strip() or self.app.output_var.get().strip() or str(Path.cwd())
            folder = filedialog.askdirectory(parent=dialog, title="Select Export Folder", initialdir=initial)
            if folder:
                output_dir_var.set(str(folder))

        ttk.Button(output_row, text="Browse...", command=_browse_output_dir, **semantic_button_options("secondary")).pack(side="left")

        checks = ttk.Frame(shell, padding=SPACING.card, style="AppSurface.TFrame")
        checks.pack(fill="x", pady=(0, 10))
        ttk.Label(checks, text="Include", style="AppSectionTitle.TLabel").pack(anchor="w", pady=(0, SPACING.gap))
        ttk.Checkbutton(checks, text="Event Images", variable=include_event_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="Baseline Images", variable=include_baseline_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="Analysis Images", variable=include_analysis_var).pack(anchor="w")
        masks_check = ttk.Checkbutton(checks, text="Binary Masks", variable=include_masks_var)
        masks_check.pack(anchor="w")
        overlay_check = ttk.Checkbutton(checks, text="Mask Overlay Images", variable=include_mask_overlay_var)
        overlay_check.pack(anchor="w")
        analysis_overlay_check = ttk.Checkbutton(
            checks,
            text="Analysis Overlay Images",
            variable=include_analysis_overlay_var,
        )
        analysis_overlay_check.pack(anchor="w")
        contour_map_check = ttk.Checkbutton(checks, text="Contour Map", variable=include_contour_map_var)
        contour_map_check.pack(anchor="w")
        if not has_masks:
            include_masks_var.set(False)
            masks_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, masks_check, "No binary masks exist for the selected events.")
            include_mask_overlay_var.set(False)
            overlay_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, overlay_check, "No binary masks exist for the selected events.")
            include_analysis_overlay_var.set(False)
            analysis_overlay_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, analysis_overlay_check, "No binary masks exist for the selected events.")
            include_contour_map_var.set(False)
            contour_map_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, contour_map_check, "No binary masks exist for the selected events.")

        ttk.Separator(checks, orient="horizontal").pack(fill="x", pady=(6, 4))
        ttk.Label(checks, text="Metrics", style="AppMeta.TLabel").pack(anchor="w")
        metric_speed_check = ttk.Checkbutton(checks, text="Propagation Speed", variable=include_metric_speed_var)
        metric_speed_check.pack(anchor="w")
        metric_area_check = ttk.Checkbutton(checks, text="Area Recruited", variable=include_metric_area_var)
        metric_area_check.pack(anchor="w")
        metric_rel_area_check = ttk.Checkbutton(
            checks, text="Relative Area Recruited", variable=include_metric_rel_area_var
        )
        metric_rel_area_check.pack(anchor="w")
        metric_intensity_check = ttk.Checkbutton(
            checks, text="Intensity", variable=include_metric_intensity_var
        )
        metric_intensity_check.pack(anchor="w")
        metric_lineage_check = ttk.Checkbutton(
            checks,
            text="Lineage-aware Object Metrics",
            variable=include_metric_lineage_var,
        )
        metric_lineage_check.pack(anchor="w")
        metric_lineage_tables_check = ttk.Checkbutton(
            checks,
            text="Export per-object track tables",
            variable=include_metric_lineage_tables_var,
        )
        metric_lineage_tables_check.pack(anchor="w")
        metric_combined_spreadsheet_check = ttk.Checkbutton(
            checks,
            text="Export combined selected as a spreadsheet",
            variable=include_metric_combined_spreadsheet_var,
        )
        metric_combined_spreadsheet_check.pack(anchor="w", pady=(2, 0))
        if importlib.util.find_spec("openpyxl") is None:
            include_metric_combined_spreadsheet_var.set(False)
            metric_combined_spreadsheet_check.configure(state="disabled")
            self.attach_disabled_tooltip(
                dialog,
                metric_combined_spreadsheet_check,
                "Install openpyxl to enable combined spreadsheet export.",
            )

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
        if not bool(metric_ready.get("intensity", {}).get("enabled")):
            include_metric_intensity_var.set(False)
            metric_intensity_check.configure(state="disabled")
            self.attach_disabled_tooltip(
                dialog,
                metric_intensity_check,
                str(metric_ready.get("intensity", {}).get("reason", "Intensity export is unavailable.")),
            )
        lineage_reason = ""
        lineage_enabled = bool(has_masks and metric_ready["relative_area_recruited"]["enabled"])
        if not has_masks:
            lineage_reason = "No binary masks exist for the selected events."
        elif not bool(metric_ready["relative_area_recruited"]["enabled"]):
            lineage_reason = str(metric_ready["relative_area_recruited"]["reason"])
        if not lineage_enabled:
            include_metric_lineage_var.set(False)
            include_metric_lineage_tables_var.set(False)
            metric_lineage_check.configure(state="disabled")
            metric_lineage_tables_check.configure(state="disabled")
            self.attach_disabled_tooltip(dialog, metric_lineage_check, lineage_reason)
            self.attach_disabled_tooltip(dialog, metric_lineage_tables_check, lineage_reason)

        def _refresh_combined_metrics_spreadsheet_state(*_args) -> None:
            enabled = self._can_export_combined_metric_spreadsheet(
                include_metric_propagation_speed=bool(include_metric_speed_var.get()),
                include_metric_area_recruited=bool(include_metric_area_var.get()),
                include_metric_relative_area_recruited=bool(include_metric_rel_area_var.get()),
                include_metric_intensity=bool(include_metric_intensity_var.get()),
                include_metric_lineage_object_metrics=bool(include_metric_lineage_var.get()),
            )
            if enabled:
                metric_combined_spreadsheet_check.configure(state="normal")
            else:
                include_metric_combined_spreadsheet_var.set(False)
                metric_combined_spreadsheet_check.configure(state="disabled")

        def _refresh_lineage_tables_state(*_args) -> None:
            enabled = bool(lineage_enabled and include_metric_lineage_var.get())
            if enabled:
                metric_lineage_tables_check.configure(state="normal")
            else:
                include_metric_lineage_tables_var.set(False)
                metric_lineage_tables_check.configure(state="disabled")

        include_metric_speed_var.trace_add("write", _refresh_combined_metrics_spreadsheet_state)
        include_metric_area_var.trace_add("write", _refresh_combined_metrics_spreadsheet_state)
        include_metric_rel_area_var.trace_add("write", _refresh_combined_metrics_spreadsheet_state)
        include_metric_intensity_var.trace_add("write", _refresh_combined_metrics_spreadsheet_state)
        include_metric_lineage_var.trace_add("write", _refresh_combined_metrics_spreadsheet_state)
        include_metric_lineage_var.trace_add("write", _refresh_lineage_tables_state)
        _refresh_combined_metrics_spreadsheet_state()
        _refresh_lineage_tables_state()

        buttons = ttk.Frame(shell, style="AppShell.TFrame")
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
                or bool(include_analysis_overlay_var.get())
                or bool(include_contour_map_var.get())
                or bool(include_metric_speed_var.get())
                or bool(include_metric_area_var.get())
                or bool(include_metric_rel_area_var.get())
                or bool(include_metric_intensity_var.get())
                or bool(include_metric_lineage_var.get())
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
                "include_analysis_overlay_images": bool(include_analysis_overlay_var.get()),
                "include_contour_map": bool(include_contour_map_var.get()),
                "include_metric_propagation_speed": bool(include_metric_speed_var.get()),
                "include_metric_area_recruited": bool(include_metric_area_var.get()),
                "include_metric_relative_area_recruited": bool(include_metric_rel_area_var.get()),
                "include_metric_intensity": bool(include_metric_intensity_var.get()),
                "include_metric_lineage_object_metrics": bool(include_metric_lineage_var.get()),
                "include_metric_lineage_track_tables": bool(include_metric_lineage_tables_var.get()),
                "include_metric_combined_spreadsheet": bool(include_metric_combined_spreadsheet_var.get()),
            }
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=_cancel, **semantic_button_options("secondary")).pack(side="right")
        ttk.Button(buttons, text="Export", command=_confirm, **semantic_button_options("primary")).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        self.center_window_on_screen(dialog, width=680)
        dialog.deiconify()
        dialog.grab_set()
        dialog.wait_window()
        return result

    def prompt_propagation_gap_action(self, payload: dict[str, object]) -> list[str]:
        warning_kind = str(payload.get("warning_kind", "gap") or "gap").strip().lower()
        default_action = "zero" if warning_kind == "zero_growth" else "ignore"

        runs_raw = list(payload.get("gap_frame_runs", []) or [])
        runs_normalized: list[tuple[int, int]] = []
        for raw in runs_raw:
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                continue
            try:
                runs_normalized.append((int(raw[0]), int(raw[1])))
            except Exception:
                continue
        if not runs_normalized:
            return []

        gap_actions = [default_action] * len(runs_normalized)
        result = {"actions": list(gap_actions)}

        dialog = tk.Toplevel(self.app.root)
        dialog.withdraw()
        dialog.title("Propagation Speed Warning")
        dialog.transient(self.app.root)
        dialog.resizable(False, False)
        apply_theme(dialog)

        shell = ttk.Frame(dialog, padding=SPACING.outer, style="AppShell.TFrame")
        shell.pack(fill="both", expand=True)
        event_name = self._propagation_gap_event_name(payload)
        action_specs = self._propagation_action_specs(warning_kind)
        preview_frame_indices, preview_values = self._preview_series_from_payload(payload)
        preview_runs = self._preview_local_runs(preview_frame_indices, payload)

        range_count = len(runs_normalized)
        range_word = "range" if range_count == 1 else "ranges"
        if warning_kind == "zero_growth":
            heading = f"No outward propagation above threshold was detected for {event_name}."
            detail = (
                f"{range_count} affected {range_word} found. Each can use its own handling: "
                "write zero speed, smooth across, or end the speed trace at that range."
            )
        else:
            heading = f"Undefined propagation-speed values were detected for {event_name}."
            detail = (
                f"{range_count} affected {range_word} found. Each can use its own handling: "
                "leave blank, smooth across, or end the speed trace at that range."
            )
        summary = ttk.Frame(shell, padding=SPACING.card, style="AppInset.TFrame")
        summary.pack(fill="x", pady=(0, SPACING.gap))
        ttk.Label(summary, text=heading, justify="left", style="AppSectionTitle.TLabel").pack(anchor="w")
        ttk.Label(
            shell,
            text=detail,
            justify="left",
            style="AppMeta.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(0, SPACING.card))

        ttk.Label(
            shell,
            text="Preview — click a button below a graph to apply that action to every range",
            style="AppSectionTitle.TLabel",
        ).pack(anchor="w", pady=(0, SPACING.gap))
        previews = ttk.Frame(shell, style="AppShell.TFrame")
        previews.pack(fill="x", pady=(0, SPACING.card))
        preview_colors = {
            "ignore": "#c58cff",
            "zero": "#f5c451",
            "stop": "#ef7d57",
            "interpolate": "#4db3ff",
        }
        for index, spec in enumerate(action_specs):
            card = ttk.Frame(previews, padding=SPACING.card, style="AppInset.TFrame")
            card.pack(side="left", fill="both", expand=True, padx=(SPACING.gap if index else 0, 0))
            ttk.Label(card, text=str(spec["label"]), style="AppSectionTitle.TLabel").pack(anchor="w")
            canvas = tk.Canvas(card, width=240, height=120, bg="#11161d", highlightthickness=0, bd=0)
            canvas.pack(fill="x", pady=(SPACING.inner, SPACING.inner))
            preview_series = self._apply_preview_action(preview_values, preview_runs, str(spec["action"]))
            self._draw_propagation_preview(
                canvas,
                frame_indices=preview_frame_indices,
                values=preview_series,
                affected_runs=preview_runs,
                color=preview_colors.get(str(spec["action"]), "#4db3ff"),
            )
            ttk.Label(
                card,
                text=str(spec["description"]),
                style="AppMeta.TLabel",
                wraplength=220,
                justify="left",
            ).pack(anchor="w")
            button_row = ttk.Frame(card, style="AppInset.TFrame")
            button_row.pack(fill="x", pady=(SPACING.inner, 0))
            ttk.Button(
                button_row,
                text="Apply to all",
                command=lambda value=str(spec["action"]): _apply_to_all(value),
                **semantic_button_options(str(spec["semantic"])),
            ).pack(anchor="center")

        ttk.Label(
            shell,
            text="Per-range selection",
            style="AppSectionTitle.TLabel",
        ).pack(anchor="w", pady=(SPACING.gap, SPACING.gap))
        rows_frame = ttk.Frame(shell, style="AppShell.TFrame")
        rows_frame.pack(fill="x", pady=(0, SPACING.card))

        row_buttons: list[dict[str, ttk.Button]] = []
        row_status_labels: list[ttk.Label] = []
        for i, (start, end) in enumerate(runs_normalized):
            row = ttk.Frame(rows_frame, padding=SPACING.card, style="AppInset.TFrame")
            row.pack(fill="x", pady=(0 if i == 0 else SPACING.gap, 0))
            label_text = (
                f"Range {i + 1}: Frame {start}"
                if start == end
                else f"Range {i + 1}: Frames {start}–{end}"
            )
            ttk.Label(row, text=label_text, style="AppSectionTitle.TLabel").pack(side="left")
            status_label = ttk.Label(row, text="", style="AppMeta.TLabel")
            status_label.pack(side="left", padx=(SPACING.gap, 0))
            row_status_labels.append(status_label)
            btn_frame = ttk.Frame(row, style="AppInset.TFrame")
            btn_frame.pack(side="right")
            btns: dict[str, ttk.Button] = {}
            for j, spec in enumerate(action_specs):
                action_val = str(spec["action"])
                btn = ttk.Button(
                    btn_frame,
                    text=str(spec["label"]),
                    command=lambda idx=i, act=action_val: _set_gap(idx, act),
                )
                btn.pack(side="left", padx=(SPACING.gap if j else 0, 0))
                btns[action_val] = btn
            row_buttons.append(btns)

        def _refresh_rows() -> None:
            stopped_at: int | None = None
            for i, btns in enumerate(row_buttons):
                ended = stopped_at is not None
                for action_val, btn in btns.items():
                    if ended:
                        btn.configure(**semantic_button_options("secondary"))
                        btn.state(["disabled"])
                    else:
                        if action_val == gap_actions[i]:
                            btn.configure(**semantic_button_options("primary"))
                        else:
                            btn.configure(**semantic_button_options("secondary"))
                        btn.state(["!disabled"])
                row_status_labels[i].configure(text="(trace already ended)" if ended else "")
                if gap_actions[i] == "stop" and stopped_at is None:
                    stopped_at = i

        def _apply_to_all(action: str) -> None:
            for i in range(len(gap_actions)):
                gap_actions[i] = action
            _refresh_rows()

        def _set_gap(i: int, action: str) -> None:
            gap_actions[i] = action
            _refresh_rows()

        def _confirm() -> None:
            result["actions"] = list(gap_actions)
            dialog.destroy()

        def _cancel() -> None:
            dialog.destroy()

        _refresh_rows()

        footer = ttk.Frame(shell, style="AppShell.TFrame")
        footer.pack(fill="x", pady=(SPACING.gap, 0))
        ttk.Button(footer, text="Cancel", command=_cancel, **semantic_button_options("secondary")).pack(side="right")
        ttk.Button(
            footer,
            text="Confirm",
            command=_confirm,
            **semantic_button_options("primary"),
        ).pack(side="right", padx=(0, SPACING.gap))

        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        row_height = 56
        base_height = 560
        height = min(840, base_height + max(0, range_count - 1) * row_height)
        self.center_window_on_screen(dialog, width=900, height=height)
        dialog.deiconify()
        dialog.grab_set()
        dialog.wait_window()
        return list(result["actions"])

    @staticmethod
    def center_window_on_screen(window, *, width: int | None = None, height: int | None = None) -> None:
        center_window(window, width=width, height=height)

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

        fps_initial, scale_value, scale_points, scale_axis_lock, roi_points, roi_polygons, roi_mask = self._global_metrics_defaults_state()

        dialog = tk.Toplevel(self.app.root)
        dialog.withdraw()
        dialog.title("Open Metrics")
        dialog.transient(self.app.root)
        dialog.resizable(True, True)
        dialog.geometry("560x1")
        apply_theme(dialog)
        self.app._open_metrics_dialog = dialog

        shell = ttk.Frame(dialog, padding=SPACING.outer, style="AppShell.TFrame")
        shell.pack(fill="both", expand=True)
        ttk.Label(
            shell,
            text="Configure global Frames/sec, Scale, and ROI defaults for this project.",
            style="AppMeta.TLabel",
        ).pack(anchor="w")

        fps_row = ttk.Frame(shell, padding=SPACING.card, style="AppSurface.TFrame")
        fps_row.pack(fill="x", pady=(10, 6))
        ttk.Label(fps_row, text="Frames/sec", style="AppSectionTitle.TLabel").pack(side="left")
        fps_var = tk.StringVar(value=f"{fps_initial:.6g}")
        ttk.Entry(fps_row, textvariable=fps_var, width=10, style="AppCompact.TEntry").pack(side="left", padx=(8, 0))

        scale_status_var = tk.StringVar()
        roi_status_var = tk.StringVar()

        def _refresh_labels() -> None:
            if scale_value is None:
                scale_status_var.set("Scale: Not set")
            else:
                scale_status_var.set(f"Scale: {float(scale_value):.6g} px/mm")
            region_count = len(roi_polygons) if isinstance(roi_polygons, list) and roi_polygons else (1 if roi_points else 0)
            if roi_mask is not None:
                roi_status_var.set(f"ROI: {region_count} region(s), {int(np.count_nonzero(roi_mask))} px")
            elif roi_points:
                roi_status_var.set(f"ROI: {len(roi_points)} points")
            else:
                roi_status_var.set("ROI: Not set")

        def _refresh_from_host() -> None:
            nonlocal scale_value, scale_points, scale_axis_lock, roi_points, roi_polygons, roi_mask
            _fps_value, scale_value, scale_points, scale_axis_lock, roi_points, roi_polygons, roi_mask = self._global_metrics_defaults_state()
            _refresh_labels()

        self.app._refresh_open_metrics_dialog = _refresh_from_host

        controls = ttk.Frame(shell, style="AppShell.TFrame")
        controls.pack(fill="x", pady=(6, 6))

        def _set_scale() -> None:
            nonlocal scale_value, scale_points, scale_axis_lock
            img_result = _call_preserving_geometry(
                dialog,
                lambda: self.app._pick_metrics_reference_image_u8(parent=None, purpose="Scale"),
            )
            if img_result is None:
                return
            img_u8, img_name = img_result

            def _pick_scale_image_for_dialog():
                res = self.app._pick_metrics_reference_image_u8(parent=dialog, purpose="Scale", force_picker=True)
                return res[0] if res else None

            initial_length_mm = None
            if scale_points and len(scale_points) >= 2 and scale_value > 0:
                p1, p2 = scale_points[0], scale_points[1]
                dist_px = np.hypot(float(p1[0]) - float(p2[0]), float(p1[1]) - float(p2[1]))
                initial_length_mm = float(dist_px) / float(scale_value)

            initial_manual_px_per_mm = None
            # In host, we don't have a dedicated manual_px_per_mm getter/setter 
            # in the same way, but we can pass it if we add it to host state.
            # For now, we'll assume it's only in Analysis for simplicity unless
            # we want to add it to host_models.py.
            
            result = open_scale_dialog(
                root=dialog,
                img_u8=img_u8,
                snap_scale_points_axis=self.app._snap_scale_points_axis,
                refine_scale_bar_points=self.app._refine_scale_bar_points,
                compute_scale=compute_scale,
                initial_scale_points=scale_points,
                initial_axis_lock=scale_axis_lock,
                pick_image_callback=_pick_scale_image_for_dialog,
                initial_length_mm=initial_length_mm,
                context="host",
                initial_manual_px_per_mm=None, # Host doesn't persist manual yet
                image_label=img_name,
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
            scale_axis_lock = bool(result.get("axis_lock", True))
            _refresh_labels()

        def _set_roi() -> None:
            nonlocal roi_points, roi_polygons, roi_mask
            img_result = _call_preserving_geometry(
                dialog,
                lambda: self.app._pick_metrics_reference_image_u8(parent=None, purpose="ROI"),
            )
            if img_result is None:
                return
            img_u8, img_name = img_result

            def _pick_roi_image_for_dialog(parent=None):
                picker_parent = parent or dialog
                res = _call_preserving_geometry(
                    picker_parent,
                    lambda: self.app._pick_metrics_reference_image_u8(
                        parent=picker_parent,
                        purpose="ROI",
                        force_picker=True,
                    ),
                )
                return res[0] if res else None

            result = open_roi_dialog(
                root=dialog,
                img_u8=img_u8,
                initial_roi_points=list(roi_points),
                initial_roi_polygons=roi_polygons,
                pick_image_callback=_pick_roi_image_for_dialog,
                context="host",
                image_label=img_name,
            )
            if not isinstance(result, dict):
                return
            roi_points = list(result.get("roi_points", []))
            roi_polygons = list(result.get("roi_polygons", [])) if isinstance(result.get("roi_polygons"), list) else []
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

        ttk.Button(controls, text="Set Scale", command=_set_scale, **semantic_button_options("secondary")).pack(side="left")
        ttk.Button(controls, text="Draw ROI", command=_set_roi, **semantic_button_options("secondary")).pack(side="left", padx=(8, 0))

        ttk.Label(shell, textvariable=scale_status_var, style="AppMeta.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Label(shell, textvariable=roi_status_var, style="AppMeta.TLabel").pack(anchor="w", pady=(0, 8))
        _refresh_labels()

        actions = ttk.Frame(shell, style="AppShell.TFrame")
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
                payload["scale_unit"] = "px_per_mm"
                payload["scale_source"] = "calibration"
            if len(scale_points) == 2:
                payload["scale_points"] = [[float(pt[0]), float(pt[1])] for pt in scale_points]
                payload["scale_axis_lock"] = bool(scale_axis_lock)
            if roi_points:
                payload["roi_points"] = [[float(pt[0]), float(pt[1])] for pt in roi_points]
            if roi_polygons:
                payload["roi_polygons"] = [
                    [[float(pt[0]), float(pt[1])] for pt in list(poly)]
                    for poly in roi_polygons
                    if isinstance(poly, list) and len(poly) >= 3
                ]
            if roi_mask is not None:
                payload["roi_mask"] = np.asarray(roi_mask, dtype=bool).copy()

            self.app.browser_controller.set_global_metrics_defaults(payload)
            materialized = self.app.browser_controller.materialize_metrics_defaults_to_events()
            self.app._set_status("Global metrics defaults updated.")
            if materialized > 0:
                self.app._log_info(
                    "Updated global metrics defaults and applied missing values to "
                    f"{materialized} event(s)."
                )
            else:
                self.app._log_info("Updated global metrics defaults.")
            if not self._save_project_after_metrics_apply():
                return
            dialog.destroy()

        ttk.Button(actions, text="Cancel", command=_cancel, **semantic_button_options("secondary")).pack(side="right")
        ttk.Button(actions, text="Apply", command=_apply, **semantic_button_options("primary")).pack(side="right", padx=(0, 8))

        def _on_destroy(_event=None) -> None:
            if getattr(self.app, "_open_metrics_dialog", None) is dialog:
                self.app._open_metrics_dialog = None
                self.app._refresh_open_metrics_dialog = None

        dialog.bind("<Destroy>", _on_destroy)
        self.center_window_on_screen(dialog, width=560)
        dialog.deiconify()
        dialog.grab_set()
        dialog.wait_window()

    def run_export(self, event_ids: list[str], *, options: dict[str, object]) -> None:
        if self.app.reader is None:
            self.app._log_warn("Export blocked: load a stack first.")
            messagebox.showwarning("Export", "Load a stack first.", parent=self.app.root)
            return
        project_controller = getattr(self.app, "_get_project_controller", lambda: None)()
        ensure_stack = getattr(project_controller, "ensure_active_stack_available", None)
        if callable(ensure_stack) and not bool(ensure_stack(title="Export")):
            self.app._log_warn("Export blocked: stack folder is missing.")
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
            f"analysis_overlay_images={bool(options.get('include_analysis_overlay_images'))}, "
            f"contour_map={bool(options.get('include_contour_map'))}, "
            f"metric_propagation_speed={bool(options.get('include_metric_propagation_speed'))}, "
            f"metric_area_recruited={bool(options.get('include_metric_area_recruited'))}, "
            f"metric_relative_area_recruited={bool(options.get('include_metric_relative_area_recruited'))}, "
            f"metric_intensity={bool(options.get('include_metric_intensity'))}, "
            f"metric_lineage_object_metrics={bool(options.get('include_metric_lineage_object_metrics'))}, "
            f"metric_lineage_track_tables={bool(options.get('include_metric_lineage_track_tables'))}, "
            f"metric_combined_spreadsheet={bool(options.get('include_metric_combined_spreadsheet'))}."
        )
        sidecar_snapshot = self._capture_export_sidecar_snapshot(event_ids)

        def worker() -> None:
            try:
                assert self.app.reader is not None
                export_events = self.app.browser_controller.export_candidates(event_ids)
                analysis_image_cache = None
                if bool(options.get("include_analysis_images")) or bool(
                    options.get("include_analysis_overlay_images")
                ):
                    analysis_image_cache = self._seed_analysis_image_export_cache(export_events, baseline_pre)
                sidecar = self.app.browser_controller.session.state().analysis_sidecar
                metadata = self.app.browser_controller.session.state().metadata

                def _notify_progress(payload: dict) -> None:
                    if not hasattr(self.app, "root") or self.app.root is None:
                        self.app._on_export_progress(dict(payload or {}))
                        return
                    progress_payload = dict(payload or {})
                    self.app.root.after(0, lambda p=progress_payload: self.app._on_export_progress(p))

                def _resolve_gap_decision(payload: dict[str, object]) -> list[str]:
                    warning_kind = str(payload.get("warning_kind", "gap") or "gap")
                    default_action = "zero" if warning_kind == "zero_growth" else "ignore"
                    run_count = len(list(payload.get("gap_frame_runs", []) or []))
                    fallback = [default_action] * max(run_count, 1)
                    response: dict[str, list[str]] = {"actions": list(fallback)}
                    wait_event = threading.Event()

                    def _ask() -> None:
                        try:
                            raw = self.prompt_propagation_gap_action(dict(payload or {}))
                            if isinstance(raw, str):
                                raw = [raw]
                            actions_list = list(raw or [])
                            if not actions_list:
                                actions_list = list(fallback)
                            response["actions"] = actions_list
                        finally:
                            wait_event.set()

                    self.app.root.after(0, _ask)
                    wait_event.wait()
                    actions = list(response.get("actions") or fallback)
                    event_name = str(payload.get("event_label", "") or payload.get("event_id", "?"))
                    self.app._log_warn(
                        f"Propagation speed warning kind='{warning_kind}' resolved for {event_name} with actions={actions}."
                    )
                    return actions

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
                    include_analysis_overlay_images=bool(options.get("include_analysis_overlay_images")),
                    include_contour_map=bool(options.get("include_contour_map")),
                    analysis_sidecar=sidecar,
                    analysis_image_cache=analysis_image_cache,
                    include_metric_propagation_speed=bool(options.get("include_metric_propagation_speed")),
                    include_metric_area_recruited=bool(options.get("include_metric_area_recruited")),
                    include_metric_relative_area_recruited=bool(options.get("include_metric_relative_area_recruited")),
                    include_metric_intensity=bool(options.get("include_metric_intensity")),
                    include_metric_lineage_object_metrics=bool(options.get("include_metric_lineage_object_metrics")),
                    include_metric_lineage_track_tables=bool(options.get("include_metric_lineage_track_tables")),
                    include_metric_combined_spreadsheet=bool(options.get("include_metric_combined_spreadsheet")),
                    project_metadata=metadata,
                    propagation_gap_decision=_resolve_gap_decision,
                )
                restored_count = self._restore_snapshot_if_masks_changed(sidecar_snapshot)
                if restored_count > 0:
                    self.app._log_warn(
                        "Detected analysis mask drift during export and restored "
                        f"{restored_count} event(s) from pre-export snapshots."
                    )
                self.app.root.after(0, lambda: self.app._on_export_done(result))
            except Exception as exc:
                def _show_err(e=exc):
                    self.app._set_status(f"Export failed: {e}")
                    messagebox.showerror("Export Failed", str(e), parent=self.app.root)
                self.app.root.after(0, _show_err)
                self.app._log_error(f"Export failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()
