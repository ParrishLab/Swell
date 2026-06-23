from __future__ import annotations
import numpy as np
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk
from swell.shared.lru_cache import LRUCache
from swell.host.processing_engine import PopupProcessingEngine


class PopupWindowManager:
    def __init__(self) -> None:
        # Window
        self.mark_popup: tk.Toplevel | None = None
        self.mark_popup_mode: str | None = None
        self.mark_popup_event_id: str | None = None
        self.mark_popup_anchor_idx: int = 0
        self.mark_popup_current_idx: int = 0
        self.mark_popup_local_start: int = 0
        self.mark_popup_local_end: int = 0
        self.mark_popup_image: ImageTk.PhotoImage | None = None
        self.mark_popup_mini_image: ImageTk.PhotoImage | None = None
        # UI vars
        self.mark_start_var: tk.StringVar | None = None
        self.mark_end_var: tk.StringVar | None = None
        self.mark_baseline_count_var: tk.StringVar | None = None
        self.mark_baseline_end_var: tk.StringVar | None = None
        self.mark_contrast_var: tk.DoubleVar | None = None
        self.mark_contrast_label_var: tk.StringVar | None = None
        self.mark_frame_info_var: tk.StringVar | None = None
        self.mark_window_info_var: tk.StringVar | None = None
        # Widgets
        self.mark_scale: tk.Scale | None = None
        self.mark_preview_label: ttk.Label | None = None
        self.mark_overlay: tk.Canvas | None = None
        self.mark_range_canvas: tk.Canvas | None = None
        self.mark_range_active_handle: str | None = None
        self.mark_range_start_idx: int = 0
        self.mark_range_end_idx: int = 0
        self.mark_last_full_refresh_note: str = ""
        self.mark_loading_var: tk.StringVar | None = None
        self.mark_loading_label: ttk.Label | None = None
        self.mark_loading_bar: ttk.Progressbar | None = None
        self.mark_main_view_shell: ttk.Frame | None = None
        self.mark_mini_frame: ttk.Frame | None = None
        self.mark_mini_canvas: tk.Canvas | None = None
        self.mark_mini_grip: tk.Label | None = None
        self.mark_resize_start_x: int | None = None
        self.mark_resize_start_y: int | None = None
        self.mark_resize_start_w: int | None = None
        self.mark_resize_start_h: int | None = None
        self.mark_recompute_after_id: str | None = None
        self.mark_recompute_show_errors: bool = False
        self.mark_baseline_frame: np.ndarray | None = None
        self.mark_norm_p1: float = 0.0
        self.mark_norm_p99: float = 1.0
        self.mark_processed_cache: LRUCache[int, np.ndarray] = LRUCache(max_items=32, max_bytes=220 * 1024 * 1024, gc_min_keep=8)
        # Job tracking
        self.popup_job_seq: int = 0
        self.popup_active_job_id: int = 0
        self.engine: PopupProcessingEngine = PopupProcessingEngine(smoothed_cache_max=64, baseline_cache_max=16, norm_cache_max=32)
        # Pending updates
        self.pending_popup_frame_idx: int | None = None
        self.pending_popup_after_id: str | None = None
