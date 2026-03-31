from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

import numpy as np

from sdapp.host.dc_trace import WaveSurferH5Adapter
from sdapp.shared.trace import TimeAlignment, TraceAttachment, TraceRecord
from sdapp.shared.ui import BackgroundTaskRunner

TRACE_EVENT_SPAN_COLOR = "#c9b4f2"
TRACE_DISPLAY_LOWPASS_HZ = 10.0
TRACE_DISPLAY_TARGET_FS = 50.0
TRACE_DISPLAY_FILTER_ORDER = 4


class HostDCTraceController:
    def __init__(self, app) -> None:
        self.app = app
        self._adapter = WaveSurferH5Adapter()
        self._attachment: TraceAttachment | None = None
        self._trace_record: TraceRecord | None = None
        self._trace_time_cache: np.ndarray | None = None
        self._display_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._window = None
        self._panel_shell = None
        self._figure: Any | None = None
        self._axes = None
        self._canvas: Any | None = None
        self._cursor_artist = None
        self._panel_visible = False
        self._load_generation = 0
        self._missing_restore_warning_path = ""

    def bind_panel(self, parent) -> None:
        del parent
        self._panel_visible = False

    def import_dc_trace(self) -> None:
        if self.app.reader is None or self.app.stack_info is None:
            self.app._show_warning("Import DC Trace", "Load a stack first.")
            return
        defaults = dict(self.app.browser_controller.get_global_metrics_defaults() or {})
        if "frames_per_sec" not in defaults:
            should_open = messagebox.askyesno(
                "Import DC Trace",
                (
                    "Set Frames/sec in Open Metrics before importing a DC trace.\n\n"
                    "Open Metrics now?"
                ),
                parent=self.app.root,
            )
            if should_open:
                self.app._open_generate_metrics_popup()
            return
        selected = filedialog.askopenfilename(
            parent=self.app.root,
            title="Import DC Trace",
            initialdir=self._initial_trace_dir(),
            filetypes=[
                ("WaveSurfer files", "*.h5 *.H5 *.hdf5 *.HDF5"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        self._load_generation += 1
        generation = int(self._load_generation)
        source_path = str(Path(selected).expanduser().resolve())
        loading_dialog = self._open_loading_dialog(
            title="Import DC Trace",
            message=f"Reading metadata for {Path(source_path).name}...",
        )
        self.app._set_status("Reading DC trace metadata...")
        self.app._log_info(f"DC trace metadata read started: {source_path}.")

        self._task_runner().start(
            lambda: self._adapter.load_metadata(Path(source_path)),
            on_success=lambda metadata: self._on_metadata_load_succeeded(generation, loading_dialog, source_path, metadata),
            on_error=lambda exc: self._on_metadata_load_failed(generation, loading_dialog, exc),
        )

    def remove_dc_trace(self) -> None:
        self._load_generation += 1
        self.app.browser_controller.set_dc_trace_attachment(None)
        self.clear_runtime()
        self.app._set_status("DC trace removed.")
        self.app._log_info("Removed linked DC trace.")

    def restore_from_project_metadata(self) -> None:
        payload = self.app.browser_controller.get_dc_trace_attachment()
        attachment = TraceAttachment.from_metadata_dict(payload)
        if attachment is None:
            self.clear_runtime()
            return
        source_path = str(Path(attachment.source_path).expanduser())
        if not Path(source_path).exists():
            if self._missing_restore_warning_path != source_path:
                self._missing_restore_warning_path = source_path
                self.app._show_warning(
                    "DC Trace",
                    (
                        "The project references a DC trace file that is not available.\n\n"
                        f"Missing file:\n{source_path}\n\n"
                        "The trace panel will stay hidden until you reimport or remove the DC trace."
                    ),
                )
            self.clear_runtime()
            return
        self._load_attachment_async(
            attachment,
            persist_on_success=False,
            failure_title="DC Trace",
            missing_path_warning=True,
        )

    def clear_runtime(self) -> None:
        self._attachment = None
        self._trace_record = None
        self._trace_time_cache = None
        self._display_cache.clear()
        self._cursor_artist = None
        self._set_panel_visible(False)
        axes = self._axes
        if axes is not None:
            axes.clear()
        if self._canvas is not None:
            try:
                self._canvas.draw_idle()
            except Exception:
                pass

    def update_for_frame(self, frame_idx: int) -> None:
        if self._trace_record is None or self._attachment is None:
            return
        self._update_cursor(frame_idx)

    def on_events_changed(self) -> None:
        if self._trace_record is None or self._attachment is None:
            return
        self.refresh_plot()

    def get_trace_time_for_frame(self, frame_idx: int) -> float | None:
        fps = self._frames_per_sec()
        if fps is None or fps <= 0 or self._attachment is None:
            return None
        return (float(frame_idx) / float(fps)) + float(self._attachment.alignment.offset_s)

    def get_frame_for_trace_time(self, t_s: float) -> int | None:
        fps = self._frames_per_sec()
        if fps is None or fps <= 0 or self.app.stack_info is None or self._attachment is None:
            return None
        frame = int(round((float(t_s) - float(self._attachment.alignment.offset_s)) * float(fps)))
        return max(0, min(int(self.app.stack_info.frame_count) - 1, frame))

    def get_trace_window(self, t0_s: float, t1_s: float) -> np.ndarray:
        record = self._trace_record
        times = self._trace_times()
        if record is None or times is None:
            return np.array([], dtype=np.float64)
        left = float(min(t0_s, t1_s))
        right = float(max(t0_s, t1_s))
        lo = int(np.searchsorted(times, left, side="left"))
        hi = int(np.searchsorted(times, right, side="right"))
        if hi <= lo:
            return np.array([], dtype=np.float64)
        return np.asarray(record.signals[lo:hi, 0], dtype=np.float64)

    def get_trace_value_at_frame(self, frame_idx: int) -> float | None:
        record = self._trace_record
        times = self._trace_times()
        trace_time = self.get_trace_time_for_frame(frame_idx)
        if record is None or times is None or trace_time is None or times.size <= 0:
            return None
        idx = int(np.searchsorted(times, trace_time, side="left"))
        idx = max(0, min(int(times.size) - 1, idx))
        return float(np.asarray(record.signals[idx, 0], dtype=np.float64))

    def _load_attachment_async(
        self,
        attachment: TraceAttachment,
        *,
        persist_on_success: bool,
        failure_title: str,
        missing_path_warning: bool,
    ) -> None:
        self._load_generation += 1
        generation = int(self._load_generation)
        self.app._set_status("Loading DC trace...")
        self.app._log_info(
            f"DC trace load started: {attachment.source_path} [channel={attachment.channel_name}, offset={attachment.alignment.offset_s:.6g}s]."
        )

        self._task_runner().start(
            lambda: self._adapter.load_trace(Path(attachment.source_path), attachment.channel_index),
            on_success=lambda record: self._on_load_succeeded(
                generation,
                attachment,
                record,
                persist_on_success=persist_on_success,
            ),
            on_error=lambda exc: self._on_load_failed(
                generation,
                attachment,
                exc,
                failure_title=failure_title,
                missing_path_warning=missing_path_warning,
            ),
        )

    def _on_metadata_load_failed(self, generation: int, loading_dialog, exc: Exception) -> None:
        self._close_loading_dialog(loading_dialog)
        if generation != self._load_generation:
            return
        self.app._show_warning("Import DC Trace", f"Unable to read DC trace metadata:\n{exc}")
        self.app._set_status("DC trace metadata read failed.")
        self.app._log_error(f"DC trace metadata read failed: {exc}")

    def _on_metadata_load_succeeded(
        self,
        generation: int,
        loading_dialog,
        source_path: str,
        metadata: dict[str, object],
    ) -> None:
        self._close_loading_dialog(loading_dialog)
        if generation != self._load_generation:
            return
        self.app._set_status("DC trace metadata ready.")
        self.app._log_info(f"DC trace metadata read completed: {source_path}.")
        dialog_result = self._open_import_dialog(metadata)
        if dialog_result is None:
            self.app._log_info("DC trace import canceled from dialog.")
            return
        channel_index, offset_s = dialog_result
        attachment = TraceAttachment(
            source_type=self._adapter.source_type,
            source_path=str(Path(source_path).expanduser().resolve()),
            channel_index=int(channel_index),
            channel_name=str(list(metadata.get("channel_names") or [])[int(channel_index)]),
            sample_rate_hz=(
                None if metadata.get("sample_rate_hz") is None else float(metadata.get("sample_rate_hz"))
            ),
            unit=str(list(metadata.get("units") or [""])[int(channel_index)]),
            alignment=TimeAlignment(mode="manual_offset", offset_s=float(offset_s)),
            metadata={
                "duration_s": metadata.get("duration_s"),
                "sweep_count": metadata.get("sweep_count"),
            },
        )
        self._load_attachment_async(
            attachment,
            persist_on_success=True,
            failure_title="Import DC Trace",
            missing_path_warning=False,
        )

    def _on_load_succeeded(
        self,
        generation: int,
        attachment: TraceAttachment,
        record: TraceRecord,
        *,
        persist_on_success: bool,
    ) -> None:
        if generation != self._load_generation:
            return
        self._missing_restore_warning_path = ""
        self._attachment = attachment
        self._trace_record = record
        self._trace_time_cache = None
        self._display_cache.clear()
        if persist_on_success:
            self.app.browser_controller.set_dc_trace_attachment(attachment.to_metadata_dict())
        self._set_panel_visible(True)
        self.refresh_plot(frame_idx=getattr(self.app, "current_frame_idx", 0))
        self.app._set_status(f"Loaded DC trace: {Path(attachment.source_path).name}")
        self.app._log_info(
            f"DC trace load completed: {Path(attachment.source_path).name}, channel={attachment.channel_name}."
        )

    def _on_load_failed(
        self,
        generation: int,
        attachment: TraceAttachment,
        exc: Exception,
        *,
        failure_title: str,
        missing_path_warning: bool,
    ) -> None:
        if generation != self._load_generation:
            return
        self.clear_runtime()
        message = str(exc)
        if missing_path_warning and "No such file" in message:
            self.app._show_warning(
                failure_title,
                (
                    "Unable to restore the project DC trace because the source file is unavailable.\n\n"
                    f"{attachment.source_path}"
                ),
            )
        else:
            self.app._show_warning(failure_title, f"Failed to load DC trace:\n{exc}")
        self.app._set_status("DC trace load failed.")
        self.app._log_error(f"DC trace load failed: {exc}")

    def _open_import_dialog(self, metadata: dict[str, object]) -> tuple[int, float] | None:
        dialog = tk.Toplevel(self.app.root)
        dialog.title("Import DC Trace")
        dialog.transient(self.app.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        shell = ttk.Frame(dialog, padding=12)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text=f"File: {Path(str(metadata.get('source_path', ''))).name}").pack(anchor="w")
        ttk.Label(
            shell,
            text=(
                f"Sweeps: {int(metadata.get('sweep_count', 0) or 0)}    "
                f"Sample rate: {self._format_float(metadata.get('sample_rate_hz'))} Hz    "
                f"Duration: {self._format_float(metadata.get('duration_s'))} s"
            ),
        ).pack(anchor="w", pady=(4, 8))

        channel_names = list(metadata.get("channel_names") or [])
        channel_var = tk.StringVar(value=str(channel_names[0] if channel_names else ""))
        channel_name_var = tk.StringVar(value=str(channel_names[0] if channel_names else ""))
        offset_var = tk.StringVar(value="0")
        row = ttk.Frame(shell)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Channel").pack(side="left")
        combo = ttk.Combobox(row, textvariable=channel_var, values=channel_names, state="readonly", width=28)
        if len(channel_names) <= 1:
            combo.state(["disabled"])
        combo.pack(side="left", padx=(8, 0))

        units = list(metadata.get("units") or [])
        unit_var = tk.StringVar(value=str(units[0] if units else ""))

        def _selected_channel_index() -> int:
            try:
                idx = channel_names.index(str(channel_var.get()))
            except ValueError:
                idx = 0
            return max(0, min(max(0, len(channel_names) - 1), idx))

        def _sync_channel_preview(*_args) -> None:
            idx = _selected_channel_index()
            channel_name_var.set(str(channel_names[idx] if idx < len(channel_names) else f"Channel {idx + 1}"))
            unit_var.set(str(units[idx] if idx < len(units) else ""))

        combo.bind("<<ComboboxSelected>>", _sync_channel_preview, add="+")
        ttk.Label(shell, textvariable=channel_name_var).pack(anchor="w", pady=(0, 2))
        ttk.Label(shell, textvariable=unit_var).pack(anchor="w", pady=(0, 8))

        offset_row = ttk.Frame(shell)
        offset_row.pack(fill="x", pady=(0, 8))
        ttk.Label(offset_row, text="Trace time at video frame 0 (s)").pack(side="left")
        ttk.Entry(offset_row, textvariable=offset_var, width=12).pack(side="left", padx=(8, 0))

        result: dict[str, object] = {}

        def _cancel() -> None:
            dialog.destroy()

        def _apply() -> None:
            channel_index = _selected_channel_index()
            try:
                offset_s = float(str(offset_var.get()).strip())
            except (TypeError, ValueError):
                self.app._show_warning("Import DC Trace", "Trace time at video frame 0 must be a number.")
                return
            result["channel_index"] = int(channel_index)
            result["offset_s"] = float(offset_s)
            dialog.destroy()

        actions = ttk.Frame(shell)
        actions.pack(fill="x")
        ttk.Button(actions, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(actions, text="Import", command=_apply).pack(side="right", padx=(0, 8))
        dialog.wait_window()
        if "channel_index" not in result:
            return None
        return int(result["channel_index"]), float(result["offset_s"])

    def _open_loading_dialog(self, *, title: str, message: str):
        dialog = tk.Toplevel(self.app.root)
        dialog.title(title)
        dialog.transient(self.app.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        shell = ttk.Frame(dialog, padding=12)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text=message).pack(anchor="w", pady=(0, 8))
        bar = ttk.Progressbar(shell, mode="indeterminate", length=260)
        bar.pack(fill="x")
        bar.start(10)
        return dialog

    @staticmethod
    def _close_loading_dialog(dialog) -> None:
        if dialog is None:
            return
        try:
            if bool(dialog.winfo_exists()):
                dialog.destroy()
        except Exception:
            return

    def refresh_plot(self, *, frame_idx: int | None = None) -> None:
        if not self._panel_visible or self._trace_record is None or self._attachment is None:
            return
        axes = self._axes
        canvas = self._canvas
        shell = self._panel_shell
        if axes is None or canvas is None or shell is None:
            return
        times = self._trace_times()
        if times is None or times.size <= 0:
            return
        view_bounds = self._ios_time_bounds()
        visible_times, visible_signal = self._display_trace_window(view_bounds)
        if visible_times.size <= 0 or visible_signal.size <= 0:
            return
        width = max(200, int(shell.winfo_width() or 0))
        plot_x, plot_y = self._display_data_for_series(width, visible_times, visible_signal)
        axes.clear()
        axes.plot(plot_x, plot_y, color="#1f2937", linewidth=1.0)
        for event in list(getattr(self.app, "events", []) or []):
            start_t = self.get_trace_time_for_frame(int(event.start_idx))
            end_t = self.get_trace_time_for_frame(int(event.end_idx))
            if start_t is None or end_t is None:
                continue
            axes.axvspan(start_t, end_t, color=TRACE_EVENT_SPAN_COLOR, alpha=0.45)
        for segment in list(self._trace_record.segments or [])[1:]:
            boundary_idx = int(segment[0])
            if boundary_idx <= 0 or boundary_idx >= int(times.size):
                continue
            axes.axvline(float(times[boundary_idx]), color="#9aa3af", linewidth=0.8, linestyle="--", alpha=0.7)
        unit = str(self._attachment.unit or "").strip()
        ylabel = unit if unit else "Signal"
        axes.set_xlabel("Trace time (s)")
        axes.set_ylabel(ylabel)
        axes.grid(True, color="#d5d8de", linewidth=0.6)
        if view_bounds is not None:
            axes.set_xlim(float(view_bounds[0]), float(view_bounds[1]))
        else:
            axes.set_xlim(
                float(visible_times[0]),
                float(visible_times[-1] if visible_times.size > 1 else visible_times[0] + 1.0),
            )
        y_min = float(np.nanmin(visible_signal))
        y_max = float(np.nanmax(visible_signal))
        if abs(y_max - y_min) < 1e-12:
            pad = 1.0 if abs(y_max) < 1e-12 else abs(y_max) * 0.1
            y_min -= pad
            y_max += pad
        axes.set_ylim(y_min, y_max)
        axes.set_title(f"{self._attachment.channel_name} ({Path(self._attachment.source_path).name})", fontsize=9)
        figure = self._figure
        if figure is not None:
            figure.tight_layout(pad=1.1)
        current_frame = int(self.app.current_frame_idx if frame_idx is None else frame_idx)
        cursor_t = self.get_trace_time_for_frame(current_frame)
        self._cursor_artist = None
        if cursor_t is not None:
            self._cursor_artist = axes.axvline(float(cursor_t), color="#dc2626", linewidth=1.2)
        canvas.draw_idle()

    def _update_cursor(self, frame_idx: int) -> None:
        if not self._panel_visible or self._attachment is None:
            return
        canvas = self._canvas
        artist = self._cursor_artist
        if canvas is None or artist is None:
            self.refresh_plot(frame_idx=frame_idx)
            return
        cursor_t = self.get_trace_time_for_frame(int(frame_idx))
        if cursor_t is None:
            return
        try:
            artist.set_xdata([float(cursor_t), float(cursor_t)])
            canvas.draw_idle()
        except Exception:
            self.refresh_plot(frame_idx=frame_idx)

    def _display_data_for_series(
        self,
        width_px: int,
        times: np.ndarray,
        signal: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        cache_key = (int(width_px), int(signal.size), float(times[0]), float(times[-1]))
        cached = self._display_cache.get(cache_key)
        if cached is not None:
            return cached
        if signal.size <= max(1000, int(width_px) * 2):
            data = (times, signal)
            self._display_cache[cache_key] = data
            return data
        bucket_count = max(1, int(width_px))
        edges = np.linspace(0, signal.size, bucket_count + 1, dtype=int)
        x_out: list[float] = []
        y_out: list[float] = []
        for left, right in zip(edges[:-1], edges[1:]):
            hi = max(int(right), int(left) + 1)
            segment = signal[int(left):hi]
            segment_times = times[int(left):hi]
            if segment.size <= 0:
                continue
            min_idx = int(np.argmin(segment))
            max_idx = int(np.argmax(segment))
            points = sorted({min_idx, max_idx})
            for idx in points:
                x_out.append(float(segment_times[idx]))
                y_out.append(float(segment[idx]))
        data = (np.asarray(x_out, dtype=np.float64), np.asarray(y_out, dtype=np.float64))
        self._display_cache[cache_key] = data
        return data

    def _ios_time_bounds(self) -> tuple[float, float] | None:
        stack_info = getattr(self.app, "stack_info", None)
        fps = self._frames_per_sec()
        if stack_info is None or fps is None or fps <= 0:
            return None
        frame_count = int(getattr(stack_info, "frame_count", 0) or 0)
        if frame_count <= 0:
            return None
        start_t = self.get_trace_time_for_frame(0)
        end_t = self.get_trace_time_for_frame(max(0, frame_count - 1))
        if start_t is None or end_t is None:
            return None
        left = float(min(start_t, end_t))
        right = float(max(start_t, end_t))
        if abs(right - left) < 1e-12:
            right = left + (1.0 / float(fps))
        return left, right

    def _visible_trace_window(self, bounds: tuple[float, float] | None) -> tuple[np.ndarray, np.ndarray]:
        times = self._trace_times()
        record = self._trace_record
        if times is None or record is None:
            return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        signal = np.asarray(record.signals[:, 0], dtype=np.float64)
        if bounds is None:
            return times, signal
        left, right = float(bounds[0]), float(bounds[1])
        lo = int(np.searchsorted(times, left, side="left"))
        hi = int(np.searchsorted(times, right, side="right"))
        if hi <= lo:
            return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        return times[lo:hi], signal[lo:hi]

    def _display_trace_window(self, bounds: tuple[float, float] | None) -> tuple[np.ndarray, np.ndarray]:
        times, signal = self._visible_trace_window(bounds)
        record = self._trace_record
        if record is None or times.size <= 0 or signal.size <= 0:
            return times, signal
        sample_rate = float(record.sample_rate_hz or 0.0)
        if sample_rate <= 0:
            return times, signal
        ds_factor = max(1, int(round(sample_rate / TRACE_DISPLAY_TARGET_FS)))
        display_sample_rate = sample_rate / float(ds_factor)
        cutoff_hz = min(TRACE_DISPLAY_LOWPASS_HZ, 0.45 * display_sample_rate)
        filtered = np.asarray(signal, dtype=np.float64)
        if cutoff_hz > 0 and sample_rate > (2.0 * cutoff_hz) and filtered.size > 32:
            try:
                from scipy import signal as scipy_signal

                sos = scipy_signal.butter(
                    TRACE_DISPLAY_FILTER_ORDER,
                    cutoff_hz,
                    btype="low",
                    fs=sample_rate,
                    output="sos",
                )
                filtered = scipy_signal.sosfiltfilt(sos, filtered).astype(np.float64, copy=False)
            except Exception:
                filtered = np.asarray(signal, dtype=np.float64)
        if ds_factor > 1:
            return times[::ds_factor], filtered[::ds_factor]
        return times, filtered

    def _trace_times(self) -> np.ndarray | None:
        if self._trace_record is None:
            return None
        if self._trace_time_cache is not None:
            return self._trace_time_cache
        record = self._trace_record
        if record.timestamps_s is not None:
            times = np.asarray(record.timestamps_s, dtype=np.float64).reshape(-1)
        else:
            if record.sample_rate_hz is None or float(record.sample_rate_hz) <= 0:
                return None
            start_time = 0.0 if record.start_time_s is None else float(record.start_time_s)
            times = start_time + (np.arange(record.signals.shape[0], dtype=np.float64) / float(record.sample_rate_hz))
        self._trace_time_cache = times
        return times

    def _frames_per_sec(self) -> float | None:
        defaults = dict(self.app.browser_controller.get_global_metrics_defaults() or {})
        raw = defaults.get("frames_per_sec")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _task_runner(self) -> BackgroundTaskRunner:
        runner = getattr(self.app, "_background_task_runner", None)
        if isinstance(runner, BackgroundTaskRunner):
            return runner
        runner = BackgroundTaskRunner(self.app.root)
        self.app._background_task_runner = runner
        return runner

    def _set_panel_visible(self, visible: bool) -> None:
        if bool(visible):
            self._ensure_window()
            window = self._window
            if window is None:
                return
            if not self._panel_visible:
                try:
                    window.deiconify()
                    window.lift()
                    window.focus_force()
                except Exception:
                    pass
                self._panel_visible = True
            return
        window = self._window
        if self._panel_visible and window is not None:
            try:
                window.withdraw()
            except Exception:
                pass
            self._panel_visible = False

    def _ensure_window(self) -> None:
        if self._window is not None and self._panel_shell is not None and self._canvas is not None:
            return
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        window = tk.Toplevel(self.app.root)
        window.title("DC Trace")
        window.geometry("980x360")
        window.minsize(760, 320)
        window.withdraw()
        window.protocol("WM_DELETE_WINDOW", self._on_window_closed)
        shell = ttk.Frame(window, padding=8)
        shell.pack(fill="both", expand=True)
        figure = Figure(figsize=(9.0, 2.6), dpi=100)
        axes = figure.add_subplot(111)
        figure.subplots_adjust(left=0.08, right=0.985, top=0.90, bottom=0.24)
        axes.grid(True, color="#d5d8de", linewidth=0.6)
        axes.set_xlabel("Trace time (s)")
        axes.set_ylabel("Signal")
        axes.tick_params(labelsize=8)
        canvas = FigureCanvasTkAgg(figure, master=shell)
        widget = canvas.get_tk_widget()
        widget.pack(fill="both", expand=True)
        canvas.mpl_connect("button_press_event", self._on_plot_click)
        widget.bind("<Configure>", lambda _event: self.refresh_plot(), add="+")
        self._window = window
        self._panel_shell = shell
        self._figure = figure
        self._axes = axes
        self._canvas = canvas

    def _on_window_closed(self) -> None:
        window = self._window
        if window is None:
            return
        try:
            window.withdraw()
        except Exception:
            pass
        self._panel_visible = False

    def _on_plot_click(self, event) -> None:
        if event is None or getattr(event, "inaxes", None) is None:
            return
        if getattr(event, "xdata", None) is None:
            return
        target = self.get_frame_for_trace_time(float(event.xdata))
        if target is None:
            return
        self.app.preview_scale.set(target)
        self.app._update_preview(target)
        self.app._log_info(f"DC trace click: jumped to frame {target}.")

    def _initial_trace_dir(self) -> str:
        payload = self.app.browser_controller.get_dc_trace_attachment()
        attachment = TraceAttachment.from_metadata_dict(payload)
        if attachment is not None:
            candidate = Path(attachment.source_path).expanduser()
            if candidate.exists():
                return str(candidate.parent.resolve())
        stack_info = getattr(self.app, "stack_info", None)
        if stack_info is not None:
            stack_dir = Path(str(getattr(stack_info, "input_dir", "") or "")).expanduser()
            if stack_dir.exists():
                return str(stack_dir.resolve())
        return str(Path.cwd())

    @staticmethod
    def _format_float(value) -> str:
        try:
            return f"{float(value):.6g}"
        except (TypeError, ValueError):
            return "-"
