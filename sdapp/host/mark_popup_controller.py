from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class MarkPopupController:
    """Owns popup lifecycle entrypoints while sd_gui keeps rendering/math helpers."""

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

    def open_popup(self, mode: str, event_id: str | None) -> None:
        if self.app.reader is None or self.app.stack_info is None:
            self.app._log_warn("Mark popup blocked: no stack loaded.")
            messagebox.showwarning("Mark SD Event", "Load a stack first.")
            return

        if self.app._mark_popup is not None and self.app._mark_popup.winfo_exists():
            self.app._mark_popup.focus_force()
            self.app._mark_popup.lift()
            return

        event = self.app._get_event_by_id(event_id) if event_id else None
        if mode == "edit" and event is None:
            self.app._log_warn("Edit popup blocked: selected event not found.")
            messagebox.showwarning("SD Event", "Selected event was not found.")
            return

        if mode == "edit" and event is not None:
            center_idx = int((event.start_idx + event.end_idx) // 2)
            start_default = event.start_idx
            end_default = event.end_idx
        else:
            center_idx = int(self.app.current_frame_idx)
            start_default = center_idx
            end_default = center_idx

        frame_count = int(self.app.stack_info.frame_count)
        self.app._mark_popup_local_start = max(0, center_idx - 100)
        self.app._mark_popup_local_end = min(frame_count - 1, center_idx + 100)
        self.app._mark_range_start_idx = self.app._mark_popup_local_start
        self.app._mark_range_end_idx = self.app._mark_popup_local_end
        self.app._mark_popup_anchor_idx = center_idx
        self.app._mark_popup_current_idx = center_idx
        self.app._mark_last_full_refresh_note = ""
        self.app._mark_popup_mode = mode
        self.app._mark_popup_event_id = event_id

        popup = tk.Toplevel(self.app.root)
        self.app._mark_popup = popup
        popup.title("Mark SD Event" if mode == "new" else f"Edit SD Event ({event_id})")
        popup.geometry("1200x850")
        popup.transient(self.app.root)

        content = ttk.Frame(popup, padding=8)
        content.pack(fill="both", expand=True)

        top_row = ttk.Frame(content)
        top_row.pack(fill="x", pady=(0, 6))
        self.app._mark_range_canvas = tk.Canvas(top_row, height=28, bg="#24262a", highlightthickness=0, bd=0, cursor="hand2")
        self.app._mark_range_canvas.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.app._mark_range_canvas.bind("<Configure>", lambda _e: self.app._redraw_popup_range_selector())
        self.app._mark_range_canvas.bind("<Button-1>", self.app._popup_range_press)
        self.app._mark_range_canvas.bind("<B1-Motion>", self.app._popup_range_drag)
        self.app._mark_range_canvas.bind("<ButtonRelease-1>", self.app._popup_range_release)
        ttk.Button(top_row, text="Refresh Selected Range", command=self.app._refresh_popup_full_sequence).pack(side="right")

        self.app._mark_main_view_shell = ttk.Frame(content)
        self.app._mark_main_view_shell.pack(fill="both", expand=True, pady=(6, 6))
        self.app._mark_preview_label = ttk.Label(self.app._mark_main_view_shell, anchor="center")
        self.app._mark_preview_label.pack(fill="both", expand=True)

        self.app._mark_mini_frame = ttk.Frame(self.app._mark_main_view_shell, width=180, height=180)
        self.app._mark_mini_frame.pack_propagate(False)
        self.app._mark_mini_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=12)
        self.app._mark_mini_canvas = tk.Canvas(
            self.app._mark_mini_frame,
            bg="black",
            width=170,
            height=170,
            highlightthickness=1,
            highlightbackground="gray",
        )
        self.app._mark_mini_canvas.pack(fill="both", expand=True)
        self.app._mark_mini_grip = tk.Label(
            self.app._mark_mini_frame,
            text="\u2199",
            font=("Arial", 15),
            cursor="fleur",
            bg="#444",
            fg="white",
        )
        self.app._mark_mini_grip.place(relx=0.0, rely=1.0, anchor="sw", width=24, height=24)
        self.app._mark_mini_grip.bind("<Button-1>", self.app._popup_start_resize_mini)
        self.app._mark_mini_grip.bind("<B1-Motion>", self.app._popup_do_resize_mini)
        self.app._mark_mini_grip.bind("<ButtonRelease-1>", self.app._popup_stop_resize_mini)

        self.app._mark_frame_info_var = tk.StringVar(value="Frame: -")
        self.app._mark_window_info_var = tk.StringVar(value="")
        self.app._mark_loading_var = tk.StringVar(value="")
        self.app._mark_contrast_var = tk.DoubleVar(value=1.0)
        self.app._mark_contrast_label_var = tk.StringVar(value="Contrast: 1.00x")
        ttk.Label(content, textvariable=self.app._mark_frame_info_var).pack(anchor="w", pady=(0, 2))
        ttk.Label(content, textvariable=self.app._mark_window_info_var).pack(anchor="w", pady=(0, 2))
        self.app._mark_loading_label = ttk.Label(content, textvariable=self.app._mark_loading_var, foreground="#8fdcff")
        self.app._mark_loading_bar = ttk.Progressbar(content, mode="indeterminate")

        self.app._mark_overlay = tk.Canvas(content, height=12, bg="#2a2b2f", highlightthickness=0, bd=0)
        self.app._mark_overlay.pack(fill="x", pady=(4, 2))
        self.app._mark_overlay.bind("<Configure>", lambda _e: self.app._redraw_popup_overlay())

        self.app._mark_scale = tk.Scale(
            content,
            from_=self.app._mark_popup_local_start,
            to=self.app._mark_popup_local_end,
            orient="horizontal",
            showvalue=False,
            relief="flat",
            highlightthickness=0,
            command=self.app._popup_on_slide,
        )
        self.app._mark_scale.pack(fill="x", pady=(0, 6))

        nav_row = ttk.Frame(content)
        nav_row.pack(fill="x", pady=(4, 0))
        ttk.Button(nav_row, text="Prev", command=lambda: self.app._popup_step(-1)).pack(side="left", padx=2)
        ttk.Button(nav_row, text="Next", command=lambda: self.app._popup_step(1)).pack(side="left", padx=2)
        ttk.Button(nav_row, text="Set Start", command=self.app._popup_set_start_current).pack(side="left", padx=6)
        ttk.Button(nav_row, text="Set End", command=self.app._popup_set_end_current).pack(side="left", padx=2)

        baseline_row = ttk.Frame(content)
        baseline_row.pack(fill="x", pady=(6, 0))
        ttk.Label(baseline_row, text="Baseline Count").pack(side="left")
        baseline_count_default = 30
        baseline_end_default = max(0, self.app._mark_popup_anchor_idx - 1)
        self.app._mark_baseline_count_var = tk.StringVar(value=str(baseline_count_default))
        baseline_count_entry = ttk.Entry(baseline_row, textvariable=self.app._mark_baseline_count_var, width=8)
        baseline_count_entry.pack(side="left", padx=(6, 14))
        ttk.Label(baseline_row, text="Baseline End").pack(side="left")
        self.app._mark_baseline_end_var = tk.StringVar(value=str(baseline_end_default))
        baseline_end_entry = ttk.Entry(baseline_row, textvariable=self.app._mark_baseline_end_var, width=8)
        baseline_end_entry.pack(side="left", padx=(6, 18))
        ttk.Label(baseline_row, textvariable=self.app._mark_contrast_label_var).pack(side="left")
        ttk.Scale(
            baseline_row,
            from_=0.5,
            to=3.0,
            orient="horizontal",
            length=150,
            variable=self.app._mark_contrast_var,
            command=self.app._popup_on_contrast_change,
        ).pack(side="left", padx=(8, 0))

        bounds_frame = ttk.Frame(content)
        bounds_frame.pack(fill="x")
        ttk.Label(bounds_frame, text="Start").pack(side="left")
        self.app._mark_start_var = tk.StringVar(value=str(start_default))
        start_entry = ttk.Entry(bounds_frame, textvariable=self.app._mark_start_var, width=10)
        start_entry.pack(side="left", padx=(4, 14))
        ttk.Label(bounds_frame, text="End").pack(side="left")
        self.app._mark_end_var = tk.StringVar(value=str(end_default))
        end_entry = ttk.Entry(bounds_frame, textvariable=self.app._mark_end_var, width=10)
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

        buttons = ttk.Frame(content)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Confirm", command=self.confirm).pack(side="right", padx=2)
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right", padx=2)

        popup.protocol("WM_DELETE_WINDOW", self.cancel)
        popup.bind("<Destroy>", self.on_destroy)
        self.app._bind_popup_keys(popup)

        popup.update_idletasks()
        self.app._redraw_popup_range_selector()
        if self.app._mark_scale is not None:
            self.app._mark_scale.set(center_idx)
        popup.after_idle(
            lambda: self.app._recompute_popup_pipeline_for_bounds(
                self.app._mark_popup_local_start,
                self.app._mark_popup_local_end,
                show_errors=False,
                loading_text="Computing selected range...",
            )
        )

    def on_destroy(self, _event=None) -> None:
        popup_ref = self.app._mark_popup
        if popup_ref is not None and popup_ref.winfo_exists():
            return
        self.app._popup_engine.cancel_active()
        self.app._popup_active_job_id = 0
        if self.app._mark_recompute_after_id is not None and popup_ref is not None:
            try:
                popup_ref.after_cancel(self.app._mark_recompute_after_id)
            except Exception:
                pass
        if self.app._pending_popup_after_id is not None and popup_ref is not None:
            try:
                popup_ref.after_cancel(self.app._pending_popup_after_id)
            except Exception:
                pass
        self.app._mark_recompute_after_id = None
        self.app._pending_popup_after_id = None
        self.app._pending_popup_frame_idx = None
        self.app._mark_popup = None
        self.app._mark_popup_mode = None
        self.app._mark_popup_event_id = None
        self.app._mark_popup_anchor_idx = 0
        self.app._mark_popup_image = None
        self.app._mark_popup_mini_image = None
        self.app._mark_start_var = None
        self.app._mark_end_var = None
        self.app._mark_baseline_count_var = None
        self.app._mark_baseline_end_var = None
        self.app._mark_contrast_var = None
        self.app._mark_contrast_label_var = None
        self.app._mark_frame_info_var = None
        self.app._mark_window_info_var = None
        self.app._mark_loading_var = None
        self.app._mark_loading_label = None
        self.app._mark_loading_bar = None
        self.app._mark_scale = None
        self.app._mark_preview_label = None
        self.app._mark_overlay = None
        self.app._mark_range_canvas = None
        self.app._mark_range_active_handle = None
        self.app._mark_range_start_idx = 0
        self.app._mark_range_end_idx = 0
        self.app._mark_last_full_refresh_note = ""
        self.app._mark_recompute_show_errors = False
        self.app._mark_main_view_shell = None
        self.app._mark_mini_frame = None
        self.app._mark_mini_canvas = None
        self.app._mark_mini_grip = None
        self.app._mark_resize_start_x = None
        self.app._mark_resize_start_y = None
        self.app._mark_resize_start_w = None
        self.app._mark_resize_start_h = None
        self.app._mark_baseline_frame = None
        self.app._mark_norm_p1 = 0.0
        self.app._mark_norm_p99 = 1.0
        self.app._mark_processed_cache.clear()
        self.app._mini_raw_u8_cache.clear()
        self.app._gc_runtime_caches(aggressive=False, run_python_gc=True)

    def confirm(self) -> None:
        if self.app.stack_info is None or self.app._mark_popup_mode is None:
            return
        try:
            start_raw = self.app._mark_start_var.get() if self.app._mark_start_var is not None else ""
            end_raw = self.app._mark_end_var.get() if self.app._mark_end_var is not None else ""
            start = self.app._parse_frame_index(start_raw, self.app._mark_popup_current_idx, "Start")
            end = self.app._parse_frame_index(end_raw, self.app._mark_popup_current_idx, "End")
            start, end, changed_by_clamp, swapped = self.app._normalize_bounds(start, end)
        except ValueError as exc:
            self.app._log_warn(f"Mark popup validation failed: {exc}")
            messagebox.showwarning("Mark SD Event", str(exc))
            return
        except Exception as exc:
            self.app._log_error(f"Mark popup failed: {exc}")
            messagebox.showwarning("Mark SD Event", str(exc))
            return

        duration_frames = end - start + 1
        _duration_sec = self.app._duration_sec(duration_frames)

        if self.app._mark_popup_mode == "edit":
            event = self.app._get_event_by_id(self.app._mark_popup_event_id)
            if event is None:
                self.app._log_warn("Edit confirm failed: event not found.")
                messagebox.showwarning("SD Event", "Selected event was not found.")
                return
            old_start = event.start_idx
            old_end = event.end_idx
            event = self.app.browser_controller.update_event(
                event.event_id,
                start_idx=start,
                end_idx=end,
                label=event.label,
                frame_count=int(self.app.stack_info.frame_count),
            )
            self.app._sync_event_projections()
            self.app.tree.selection_set(event.event_id)
            self.app._set_active_event_id(event.event_id)
            self.app._set_status(f"Updated {event.event_id} boundaries.")
            self.app._log_info(f"Updated {event.event_id}: [{old_start}, {old_end}] -> [{start}, {end}].")
        else:
            event = self.app.browser_controller.create_event(
                start_idx=start,
                end_idx=end,
                frame_count=int(self.app.stack_info.frame_count),
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
        if self.app._mark_popup is not None and self.app._mark_popup.winfo_exists():
            self.app._mark_popup.destroy()

    def delete_selected_events(self) -> None:
        ids = list(self.app.tree.selection())
        if not ids:
            self.app._log_warn("Delete blocked: no events selected.")
            messagebox.showwarning("SD Event", "Select one or more events first.")
            return

        selected = set(ids)
        deleted = self.app.browser_controller.delete_events(ids)
        self.app._sync_event_projections()
        if self.app._active_event_id() in selected:
            self.app._set_active_event_id(None)

        self.app._set_status(f"Deleted {deleted} event(s).")
        self.app._log_info(f"Deleted {deleted} event(s).")
