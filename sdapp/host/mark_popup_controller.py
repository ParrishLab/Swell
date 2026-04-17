from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from sdapp.shared.ui.theme import SPACING, apply_theme
from sdapp.host.analysis_payload_mapper import apply_analysis_scope_flags
from sdapp.host.ui_geometry import clamp_popup_range
from sdapp.shared.ui.bootstrap import center_window_on_screen as center_window, semantic_button_options, ttk


class MarkPopupController:
    """Manage mark/edit popup lifecycle while delegating rendering to the host UI layer."""

    def __init__(self, app) -> None:
        self.app = app

    def open_new(self) -> None:
        self.open_popup(mode="new", event_id=None)

    def open_edit_selected(self) -> None:
        selected = list(self.app.tree.selection())
        if not selected:
            self.app._log_warn("Edit Selected blocked: no event selected.")
            self.app._show_warning("SD Event", "Select one event first.")
            return
        if len(selected) != 1:
            self.app._log_warn("Edit Selected blocked: multiple events selected.")
            self.app._show_warning("SD Event", "Select exactly one event to edit.")
            return
        self.open_popup(mode="edit", event_id=selected[0])

    def _resolve_initial_popup_state(
        self,
        *,
        mode: str,
        event,
        frame_count: int,
        current_frame_idx: int,
    ) -> tuple[int, int, int, int, int]:
        if mode == "edit" and event is not None:
            start_default = int(event.start_idx)
            end_default = int(event.end_idx)
            center_idx = int((start_default + end_default) // 2)
        else:
            center_idx = int(current_frame_idx)
            start_default = center_idx
            end_default = center_idx

        local_start, local_end, clamped_center, _removed = clamp_popup_range(
            center_idx - 100,
            center_idx + 100,
            int(frame_count),
            center_idx,
            None,
        )
        return clamped_center, start_default, end_default, local_start, local_end

    def _begin_popup_session(self, range_start: int, range_end: int, *, normalize_to_current_frame: bool = False) -> None:
        try:
            self.app._apply_popup_range_bounds(int(range_start), int(range_end))
        except Exception as exc:
            self.app._log_warn(f"Initial popup preview failed: {exc}")

        recompute_kwargs = {
            "show_errors": False,
            "loading_text": "Computing selected range...",
        }
        if normalize_to_current_frame:
            current_idx = int(getattr(self.app, "_mark_popup_current_idx", range_start))
            recompute_kwargs["normalization_range_start"] = current_idx
            recompute_kwargs["normalization_range_end"] = current_idx

        self.app._recompute_popup_pipeline_for_bounds(
            int(getattr(self.app, "_mark_popup_local_start", range_start)),
            int(getattr(self.app, "_mark_popup_local_end", range_end)),
            **recompute_kwargs,
        )

    def _resolve_initial_baseline_state(self, *, mode: str, event, start_default: int) -> tuple[int, int]:
        fallback_count = max(1, int(getattr(self.app, "baseline_pre_frames", 30) or 30))
        flags = dict(getattr(event, "flags", {}) or {}) if mode == "edit" and event is not None else {}
        try:
            baseline_count = max(1, int(flags.get("baseline_pre_frames", fallback_count)))
        except Exception:
            baseline_count = fallback_count
        baseline_end = max(0, int(start_default) - 1)
        return baseline_count, baseline_end

    def open_popup(self, mode: str, event_id: str | None) -> None:
        if self.app.reader is None or self.app.stack_info is None:
            self.app._log_warn("Mark popup blocked: no stack loaded.")
            messagebox.showwarning("Mark SD Event", "Load a stack first.", parent=self.app.root)
            return

        if self.app._popup.mark_popup is not None and self.app._popup.mark_popup.winfo_exists():
            self.app._popup.mark_popup.focus_force()
            self.app._popup.mark_popup.lift()
            return

        event = self.app._get_event_by_id(event_id) if event_id else None
        if mode == "edit" and event is None:
            self.app._log_warn("Edit popup blocked: selected event not found.")
            messagebox.showwarning("SD Event", "Selected event was not found.", parent=self.app.root)
            return

        frame_count = int(self.app.stack_info.frame_count)
        center_idx, start_default, end_default, initial_range_start, initial_range_end = self._resolve_initial_popup_state(
            mode=mode,
            event=event,
            frame_count=frame_count,
            current_frame_idx=int(self.app.current_frame_idx),
        )
        self.app._popup.mark_popup_local_start = initial_range_start
        self.app._popup.mark_popup_local_end = initial_range_end
        self.app._popup.mark_range_start_idx = self.app._popup.mark_popup_local_start
        self.app._popup.mark_range_end_idx = self.app._popup.mark_popup_local_end
        self.app._popup.mark_popup_anchor_idx = center_idx
        self.app._popup.mark_popup_current_idx = center_idx
        self.app._popup.mark_last_full_refresh_note = ""
        self.app._popup.mark_popup_mode = mode
        self.app._popup.mark_popup_event_id = event_id

        popup = tk.Toplevel(self.app.root)
        popup.withdraw()
        self.app._popup.mark_popup = popup
        popup.title("Mark SD Event" if mode == "new" else f"Edit SD Event ({event_id})")
        popup.geometry("1200x850")
        popup.transient(self.app.root)
        apply_theme(popup)

        content = ttk.Frame(popup, padding=SPACING.outer, style="AppShell.TFrame")
        content.pack(fill="both", expand=True)

        top_row = ttk.Frame(content, style="AppShell.TFrame")
        top_row.pack(fill="x", pady=(0, 6))
        self.app._popup.mark_range_canvas = tk.Canvas(top_row, height=28, bg="#24262a", highlightthickness=0, bd=0, cursor="hand2")
        self.app._popup.mark_range_canvas.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.app._popup.mark_range_canvas.bind("<Configure>", lambda _e: self.app._redraw_popup_range_selector())
        self.app._popup.mark_range_canvas.bind("<Button-1>", self.app._popup_range_press)
        self.app._popup.mark_range_canvas.bind("<B1-Motion>", self.app._popup_range_drag)
        self.app._popup.mark_range_canvas.bind("<ButtonRelease-1>", self.app._popup_range_release)
        ttk.Button(
            top_row,
            text="Refresh Selected Range",
            command=self.app._refresh_popup_full_sequence,
            **semantic_button_options("secondary"),
        ).pack(side="right")

        self.app._popup.mark_main_view_shell = ttk.Frame(content, padding=SPACING.card, style="AppSurface.TFrame")
        self.app._popup.mark_main_view_shell.pack(fill="both", expand=True, pady=(6, 6))
        self.app._popup.mark_preview_label = ttk.Label(self.app._popup.mark_main_view_shell, anchor="center", style="AppCard.TLabel")
        self.app._popup.mark_preview_label.pack(fill="both", expand=True)

        self.app._popup.mark_mini_frame = ttk.Frame(self.app._popup.mark_main_view_shell, width=180, height=180, style="AppPreview.TFrame")
        self.app._popup.mark_mini_frame.pack_propagate(False)
        self.app._popup.mark_mini_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=12)
        self.app._popup.mark_mini_canvas = tk.Canvas(
            self.app._popup.mark_mini_frame,
            bg="black",
            width=170,
            height=170,
            highlightthickness=0,
            bd=0,
        )
        self.app._popup.mark_mini_canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.app._popup.mark_mini_grip = ttk.Label(
            self.app._popup.mark_mini_frame,
            text="\u2199",
            style="AppPreviewGrip.TLabel",
            cursor="fleur",
        )
        self.app._popup.mark_mini_grip.place(relx=0.0, rely=1.0, anchor="sw", x=6, y=-6, width=24, height=24)
        self.app._popup.mark_mini_grip.bind("<Button-1>", self.app._popup_start_resize_mini)
        self.app._popup.mark_mini_grip.bind("<B1-Motion>", self.app._popup_do_resize_mini)
        self.app._popup.mark_mini_grip.bind("<ButtonRelease-1>", self.app._popup_stop_resize_mini)

        self.app._popup.mark_frame_info_var = tk.StringVar(value="Frame: -")
        self.app._popup.mark_window_info_var = tk.StringVar(value="")
        self.app._popup.mark_loading_var = tk.StringVar(value="")
        self.app._popup.mark_contrast_var = tk.DoubleVar(value=1.0)
        self.app._popup.mark_contrast_label_var = tk.StringVar(value="Contrast: 1.00x")
        ttk.Label(content, textvariable=self.app._popup.mark_frame_info_var, style="AppDataValue.TLabel").pack(anchor="w", pady=(0, 2))
        ttk.Label(content, textvariable=self.app._popup.mark_window_info_var, style="AppMeta.TLabel").pack(anchor="w", pady=(0, 2))
        self.app._popup.mark_loading_label = ttk.Label(content, textvariable=self.app._popup.mark_loading_var, style="AppMeta.TLabel")
        self.app._popup.mark_loading_bar = ttk.Progressbar(content, mode="indeterminate", style="AppLoading.Horizontal.TProgressbar")

        self.app._popup.mark_overlay = tk.Canvas(content, height=12, bg="#2a2b2f", highlightthickness=0, bd=0)
        self.app._popup.mark_overlay.pack(fill="x", pady=(4, 2))
        self.app._popup.mark_overlay.bind("<Configure>", lambda _e: self.app._redraw_popup_overlay())

        self.app._popup.mark_scale = tk.Scale(
            content,
            from_=self.app._popup.mark_popup_local_start,
            to=self.app._popup.mark_popup_local_end,
            orient="horizontal",
            showvalue=False,
            relief="flat",
            highlightthickness=0,
            bd=0,
            bg="#1f242b",
            fg="#edf1f3",
            troughcolor="#2a3038",
            activebackground="#1b75bc",
            command=self.app._popup_on_slide,
        )
        self.app._popup.mark_scale.pack(fill="x", pady=(0, 6))

        nav_row = ttk.Frame(content, style="AppShell.TFrame")
        nav_row.pack(fill="x", pady=(4, 0))
        ttk.Button(nav_row, text="Prev", command=lambda: self.app._popup_step(-1), **semantic_button_options("secondary")).pack(side="left", padx=2)
        ttk.Button(nav_row, text="Next", command=lambda: self.app._popup_step(1), **semantic_button_options("secondary")).pack(side="left", padx=2)
        ttk.Button(nav_row, text="Set Start", command=self.app._popup_set_start_current, **semantic_button_options("secondary")).pack(side="left", padx=6)
        ttk.Button(nav_row, text="Set End", command=self.app._popup_set_end_current, **semantic_button_options("secondary")).pack(side="left", padx=2)

        baseline_row = ttk.Frame(content, padding=SPACING.card, style="AppSurface.TFrame")
        baseline_row.pack(fill="x", pady=(6, 0))
        ttk.Label(baseline_row, text="Baseline Count", style="AppSurfaceMeta.TLabel").pack(side="left")
        baseline_count_default, baseline_end_default = self._resolve_initial_baseline_state(
            mode=mode,
            event=event,
            start_default=int(start_default),
        )
        self.app._popup.mark_baseline_count_var = tk.StringVar(value=str(baseline_count_default))
        baseline_count_entry = ttk.Entry(baseline_row, textvariable=self.app._popup.mark_baseline_count_var, width=8, style="AppCompact.TEntry")
        baseline_count_entry.pack(side="left", padx=(6, 14))
        ttk.Label(baseline_row, text="Baseline End", style="AppSurfaceMeta.TLabel").pack(side="left")
        self.app._popup.mark_baseline_end_var = tk.StringVar(value=str(baseline_end_default))
        baseline_end_entry = ttk.Entry(baseline_row, textvariable=self.app._popup.mark_baseline_end_var, width=8, style="AppCompact.TEntry")
        baseline_end_entry.pack(side="left", padx=(6, 18))
        ttk.Label(baseline_row, textvariable=self.app._popup.mark_contrast_label_var, style="AppSurfaceMeta.TLabel").pack(side="left")
        ttk.Scale(
            baseline_row,
            from_=0.5,
            to=3.0,
            orient="horizontal",
            length=150,
            variable=self.app._popup.mark_contrast_var,
            command=self.app._popup_on_contrast_change,
            style="AppFlat.Horizontal.TScale",
        ).pack(side="left", padx=(8, 0))

        bounds_frame = ttk.Frame(content, style="AppShell.TFrame")
        bounds_frame.pack(fill="x")
        ttk.Label(bounds_frame, text="Start", style="AppMeta.TLabel").pack(side="left")
        self.app._popup.mark_start_var = tk.StringVar(value=str(start_default))
        start_entry = ttk.Entry(bounds_frame, textvariable=self.app._popup.mark_start_var, width=10, style="AppCompact.TEntry")
        start_entry.pack(side="left", padx=(4, 14))
        ttk.Label(bounds_frame, text="End", style="AppMeta.TLabel").pack(side="left")
        self.app._popup.mark_end_var = tk.StringVar(value=str(end_default))
        end_entry = ttk.Entry(bounds_frame, textvariable=self.app._popup.mark_end_var, width=10, style="AppCompact.TEntry")
        end_entry.pack(side="left", padx=(4, 14))
        start_entry.bind(
            "<KeyRelease>",
            lambda _e: (self.app._redraw_popup_overlay(), self.app._schedule_popup_recompute(align_baseline_to_start=True)),
        )
        end_entry.bind("<KeyRelease>", lambda _e: self.app._redraw_popup_overlay())
        start_entry.bind(
            "<Return>", lambda _e: self.app._schedule_popup_recompute(show_errors=True, align_baseline_to_start=True)
        )
        start_entry.bind(
            "<FocusOut>", lambda _e: self.app._schedule_popup_recompute(show_errors=True, align_baseline_to_start=True)
        )
        baseline_count_entry.bind("<Return>", lambda _e: self.app._schedule_popup_recompute(show_errors=True))
        baseline_end_entry.bind("<Return>", lambda _e: self.app._schedule_popup_recompute(show_errors=True))
        baseline_count_entry.bind("<FocusOut>", lambda _e: self.app._schedule_popup_recompute(show_errors=True))
        baseline_end_entry.bind("<FocusOut>", lambda _e: self.app._schedule_popup_recompute(show_errors=True))
        baseline_count_entry.bind("<KeyRelease>", lambda _e: self.app._schedule_popup_recompute())
        baseline_end_entry.bind("<KeyRelease>", lambda _e: self.app._schedule_popup_recompute())

        buttons = ttk.Frame(content, style="AppShell.TFrame")
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Confirm", command=self.confirm, **semantic_button_options("primary")).pack(side="right", padx=2)
        ttk.Button(buttons, text="Cancel", command=self.cancel, **semantic_button_options("secondary")).pack(side="right", padx=2)

        popup.protocol("WM_DELETE_WINDOW", self.cancel)
        popup.bind("<Destroy>", self.on_destroy)
        self.app._bind_popup_keys(popup)

        center_window(popup, width=1200, height=850)
        popup.deiconify()
        popup.update_idletasks()
        self._begin_popup_session(
            initial_range_start,
            initial_range_end,
            normalize_to_current_frame=(mode == "new"),
        )

    def on_destroy(self, _event=None) -> None:
        popup_ref = self.app._popup.mark_popup
        if popup_ref is not None and popup_ref.winfo_exists():
            return
        self.app._popup.engine.cancel_active()
        self.app._popup.popup_active_job_id = 0
        if self.app._popup.mark_recompute_after_id is not None and popup_ref is not None:
            try:
                popup_ref.after_cancel(self.app._popup.mark_recompute_after_id)
            except Exception:
                pass
        if self.app._popup.pending_popup_after_id is not None and popup_ref is not None:
            try:
                popup_ref.after_cancel(self.app._popup.pending_popup_after_id)
            except Exception:
                pass
        self.app._popup.mark_recompute_after_id = None
        self.app._popup.pending_popup_after_id = None
        self.app._popup.pending_popup_frame_idx = None
        self.app._popup.mark_popup = None
        self.app._popup.mark_popup_mode = None
        self.app._popup.mark_popup_event_id = None
        self.app._popup.mark_popup_anchor_idx = 0
        self.app._popup.mark_popup_image = None
        self.app._popup.mark_popup_mini_image = None
        self.app._popup.mark_start_var = None
        self.app._popup.mark_end_var = None
        self.app._popup.mark_baseline_count_var = None
        self.app._popup.mark_baseline_end_var = None
        self.app._popup.mark_contrast_var = None
        self.app._popup.mark_contrast_label_var = None
        self.app._popup.mark_frame_info_var = None
        self.app._popup.mark_window_info_var = None
        self.app._popup.mark_loading_var = None
        self.app._popup.mark_loading_label = None
        self.app._popup.mark_loading_bar = None
        self.app._popup.mark_scale = None
        self.app._popup.mark_preview_label = None
        self.app._popup.mark_overlay = None
        self.app._popup.mark_range_canvas = None
        self.app._popup.mark_range_active_handle = None
        self.app._popup.mark_range_start_idx = 0
        self.app._popup.mark_range_end_idx = 0
        self.app._popup.mark_last_full_refresh_note = ""
        self.app._popup.mark_recompute_show_errors = False
        self.app._popup.mark_main_view_shell = None
        self.app._popup.mark_mini_frame = None
        self.app._popup.mark_mini_canvas = None
        self.app._popup.mark_mini_grip = None
        self.app._popup.mark_resize_start_x = None
        self.app._popup.mark_resize_start_y = None
        self.app._popup.mark_resize_start_w = None
        self.app._popup.mark_resize_start_h = None
        self.app._popup.mark_baseline_frame = None
        self.app._popup.mark_norm_p1 = 0.0
        self.app._popup.mark_norm_p99 = 1.0
        self.app._popup.mark_processed_cache.clear()
        self.app._normalized_frame_u8_cache.clear()
        self.app._gc_runtime_caches(aggressive=False, run_python_gc=True)

    def confirm(self) -> None:
        if self.app.stack_info is None or self.app._popup.mark_popup_mode is None:
            return
        try:
            start_raw = self.app._popup.mark_start_var.get() if self.app._popup.mark_start_var is not None else ""
            end_raw = self.app._popup.mark_end_var.get() if self.app._popup.mark_end_var is not None else ""
            start = self.app._parse_frame_index(start_raw, self.app._popup.mark_popup_current_idx, "Start")
            end = self.app._parse_frame_index(end_raw, self.app._popup.mark_popup_current_idx, "End")
            start, end, changed_by_clamp, swapped = self.app._normalize_bounds(start, end)
        except ValueError as exc:
            self.app._log_warn(f"Mark popup validation failed: {exc}")
            messagebox.showwarning("Mark SD Event", str(exc), parent=self.app.root)
            return
        except Exception as exc:
            self.app._log_error(f"Mark popup failed: {exc}")
            messagebox.showwarning("Mark SD Event", str(exc), parent=self.app.root)
            return

        duration_frames = end - start + 1
        _duration_sec = self.app._duration_sec(duration_frames)
        baseline_count, _baseline_end = self.app._popup_parse_baseline_controls()

        if self.app._popup.mark_popup_mode == "edit":
            event = self.app._get_event_by_id(self.app._popup.mark_popup_event_id)
            if event is None:
                self.app._log_warn("Edit confirm failed: event not found.")
                messagebox.showwarning("SD Event", "Selected event was not found.", parent=self.app.root)
                return
            old_start = event.start_idx
            old_end = event.end_idx
            updated_flags = apply_analysis_scope_flags(
                dict(getattr(event, "flags", {}) or {}),
                event_start=int(start),
                event_end=int(end),
                baseline_pre_frames=int(baseline_count),
            )
            event = self.app.browser_controller.update_event(
                event.event_id,
                start_idx=start,
                end_idx=end,
                label=event.label,
                frame_count=int(self.app.stack_info.frame_count),
                flags=updated_flags,
            )
            self.app._sync_event_projections()
            self.app.tree.selection_set(event.event_id)
            self.app._set_active_event_id(event.event_id)
            self.app._set_status(f"Updated {event.event_id} boundaries.")
            self.app._log_info(f"Updated {event.event_id}: [{old_start}, {old_end}] -> [{start}, {end}].")
        else:
            new_flags = apply_analysis_scope_flags(
                {},
                event_start=int(start),
                event_end=int(end),
                baseline_pre_frames=int(baseline_count),
            )
            event = self.app.browser_controller.create_event(
                start_idx=start,
                end_idx=end,
                frame_count=int(self.app.stack_info.frame_count),
                flags=new_flags,
            )
            self.app._sync_event_projections()
            self.app.tree.selection_set(event.event_id)
            self.app._set_active_event_id(event.event_id)
            self.app._set_status(f"Added {event.event_id}.")
            self.app._log_info(f"Added {event.event_id}: start={start}, end={end}, duration={duration_frames} frame(s).")

        if changed_by_clamp:
            self.app._log_info("Popup values were clamped to valid frame range.")
        if swapped:
            self.app._log_info("Popup swapped start/end to keep start <= end.")

        self.app.preview_scale.set(start)
        self.app._update_preview(start)
        self.cancel()

    def cancel(self) -> None:
        if self.app._popup.mark_popup is not None and self.app._popup.mark_popup.winfo_exists():
            self.app._popup.mark_popup.destroy()

    def delete_selected_events(self) -> None:
        ids = list(self.app.tree.selection())
        if not ids:
            self.app._log_warn("Delete blocked: no events selected.")
            messagebox.showwarning("SD Event", "Select one or more events first.", parent=self.app.root)
            return

        labels: list[str] = []
        for event_id in ids:
            try:
                event = self.app.browser_controller.get_event(str(event_id))
            except Exception:
                event = None
            label = str(getattr(event, "label", "") or "").strip() if event is not None else ""
            labels.append(label or str(event_id))
        preview = ", ".join(labels[:3])
        if len(labels) > 3:
            preview = f"{preview}, +{len(labels) - 3} more"
        message = (
            f"Delete {len(ids)} event(s)?\n\n"
            f"This will remove the selected event metadata and saved analysis data.\n"
            f"Selected: {preview}"
        )
        should_delete = messagebox.askyesno("Delete Event", message, parent=self.app.root)
        if not should_delete:
            self.app._log_info("Delete canceled.")
            return

        selected = set(ids)
        deleted = self.app.browser_controller.delete_events(ids)
        self.app._sync_event_projections()
        if self.app._active_event_id() in selected:
            self.app._set_active_event_id(None)

        self.app._set_status(f"Deleted {deleted} event(s).")
        self.app._log_info(f"Deleted {deleted} event(s).")
