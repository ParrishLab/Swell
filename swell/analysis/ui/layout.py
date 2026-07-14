from __future__ import annotations

import sys
import tkinter as tk

from PIL import Image, ImageTk

from swell.shared.ui.theme import APP_COLORS, CANVAS_BACKGROUND, SLIDER_OVERLAY_BACKGROUND, SPACING, apply_theme
from swell.analysis.ui.tooltips import TooltipManager
from swell.analysis.ui.widgets import build_preview_overlay
from swell.shared.utils.paths import get_resources_root
from swell.analysis.core.region_tools import REGION_EXCLUDE_TOOL, REGION_INCLUDE_TOOL, is_region_tool_mode
from swell.shared.ui.bootstrap import semantic_button_options, ttk


TOOLBAR_ICON_SIZE = (24, 24)
TOOLBAR_ACTIVE_ICON_COLOR = (255, 255, 255, 255)
TOOLBAR_ICON_FILES = {
    "select": "Mouse Icon@4x.png",
    "point_pos": "Point+ Icon@4x.png",
    "point_neg": "Point- Icon@4x.png",
    "box": "Box Icon@4x.png",
    "brush": "Brush Icon@4x.png",
    "eraser": "Eraser Icon@4x.png",
    "fill": "Fill+ Icon@4x.png",
    "fill_erase": "FIll- Icon@4x.png",
    REGION_INCLUDE_TOOL: "Region+ Icon@4x.png",
    REGION_EXCLUDE_TOOL: "Region- Icon@4x.png",
    "clear_frame": "Clear Frame Icon@4x.png",
}


def _attach_tooltip(widget, text: str) -> None:
    manager = _tooltip_manager_for_widget(widget)
    manager.attach(widget, text)


def _tooltip_manager_for_widget(widget) -> TooltipManager:
    try:
        root = widget.winfo_toplevel()
    except Exception:
        root = widget
    manager = getattr(root, "_analysis_tooltip_manager", None)
    if manager is None:
        manager = TooltipManager(root)
        try:
            setattr(root, "_analysis_tooltip_manager", manager)
        except Exception:
            pass
    return manager


def _load_toolbar_icon_pair(filename: str) -> tuple[ImageTk.PhotoImage, ImageTk.PhotoImage] | None:
    icon_path = get_resources_root() / "assets" / "analysis_toolbar" / filename
    if not icon_path.exists():
        return None
    with Image.open(icon_path) as source:
        image = source.convert("RGBA")
    image = image.resize(TOOLBAR_ICON_SIZE, Image.Resampling.LANCZOS)
    active_image = Image.new("RGBA", image.size, TOOLBAR_ACTIVE_ICON_COLOR)
    active_image.putalpha(image.getchannel("A"))
    return ImageTk.PhotoImage(image), ImageTk.PhotoImage(active_image)


class LayoutBuilder:
    def setup_ui(self):
        apply_theme(self.root)
        self._tooltip_manager = TooltipManager(self.root)
        setattr(self.root, "_analysis_tooltip_manager", self._tooltip_manager)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = ttk.Frame(self.root, padding=SPACING.outer, style="AppShell.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=0, minsize=320)
        shell.rowconfigure(1, weight=0)
        shell.rowconfigure(2, weight=1)
        shell.rowconfigure(3, weight=0)
        self.frame_status_var = tk.StringVar(value="Frame 0 / 0")
        self.frame_meta_var = tk.StringVar(value="No file loaded")

        self._build_status_row(shell)
        self._build_tool_options_bar(shell)

        content = ttk.Frame(shell, style="AppShell.TFrame")
        content.grid(row=2, column=0, sticky="nsew", pady=(0, SPACING.inner), padx=(0, SPACING.gap))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.build_left_panel(content)
        self.build_inspector_dock(shell)

        controls = ttk.Frame(shell, style="AppShell.TFrame")
        controls.grid(row=3, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        self.build_controls(controls)
        self._disable_button_focus(shell)
        self._bind_clicks_to_clear_text_focus(shell)
        self._configure_text_cursor()
        self._bind_shortcuts()

    def _build_status_row(self, parent):
        status_row = ttk.Frame(parent, style="AppShell.TFrame")
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, SPACING.inner))
        status_row.columnconfigure(0, weight=1)
        status_row.columnconfigure(1, weight=1)

        self.lbl_status = ttk.Label(status_row, text="Status: Idle", style="AppMeta.TLabel", justify="left", wraplength=480)
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.loading_status_var = tk.StringVar(value="Idle")
        self.loading_status_label = ttk.Label(
            status_row,
            textvariable=self.loading_status_var,
            style="AppMeta.TLabel",
            justify="right",
            anchor="e",
            wraplength=420,
        )
        self.loading_status_label.grid(row=0, column=1, sticky="e")

    def _build_tool_options_bar(self, parent):
        self.tool_options_bar = ttk.Frame(parent, padding=(SPACING.card, 2, SPACING.card, 2), style="AppStrip.TFrame")
        self.tool_options_bar.grid(row=1, column=0, sticky="ew", pady=(0, SPACING.gap))
        self.tool_options_bar.columnconfigure(0, weight=1)

        self.tool_option_frames = {}
        self.tool_options_slot = ttk.Frame(self.tool_options_bar, style="AppStrip.TFrame")
        self.tool_options_slot.grid(row=0, column=0, sticky="ew")
        self.tool_options_slot.columnconfigure(0, weight=1)

        select_frame = ttk.Frame(self.tool_options_slot, style="AppStrip.TFrame")
        select_frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(select_frame, text="Select", style="AppStripMeta.TLabel").grid(row=0, column=0, sticky="w")
        self.tool_option_frames["select"] = select_frame

        prompt_frame = ttk.Frame(self.tool_options_slot, style="AppStrip.TFrame")
        prompt_frame.grid(row=0, column=0, sticky="ew")
        prompt_frame.columnconfigure(1, weight=1)
        ttk.Label(prompt_frame, text="Sensitivity", style="AppStripMeta.TLabel").grid(row=0, column=0, sticky="w")
        self.sensitivity = tk.DoubleVar(value=0.0)
        ttk.Scale(
            prompt_frame,
            from_=-3.0,
            to=3.0,
            variable=self.sensitivity,
            orient="horizontal",
            command=self.on_sensitivity_change,
            style="AppFlat.Horizontal.TScale",
        ).grid(row=0, column=1, sticky="ew", padx=(SPACING.gap, SPACING.gap))
        self.lbl_sens = ttk.Label(prompt_frame, text="0.0", style="AppStripMeta.TLabel", width=5)
        self.lbl_sens.grid(row=0, column=2, sticky="w")
        for mode in ("point_pos", "point_neg", "box"):
            self.tool_option_frames[mode] = prompt_frame

        brush_frame = ttk.Frame(self.tool_options_slot, style="AppStrip.TFrame")
        brush_frame.grid(row=0, column=0, sticky="ew")
        brush_frame.columnconfigure(1, weight=1)
        ttk.Label(brush_frame, text="Brush", style="AppStripMeta.TLabel").grid(row=0, column=0, sticky="w")
        self.brush_size = tk.DoubleVar(value=10.0)
        self.scale_brush = ttk.Scale(
            brush_frame,
            from_=1,
            to=50,
            variable=self.brush_size,
            orient="horizontal",
            command=self.on_brush_size_change,
            style="AppFlat.Horizontal.TScale",
        )
        self.scale_brush.grid(row=0, column=1, sticky="ew", padx=(SPACING.gap, SPACING.gap))
        self.lbl_brush_val = ttk.Label(brush_frame, text="10 px", style="AppStripMeta.TLabel", width=7)
        self.lbl_brush_val.grid(row=0, column=2, sticky="w")
        self.tool_option_frames["brush"] = brush_frame
        self.tool_option_frames["eraser"] = brush_frame

        # Fill is split into two explicit tools (Fill (+) / Fill (-)); add vs.
        # remove is derived from the selected tool, so there is no mode toggle
        # here — only the shared tolerance and Fill Holes controls.
        fill_frame = ttk.Frame(self.tool_options_slot, style="AppStrip.TFrame")
        fill_frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(fill_frame, text="Fill", style="AppStripMeta.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(fill_frame, text="Tolerance", style="AppStripMeta.TLabel").grid(row=0, column=1, sticky="e", padx=(SPACING.inner, SPACING.gap))
        self.fill_tolerance = tk.DoubleVar(value=8.0)
        ttk.Scale(
            fill_frame,
            from_=0,
            to=64,
            variable=self.fill_tolerance,
            orient="horizontal",
            style="AppFlat.Horizontal.TScale",
        ).grid(row=0, column=2, sticky="ew")
        ttk.Button(fill_frame, text="Fill Holes", command=self.fill_current_frame_holes, **semantic_button_options("secondary")).grid(
            row=0,
            column=3,
            sticky="e",
            padx=(SPACING.gap, 0),
        )
        fill_frame.columnconfigure(2, weight=1)
        self.tool_option_frames["fill"] = fill_frame
        self.tool_option_frames["fill_erase"] = fill_frame

        region_frame = ttk.Frame(self.tool_options_slot, style="AppStrip.TFrame")
        region_frame.grid(row=0, column=0, sticky="ew")
        self.lbl_region_options_title = ttk.Label(region_frame, text="Include Region", style="AppStripMeta.TLabel")
        self.lbl_region_options_title.grid(row=0, column=0, sticky="w")
        ttk.Label(region_frame, text="Frames", style="AppStripMeta.TLabel").grid(row=0, column=1, sticky="e", padx=(SPACING.inner, SPACING.gap))
        self.region_start_var = tk.StringVar(value="1")
        self.entry_region_start = ttk.Entry(region_frame, textvariable=self.region_start_var, width=5, style="AppCompact.TEntry")
        self.entry_region_start.grid(row=0, column=2, sticky="w")
        ttk.Label(region_frame, text="-", style="AppStripMeta.TLabel").grid(row=0, column=3, sticky="w", padx=(SPACING.gap, SPACING.gap))
        self.region_end_var = tk.StringVar(value="1")
        self.entry_region_end = ttk.Entry(region_frame, textvariable=self.region_end_var, width=5, style="AppCompact.TEntry")
        self.entry_region_end.grid(row=0, column=4, sticky="w")
        for entry in (self.entry_region_start, self.entry_region_end):
            entry.bind("<Return>", self._apply_selected_region_options_event, add="+")
            entry.bind("<FocusOut>", self._apply_selected_region_options_event, add="+")
        self.btn_region_close_shape = ttk.Button(region_frame, text="Close Shape", command=self.close_region_draft, **semantic_button_options("secondary"))
        self.btn_region_close_shape.grid(
            row=0,
            column=5,
            sticky="e",
            padx=(SPACING.inner, 0),
        )
        self.btn_region_discard = ttk.Button(region_frame, text="Discard", command=self.cancel_region_draft, **semantic_button_options("secondary"))
        self.btn_region_discard.grid(
            row=0,
            column=6,
            sticky="e",
            padx=(SPACING.gap, 0),
        )
        self.btn_region_add = ttk.Button(region_frame, text="Add Region", command=self.commit_region_draft, **semantic_button_options("primary"))
        self.btn_region_add.grid(
            row=0,
            column=7,
            sticky="e",
            padx=(SPACING.gap, 0),
        )
        self.btn_region_convert = ttk.Button(region_frame, text="Convert to Exclude", command=self.convert_selected_region_mode, **semantic_button_options("secondary"))
        self.btn_region_convert.grid(
            row=0,
            column=8,
            sticky="e",
            padx=(SPACING.gap, 0),
        )
        self.tool_option_frames[REGION_INCLUDE_TOOL] = region_frame
        self.tool_option_frames[REGION_EXCLUDE_TOOL] = region_frame
        self.tool_option_frames["region"] = region_frame
        self._active_tool_option_frame = None
        self.root.after_idle(self._lock_tool_options_slot_size)

    def build_left_panel(self, parent):
        self.panel_left, body = self._create_view_panel(parent, row=0, column=0, title="Canvas", padx=(0, SPACING.gap))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas_left = tk.Canvas(body, bg=CANVAS_BACKGROUND, cursor="cross", highlightthickness=0, bd=0)
        self.canvas_left.grid(row=0, column=0, sticky="nsew")

        self.canvas_left.bind("<Button-1>", self.on_mouse_down)
        self.canvas_left.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas_left.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas_left.bind("<Motion>", self.on_mouse_move)
        self.canvas_left.bind("<Leave>", self.on_mouse_leave)
        self.canvas_left.bind("<Configure>", self._on_viewport_canvas_configure, add="+")
        self.canvas_left.bind("<MouseWheel>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_left.bind("<Button-4>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_left.bind("<Button-5>", self._on_canvas_mouse_wheel, add="+")

        self.preview_frame, self.canvas_preview, self.lbl_grip = build_preview_overlay(
            self.canvas_left,
            self.start_resize_preview,
            self.do_resize_preview,
            self.stop_resize_preview,
            dark_theme=True,
        )
        self.canvas_preview.bind("<Button-1>", lambda event: self._start_canvas_pan(self.canvas_preview, event), add="+")
        self.canvas_preview.bind("<B1-Motion>", lambda event: self._drag_canvas_pan(self.canvas_preview, event), add="+")
        self.canvas_preview.bind("<ButtonRelease-1>", lambda event: self._stop_canvas_pan(self.canvas_preview, event), add="+")
        self.canvas_preview.bind("<Configure>", self._on_viewport_canvas_configure, add="+")
        self.canvas_preview.bind("<MouseWheel>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_preview.bind("<Button-4>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_preview.bind("<Button-5>", self._on_canvas_mouse_wheel, add="+")
        self.build_tool_rail(body)

    def build_tool_rail(self, parent):
        rail = ttk.Frame(parent, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.card), style="AppSidebar.TFrame")
        rail.place(x=14, y=14, anchor="nw")
        rail.columnconfigure(0, weight=1)
        self.tool_rail = rail
        self.frame_tools = self._build_tools_group(rail, 0, row=0, vertical=True)
        rail.lift()

    def build_inspector_dock(self, parent):
        dock = ttk.Frame(parent, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.card), style="AppSidebar.TFrame")
        dock.grid(row=1, column=1, rowspan=3, sticky="nsew")
        dock.columnconfigure(0, weight=1, minsize=304)
        dock.columnconfigure(1, weight=0)
        dock.rowconfigure(0, weight=1)
        dock.rowconfigure(1, weight=0)
        self.panel_right = dock
        self.inspector_dock = dock

        canvas = tk.Canvas(dock, bg=APP_COLORS["surface_bg"], highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(dock, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(SPACING.gap, 0))
        canvas.configure(yscrollcommand=scrollbar.set)

        scroll_body = ttk.Frame(canvas, style="AppSidebar.TFrame")
        scroll_body.columnconfigure(0, weight=1, minsize=304)
        window_id = canvas.create_window((0, 0), window=scroll_body, anchor="nw")
        self.inspector_scroll_canvas = canvas
        self.inspector_scroll_body = scroll_body
        self.inspector_scrollbar = scrollbar
        self._inspector_scroll_window_id = window_id
        self._inspector_wheel_bound = False

        scroll_body.bind("<Configure>", self._on_inspector_scroll_body_configure, add="+")
        canvas.bind("<Configure>", self._on_inspector_scroll_canvas_configure, add="+")
        for widget in (canvas, scroll_body):
            widget.bind("<Enter>", self._bind_inspector_mouse_wheel, add="+")
            widget.bind("<Leave>", self._unbind_inspector_mouse_wheel_if_outside, add="+")

        self._build_reference_section(scroll_body, row=0)
        self.frame_prop = self._build_propagation_group(scroll_body, 0, row=1)
        self.right_controls = self._build_event_metrics_group(scroll_body, 0, row=2)
        self.frame_view = self._build_view_section(scroll_body, row=3)
        self.frame_regions = self._build_regions_section(scroll_body, row=4)
        self._build_save_masks_button(dock, row=1)

    def _on_inspector_scroll_body_configure(self, _event=None):
        canvas = getattr(self, "inspector_scroll_canvas", None)
        if canvas is None:
            return
        try:
            bbox = canvas.bbox("all")
            if bbox is not None:
                canvas.configure(scrollregion=bbox)
        except Exception:
            return

    def _on_inspector_scroll_canvas_configure(self, event=None):
        canvas = getattr(self, "inspector_scroll_canvas", None)
        window_id = getattr(self, "_inspector_scroll_window_id", None)
        if canvas is None or window_id is None:
            return
        try:
            width = max(1, int(getattr(event, "width", canvas.winfo_width())))
            canvas.itemconfigure(window_id, width=width)
            bbox = canvas.bbox("all")
            if bbox is not None:
                canvas.configure(scrollregion=bbox)
        except Exception:
            return

    def _event_inside_inspector(self, event) -> bool:
        canvas = getattr(self, "inspector_scroll_canvas", None)
        if canvas is None:
            return False
        try:
            x_root = int(getattr(event, "x_root", 0))
            y_root = int(getattr(event, "y_root", 0))
            left = int(canvas.winfo_rootx())
            top = int(canvas.winfo_rooty())
            right = left + int(canvas.winfo_width())
            bottom = top + int(canvas.winfo_height())
            return bool(left <= x_root <= right and top <= y_root <= bottom)
        except Exception:
            return False

    def _bind_inspector_mouse_wheel(self, _event=None):
        if getattr(self, "_inspector_wheel_bound", False):
            return
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_class("InspectorWheel", sequence, self._on_inspector_mouse_wheel, add="+")
        for widget in self._iter_inspector_wheel_widgets():
            try:
                tags = tuple(widget.bindtags())
                if "InspectorWheel" not in tags:
                    widget.bindtags(tags + ("InspectorWheel",))
            except Exception:
                continue
        self._inspector_wheel_bound = True

    def _unbind_inspector_mouse_wheel(self):
        if not getattr(self, "_inspector_wheel_bound", False):
            return
        for widget in self._iter_inspector_wheel_widgets():
            try:
                tags = tuple(tag for tag in widget.bindtags() if tag != "InspectorWheel")
                widget.bindtags(tags)
            except Exception:
                continue
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.root.unbind_class("InspectorWheel", sequence)
            except Exception:
                pass
        self._inspector_wheel_bound = False

    def _iter_inspector_wheel_widgets(self):
        roots = [
            getattr(self, "inspector_scroll_canvas", None),
            getattr(self, "inspector_scroll_body", None),
        ]
        seen = set()

        def walk(widget):
            if widget is None:
                return
            ident = id(widget)
            if ident in seen:
                return
            seen.add(ident)
            yield widget
            try:
                children = list(widget.winfo_children())
            except Exception:
                children = []
            for child in children:
                yield from walk(child)

        for root in roots:
            yield from walk(root)

    def _unbind_inspector_mouse_wheel_if_outside(self, event=None):
        if event is not None and self._event_inside_inspector(event):
            return
        self._unbind_inspector_mouse_wheel()

    def _on_inspector_mouse_wheel(self, event):
        canvas = getattr(self, "inspector_scroll_canvas", None)
        if canvas is None:
            return None
        if not self._event_inside_inspector(event):
            self._unbind_inspector_mouse_wheel()
            return None

        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        direction = 0
        if delta:
            direction = -1 if float(delta) > 0 else 1
        elif num in (4, 5):
            direction = -1 if int(num) == 4 else 1
        if direction == 0:
            return None
        try:
            canvas.yview_scroll(direction * 3, "units")
        except Exception:
            return None
        return "break"

    def build_right_panel(self, parent):
        self.panel_right, body = self._create_view_panel(parent, row=0, column=1, title="Reference View", padx=(SPACING.gap, 0))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas_right = tk.Canvas(body, bg=CANVAS_BACKGROUND, highlightthickness=0, bd=0)
        self.canvas_right.grid(row=0, column=0, sticky="nsew")
        self.reference_overlay = self._create_frame_overlay(body)
        self.reference_overlay.lift()
        self.canvas_right.bind("<Button-1>", self.on_right_canvas_click)
        self.canvas_right.bind("<Double-Button-1>", self.on_right_canvas_double_click)
        self.canvas_right.bind("<Button-1>", lambda event: self._start_canvas_pan(self.canvas_right, event), add="+")
        self.canvas_right.bind("<B1-Motion>", lambda event: self._drag_canvas_pan(self.canvas_right, event), add="+")
        self.canvas_right.bind("<ButtonRelease-1>", lambda event: self._stop_canvas_pan(self.canvas_right, event), add="+")
        self.canvas_right.bind("<Configure>", self._on_viewport_canvas_configure, add="+")
        self.canvas_right.bind("<MouseWheel>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_right.bind("<Button-4>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_right.bind("<Button-5>", self._on_canvas_mouse_wheel, add="+")

    def build_controls(self, parent):
        parent.columnconfigure(0, weight=1)
        self._build_timeline_band(parent)

    def _build_timeline_band(self, parent):
        timeline = ttk.Frame(parent, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.card), style="AppStrip.TFrame")
        timeline.grid(row=0, column=0, sticky="ew")
        timeline.columnconfigure(0, weight=1)

        ttk.Label(timeline, text="Timeline", style="AppStripTitle.TLabel").grid(row=0, column=0, sticky="w")

        slider_row = ttk.Frame(timeline, style="AppStrip.TFrame")
        slider_row.grid(row=1, column=0, sticky="ew", pady=(SPACING.inner, 0))
        slider_row.columnconfigure(0, weight=1)

        self.slider_overlay = tk.Canvas(
            slider_row,
            height=18,
            bg=SLIDER_OVERLAY_BACKGROUND,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.slider_overlay.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.slider_overlay.bind("<Button-1>", self._on_slider_overlay_click)
        self.slider_overlay.bind("<Configure>", lambda _event: self._redraw_slider_overlay())

        self.loading_bar = ttk.Progressbar(timeline, mode="indeterminate", style="AppLoading.Horizontal.TProgressbar")

        self.slider = ttk.Scale(
            slider_row,
            from_=0,
            to=100,
            orient="horizontal",
            command=self.on_slider_move,
            style="AppFlat.Horizontal.TScale",
            takefocus=False,
        )
        self.slider.grid(row=1, column=0, sticky="ew")
        self.slider.bind("<Left>", self.on_nav_left)
        self.slider.bind("<Right>", self.on_nav_right)

    def _build_reference_section(self, parent, row):
        section, body = self._build_dock_section(
            parent,
            row=row,
            title="Reference",
            collapsible=False,
            tooltip="Reference view and mask peek controls.",
        )
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)

        action_row = ttk.Frame(body, style="AppSubpanel.TFrame")
        action_row.grid(row=0, column=0, sticky="ew", pady=(0, SPACING.gap))
        action_row.columnconfigure(0, weight=1)
        self.chk_mask_peek = ttk.Checkbutton(
            action_row,
            text="Peek",
            variable=self.mask_peek_sticky_var,
            command=self._on_mask_peek_sticky_toggled,
            style="AppSubpanel.TCheckbutton",
            takefocus=False,
        )
        self.chk_mask_peek.grid(row=0, column=0, sticky="w")
        _attach_tooltip(self.chk_mask_peek, "Hide mask overlay while enabled (P)")
        self.btn_reference_expand = ttk.Button(
            action_row,
            text="Expand",
            command=self._open_reference_popout,
            **semantic_button_options("secondary"),
        )
        self.btn_reference_expand.grid(row=0, column=1, sticky="e")

        ref_body = ttk.Frame(body, style="AppInset.TFrame")
        ref_body.grid(row=1, column=0, sticky="nsew")
        ref_body.columnconfigure(0, weight=1)
        ref_body.rowconfigure(0, weight=1, minsize=180)

        self.canvas_right = tk.Canvas(ref_body, bg=CANVAS_BACKGROUND, highlightthickness=0, bd=0)
        self.canvas_right.grid(row=0, column=0, sticky="nsew")
        self.reference_overlay = self._create_frame_overlay(ref_body)
        self.reference_overlay.lift()
        self._bind_reference_canvas(self.canvas_right)
        return section

    def _bind_reference_canvas(self, canvas):
        canvas.bind("<Button-1>", self.on_right_canvas_click)
        canvas.bind("<Double-Button-1>", self.on_right_canvas_double_click)
        canvas.bind("<Button-1>", lambda event, c=canvas: self._start_canvas_pan(c, event), add="+")
        canvas.bind("<B1-Motion>", lambda event, c=canvas: self._drag_canvas_pan(c, event), add="+")
        canvas.bind("<ButtonRelease-1>", lambda event, c=canvas: self._stop_canvas_pan(c, event), add="+")
        canvas.bind("<Configure>", self._on_viewport_canvas_configure, add="+")
        canvas.bind("<MouseWheel>", self._on_canvas_mouse_wheel, add="+")
        canvas.bind("<Button-4>", self._on_canvas_mouse_wheel, add="+")
        canvas.bind("<Button-5>", self._on_canvas_mouse_wheel, add="+")

    def _open_reference_popout(self):
        existing = getattr(self, "reference_popout_window", None)
        try:
            if existing is not None and bool(existing.winfo_exists()):
                existing.lift()
                return
        except Exception:
            pass
        top = tk.Toplevel(self.root)
        top.title("Reference")
        top.geometry("760x560")
        top.columnconfigure(0, weight=1)
        top.rowconfigure(0, weight=1)
        frame = ttk.Frame(top, padding=SPACING.card, style="AppShell.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        canvas = tk.Canvas(frame, bg=CANVAS_BACKGROUND, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        self.reference_popout_window = top
        self.canvas_reference_popout = canvas
        self._bind_reference_canvas(canvas)

        def _close():
            self.canvas_reference_popout = None
            self.reference_popout_window = None
            try:
                top.destroy()
            except Exception:
                pass
            self._clamp_shared_viewport()
            self._queue_display_update(update_preview=True)

        top.protocol("WM_DELETE_WINDOW", _close)
        self._clamp_shared_viewport()
        self._queue_display_update(update_preview=True)

    def _build_dock_section(self, parent, *, row, title, collapsible=True, open_state=False, tooltip=None):
        section = ttk.Frame(parent, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.card), style="AppSubpanel.TFrame")
        section.grid(row=row, column=0, sticky="new", pady=(0, SPACING.gap))
        section.columnconfigure(0, weight=1)

        header = ttk.Frame(section, style="AppSubpanel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        title_label = ttk.Label(header, text=title, style="AppSubpanelTitle.TLabel")
        title_label.grid(row=0, column=0, sticky="w")
        if tooltip:
            for widget in (header, title_label):
                _attach_tooltip(widget, str(tooltip))
        body = ttk.Frame(section, style="AppSubpanel.TFrame")
        body.grid(row=1, column=0, sticky="new", pady=(SPACING.gap, 0))
        body.columnconfigure(0, weight=1)

        if collapsible:
            state = tk.BooleanVar(value=bool(open_state))
            button = ttk.Button(
                header,
                text="Hide" if bool(open_state) else "Show",
                command=lambda: self._toggle_dock_section(body, state, button),
                **semantic_button_options("secondary"),
            )
            button.grid(row=0, column=1, sticky="e")
            self._toggle_dock_section(body, state, button, force=bool(open_state))
        return section, body

    def _toggle_dock_section(self, body, state, button, *, force=None):
        is_open = bool(force) if force is not None else not bool(state.get())
        state.set(is_open)
        if is_open:
            body.grid()
            button.configure(text="Hide")
        else:
            body.grid_remove()
            button.configure(text="Show")

    def _build_tools_group(self, parent, column, *, row=0, vertical=False):
        loaded_icons = {
            key: icon_pair
            for key, filename in TOOLBAR_ICON_FILES.items()
            if (icon_pair := _load_toolbar_icon_pair(filename)) is not None
        }
        self._analysis_toolbar_icons = {key: icon_pair[0] for key, icon_pair in loaded_icons.items()}
        self._analysis_toolbar_active_icons = {key: icon_pair[1] for key, icon_pair in loaded_icons.items()}

        def icon_button_options(icon_key: str, fallback_text: str) -> dict[str, object]:
            icon = self._analysis_toolbar_icons.get(icon_key)
            if icon is None:
                return {"text": fallback_text}
            return {"image": icon, "text": ""}

        frame = ttk.Frame(parent, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.card), style="AppSubpanel.TFrame")
        frame.grid(row=row, column=column, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        if not vertical:
            frame.columnconfigure(1, weight=1)
            frame.columnconfigure(2, weight=1)
        self.tool_mode = tk.StringVar(value="select")
        self.tool_mode.trace_add("write", lambda *_args: self._on_tool_mode_changed())

        title_span = 1 if vertical else 3
        ttk.Label(frame, text="Tools", style="AppSubpanelTitle.TLabel").grid(row=0, column=0, columnspan=title_span, sticky="w", pady=(0, SPACING.gap))
        segmented = ttk.Frame(frame, style="AppSubpanel.TFrame")
        segmented.grid(row=1, column=0, columnspan=title_span, sticky="ew")
        if vertical:
            segmented.columnconfigure(0, weight=1)
        else:
            for seg_col in range(3):
                segmented.columnconfigure(seg_col, weight=1)
        self.btn_tool_select = ttk.Button(
            segmented,
            command=lambda: self._set_tool_mode("select"),
            style="AppSegmentedActive.TButton",
            **icon_button_options("select", "Select"),
        )
        self.btn_tool_select.grid(row=0, column=0, sticky="ew")
        _attach_tooltip(self.btn_tool_select, "Select (V)")
        self.btn_tool_point_pos = ttk.Button(
            segmented,
            command=lambda: self._set_tool_mode("point_pos"),
            style="AppSegmented.TButton",
            **icon_button_options("point_pos", "Point (+)"),
        )
        self.btn_tool_point_pos.grid(row=1 if vertical else 0, column=0 if vertical else 1, sticky="ew", padx=(0 if vertical else 1, 0 if vertical else 1), pady=(SPACING.gap if vertical else 0, 0))
        _attach_tooltip(self.btn_tool_point_pos, "Add Point (+)")
        self.btn_tool_point_neg = ttk.Button(
            segmented,
            command=lambda: self._set_tool_mode("point_neg"),
            style="AppSegmented.TButton",
            **icon_button_options("point_neg", "Point (-)"),
        )
        self.btn_tool_point_neg.grid(row=2 if vertical else 0, column=0 if vertical else 2, sticky="ew", pady=(SPACING.gap if vertical else 0, 0))
        _attach_tooltip(self.btn_tool_point_neg, "Remove Point (-)")
        self.btn_tool_box = ttk.Button(
            segmented,
            command=lambda: self._set_tool_mode("box"),
            style="AppSegmented.TButton",
            **icon_button_options("box", "Box"),
        )
        if vertical:
            self.btn_tool_box.grid(row=3, column=0, sticky="ew", pady=(SPACING.gap, 0))
        else:
            self.btn_tool_box.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(SPACING.gap, 0), padx=(1, 0))
        _attach_tooltip(self.btn_tool_box, "Box (K)")

        brush_row = ttk.Frame(frame, style="AppSubpanel.TFrame")
        brush_row.grid(row=2, column=0, columnspan=title_span, sticky="ew", pady=(SPACING.inner, 0))
        brush_row.columnconfigure(0, weight=1)
        if not vertical:
            brush_row.columnconfigure(1, weight=1)
        self.btn_tool_brush = ttk.Button(
            brush_row,
            command=lambda: self._set_tool_mode("brush"),
            style="AppSegmented.TButton",
            **icon_button_options("brush", "Brush (+)"),
        )
        self.btn_tool_brush.grid(row=0, column=0, sticky="ew", padx=(0, 1))
        _attach_tooltip(self.btn_tool_brush, "Brush + (B)")
        self.btn_tool_eraser = ttk.Button(
            brush_row,
            command=lambda: self._set_tool_mode("eraser"),
            style="AppSegmented.TButton",
            **icon_button_options("eraser", "Brush (-)"),
        )
        self.btn_tool_eraser.grid(row=1 if vertical else 0, column=0 if vertical else 1, sticky="ew", pady=(SPACING.gap if vertical else 0, 0))
        _attach_tooltip(self.btn_tool_eraser, "Brush - (E)")
        self.btn_tool_fill = ttk.Button(
            brush_row,
            command=lambda: self._set_tool_mode("fill"),
            style="AppSegmented.TButton",
            **icon_button_options("fill", "Fill (+)"),
        )
        self.btn_tool_fill.grid(
            row=2 if vertical else 1,
            column=0,
            sticky="ew",
            padx=(0, 0) if vertical else (0, 1),
            pady=(SPACING.gap, 0),
        )
        _attach_tooltip(self.btn_tool_fill, "Fill + (G)")
        self.btn_tool_fill_erase = ttk.Button(
            brush_row,
            command=lambda: self._set_tool_mode("fill_erase"),
            style="AppSegmented.TButton",
            **icon_button_options("fill_erase", "Fill (-)"),
        )
        self.btn_tool_fill_erase.grid(
            row=3 if vertical else 1,
            column=0 if vertical else 1,
            sticky="ew",
            pady=(SPACING.gap, 0),
        )
        _attach_tooltip(self.btn_tool_fill_erase, "Fill - (Shift+G)")
        self.btn_tool_region_include = ttk.Button(
            brush_row,
            command=lambda: self._set_tool_mode(REGION_INCLUDE_TOOL),
            style="AppSegmented.TButton",
            **icon_button_options(REGION_INCLUDE_TOOL, "Include Region"),
        )
        self.btn_tool_region_include.grid(
            row=4 if vertical else 2,
            column=0 if vertical else 0,
            columnspan=1 if vertical else 2,
            sticky="ew",
            pady=(SPACING.gap, 0),
        )
        _attach_tooltip(self.btn_tool_region_include, "Include Region (R)")
        self.btn_tool_region_exclude = ttk.Button(
            brush_row,
            command=lambda: self._set_tool_mode(REGION_EXCLUDE_TOOL),
            style="AppSegmented.TButton",
            **icon_button_options(REGION_EXCLUDE_TOOL, "Exclude Region"),
        )
        self.btn_tool_region_exclude.grid(
            row=5 if vertical else 3,
            column=0 if vertical else 0,
            columnspan=1 if vertical else 2,
            sticky="ew",
            pady=(SPACING.gap, 0),
        )
        _attach_tooltip(self.btn_tool_region_exclude, "Exclude Region (Shift+R)")

        self.btn_tool_clear_frame = ttk.Button(
            frame,
            command=self.clear_current_frame_data,
            **semantic_button_options("secondary"),
            **icon_button_options("clear_frame", "Clear Frame"),
        )
        self.btn_tool_clear_frame.grid(
            row=3,
            column=0 if vertical else 2,
            columnspan=title_span if vertical else 1,
            sticky="ew" if vertical else "e",
            pady=(SPACING.inner, 0),
        )
        _attach_tooltip(self.btn_tool_clear_frame, "Clear Frame")
        self._sync_tool_mode_buttons()
        self._sync_tool_options()
        return frame

    def _build_propagation_group(self, parent, column, *, row=0):
        _section, frame = self._build_dock_section(
            parent,
            row=row,
            title="Propagation",
            collapsible=True,
            tooltip="Run propagation from point, box, paint, or committed-mask anchors. Regions do not seed propagation.",
        )
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        self.propagation_range_canvas = tk.Canvas(frame, height=16, bg=SLIDER_OVERLAY_BACKGROUND, highlightthickness=0, bd=0)
        self.propagation_range_canvas.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, SPACING.gap))
        ttk.Label(frame, text="Start", style="AppSubpanelMeta.TLabel").grid(row=1, column=0, sticky="w")
        self.spin_prop_start = ttk.Entry(frame, width=5, style="AppCompact.TEntry")
        self.spin_prop_start.grid(row=1, column=1, sticky="ew", padx=(SPACING.gap, SPACING.inner))
        self._set_spinbox_value(self.spin_prop_start, 1)
        self.spin_prop_start.bind("<KeyRelease>", lambda _event: self._redraw_propagation_range_bar(), add="+")
        self.spin_prop_start.bind("<FocusOut>", lambda _event: self._redraw_propagation_range_bar(), add="+")

        ttk.Label(frame, text="End", style="AppSubpanelMeta.TLabel").grid(row=1, column=2, sticky="w")
        self.spin_prop_end = ttk.Entry(frame, width=5, style="AppCompact.TEntry")
        self.spin_prop_end.grid(row=1, column=3, sticky="ew", padx=(SPACING.gap, 0))
        self._set_spinbox_value(self.spin_prop_end, 100)
        self.spin_prop_end.bind("<KeyRelease>", lambda _event: self._redraw_propagation_range_bar(), add="+")
        self.spin_prop_end.bind("<FocusOut>", lambda _event: self._redraw_propagation_range_bar(), add="+")

        self.btn_run_propagation = ttk.Button(frame, text="Run Propagation", command=self._trigger_background_propagation, **semantic_button_options("success"))
        self.btn_run_propagation.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(SPACING.inner, 0),
        )

        prop_control_row = ttk.Frame(frame, style="AppSubpanel.TFrame")
        prop_control_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(SPACING.gap, 0))
        for control_col in range(3):
            prop_control_row.columnconfigure(control_col, weight=1)
        self.btn_pause_propagation = ttk.Button(
            prop_control_row,
            text="Pause",
            command=self._pause_background_propagation,
            **semantic_button_options("secondary"),
        )
        self.btn_pause_propagation.grid(row=0, column=0, sticky="ew", padx=(0, SPACING.gap))
        self.btn_resume_propagation = ttk.Button(
            prop_control_row,
            text="Resume",
            command=self._resume_background_propagation,
            **semantic_button_options("secondary"),
        )
        self.btn_resume_propagation.grid(row=0, column=1, sticky="ew", padx=(0, SPACING.gap))
        self.btn_stop_propagation = ttk.Button(
            prop_control_row,
            text="Stop",
            command=self._stop_background_propagation,
            **semantic_button_options("danger"),
        )
        self.btn_stop_propagation.grid(row=0, column=2, sticky="ew")
        for button in (self.btn_pause_propagation, self.btn_resume_propagation, self.btn_stop_propagation):
            button.configure(state="disabled")
        self.propagation_range_canvas.bind("<Configure>", lambda _event: self._redraw_propagation_range_bar(), add="+")
        self._redraw_propagation_range_bar()
        return frame

    def _build_metrics_group(self, parent, column, *, row=0):
        frame = ttk.Frame(parent, style="AppSubpanel.TFrame")
        frame.grid(row=row, column=column, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        self.frame_metrics = frame

        self.frame_analysis_body = ttk.Frame(frame, style="AppSubpanel.TFrame")
        self.frame_analysis_body.grid(row=0, column=0, sticky="ew")
        self.frame_analysis_body.columnconfigure(1, weight=1)

        ttk.Label(self.frame_analysis_body, text="Frames/sec", style="AppSubpanelMeta.TLabel").grid(row=0, column=0, sticky="w")
        self.frames_per_sec_var = tk.DoubleVar(value=1.0)
        self.entry_frames_per_sec = ttk.Entry(self.frame_analysis_body, textvariable=self.frames_per_sec_var, width=7, style="AppCompact.TEntry")
        self.entry_frames_per_sec.grid(row=0, column=1, sticky="ew", padx=(SPACING.gap, 0))

        metrics_actions = ttk.Frame(self.frame_analysis_body, style="AppSubpanel.TFrame")
        metrics_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING.inner, 0))
        metrics_actions.columnconfigure(0, weight=1)
        metrics_actions.columnconfigure(1, weight=1)
        metrics_actions.columnconfigure(2, weight=1)

        self.btn_set_scale = ttk.Button(metrics_actions, text="Set Scale", command=self.start_scale_selection, **semantic_button_options("secondary"))
        self.btn_set_scale.grid(row=0, column=0, sticky="ew", padx=(0, SPACING.gap))
        self.btn_draw_roi = ttk.Button(metrics_actions, text="Draw ROI", command=self.start_roi_selection, **semantic_button_options("secondary"))
        self.btn_draw_roi.grid(row=0, column=1, sticky="ew", padx=(0, SPACING.gap))
        self.btn_preview_metrics = ttk.Button(metrics_actions, text="Preview", command=self.compute_metrics_preview, **semantic_button_options("secondary"))
        self.btn_preview_metrics.grid(row=0, column=2, sticky="ew")

        self.metrics_fps_status_var = tk.StringVar(value="Frames/sec: 1 (Current)")
        self.metrics_scale_status_var = tk.StringVar(value="Scale: Not set (Current)")
        self.metrics_roi_status_var = tk.StringVar(value="ROI: Not set (Current)")
        self.metrics_preview_var = tk.StringVar(value="Preview: Click 'Preview' to compute")
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_fps_status_var, style="AppSubpanelMeta.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(SPACING.inner, 0)
        )
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_scale_status_var, style="AppSubpanelMeta.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_roi_status_var, style="AppSubpanelMeta.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_preview_var, style="AppSubpanelMeta.TLabel").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        self._stabilize_metrics_group_width()

    def _stabilize_metrics_group_width(self):
        frame = getattr(self, "frame_metrics", None)
        body = getattr(self, "frame_analysis_body", None)
        if frame is None or body is None:
            return
        try:
            frame.update_idletasks()
            frame.columnconfigure(0, minsize=int(body.winfo_reqwidth()))
        except Exception:
            return

    def _build_event_metrics_group(self, parent, column, *, row=0):
        _section, frame = self._build_dock_section(
            parent,
            row=row,
            title="Event Metrics",
            collapsible=True,
            tooltip="Preview and configure metrics from final composed masks.",
        )
        frame.columnconfigure(0, weight=1)

        self._build_metrics_group(frame, 0)
        return frame

    def _build_save_masks_button(self, parent, *, row):
        frame = ttk.Frame(parent, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.card), style="AppSubpanel.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=(SPACING.gap, 0))
        frame.columnconfigure(0, weight=1)
        self.btn_save_masks = ttk.Button(
            frame,
            text="Save Current Masks",
            command=self.save_current_masks,
            **semantic_button_options("secondary"),
        )
        self.btn_save_masks.grid(row=0, column=0, sticky="ew")
        return frame

    def _build_regions_section(self, parent, row):
        _section, body = self._build_dock_section(
            parent,
            row=row,
            title="Regions",
            collapsible=True,
            tooltip="Regions constrain final masks and exports; they do not seed propagation.",
        )
        body.columnconfigure(0, weight=1)
        self.regions_list_frame = ttk.Frame(body, style="AppSubpanel.TFrame")
        self.regions_list_frame.grid(row=0, column=0, sticky="ew")
        self.regions_empty_var = tk.StringVar(value="No persistent regions")
        self.lbl_regions_empty = ttk.Label(
            self.regions_list_frame,
            textvariable=self.regions_empty_var,
            style="AppSubpanelMeta.TLabel",
        )
        self.lbl_regions_empty.grid(row=0, column=0, sticky="w")
        return body

    def _refresh_regions_dock(self):
        frame = getattr(self, "regions_list_frame", None)
        if frame is None:
            return
        for child in list(frame.winfo_children()):
            child.destroy()
        regions = list(getattr(getattr(self, "seg_state", None), "persistent_regions", []) or [])
        if not regions:
            ttk.Label(frame, text="No persistent regions", style="AppSubpanelMeta.TLabel").grid(row=0, column=0, sticky="w")
            return
        for row, region in enumerate(regions):
            region_id = str(region.get("id", ""))
            selected = region_id and region_id == str(getattr(self, "selected_region_id", ""))
            container = ttk.Frame(frame, padding=(0, SPACING.gap, 0, SPACING.gap), style="AppSubpanel.TFrame")
            container.grid(row=row, column=0, sticky="ew", pady=(0, 1))
            for col in range(6):
                container.columnconfigure(col, weight=1 if col == 0 else 0)
            label = (
                f"{'* ' if selected else ''}{str(region.get('mode', 'include')).title()} "
                f"{int(region.get('frame_start', 0)) + 1}-{int(region.get('frame_end', 0)) + 1}"
            )
            ttk.Button(
                container,
                text=label,
                command=lambda rid=region_id: self._select_region_from_dock(rid),
                **semantic_button_options("secondary"),
            ).grid(row=0, column=0, sticky="ew", padx=(0, SPACING.gap))
            enabled_var = tk.BooleanVar(value=bool(region.get("enabled", True)))
            visible_var = tk.BooleanVar(value=bool(region.get("visible", True)))
            ttk.Checkbutton(
                container,
                text="On",
                variable=enabled_var,
                command=lambda rid=region_id, var=enabled_var: self._set_region_enabled(rid, var.get()),
                style="AppSubpanel.TCheckbutton",
                takefocus=False,
            ).grid(row=0, column=1, sticky="w", padx=(0, SPACING.gap))
            ttk.Checkbutton(
                container,
                text="View",
                variable=visible_var,
                command=lambda rid=region_id, var=visible_var: self._set_region_visible(rid, var.get()),
                style="AppSubpanel.TCheckbutton",
                takefocus=False,
            ).grid(row=0, column=2, sticky="w", padx=(0, SPACING.gap))
            ttk.Button(
                container,
                text="Dup",
                command=lambda rid=region_id: self._duplicate_region_from_dock(rid),
                **semantic_button_options("secondary"),
            ).grid(row=0, column=3, sticky="e", padx=(0, SPACING.gap))
            ttk.Button(
                container,
                text="Del",
                command=lambda rid=region_id: self._delete_region_from_dock(rid),
                **semantic_button_options("danger"),
            ).grid(row=0, column=4, sticky="e")

    def _select_region_from_dock(self, region_id):
        if str(self.tool_mode.get()) != "select":
            self.tool_mode.set("select")
        self._set_selected_region_id(region_id)
        self._sync_tool_options()
        self.update_display()

    def _duplicate_region_from_dock(self, region_id):
        self._set_selected_region_id(region_id)
        self.duplicate_selected_region()

    def _delete_region_from_dock(self, region_id):
        self._set_selected_region_id(region_id)
        self.delete_selected_region()

    def _build_view_section(self, parent, row):
        section, body = self._build_dock_section(
            parent,
            row=row,
            title="View",
            collapsible=True,
            tooltip="Canvas overlays, ghost outlines, and leverage timeline display.",
        )

        self.chk_ghost = ttk.Checkbutton(
            body,
            text="Ghost Outlines",
            variable=self.ghost_outlines_enabled_var,
            style="AppSubpanel.TCheckbutton",
            takefocus=False,
        )
        self.chk_ghost.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, SPACING.inner))

        range_frame = ttk.Frame(body, style="AppSubpanel.TFrame")
        range_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, SPACING.inner))
        range_frame.columnconfigure(1, weight=1)

        ttk.Label(range_frame, text="Range", style="AppSubpanelMeta.TLabel").grid(row=0, column=0, sticky="w")

        self.scale_ghost_range = ttk.Scale(
            range_frame,
            from_=1,
            to=10,
            variable=self.ghost_range_var,
            orient="horizontal",
            command=self._on_ghost_range_scale_changed,
            style="AppFlat.Horizontal.TScale",
        )
        self.scale_ghost_range.grid(row=0, column=1, sticky="ew", padx=(SPACING.gap, SPACING.gap))

        self.lbl_ghost_range_val = ttk.Label(range_frame, text="2", style="AppSubpanelMeta.TLabel", width=5)
        self.lbl_ghost_range_val.grid(row=0, column=2, sticky="w")

        self.chk_leverage_vis = ttk.Checkbutton(
            body,
            text="Show Leverage Heatmap",
            variable=self.leverage_visibility_var,
            style="AppSubpanel.TCheckbutton",
            takefocus=False,
        )
        self.chk_leverage_vis.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, SPACING.inner))

        self.btn_jump_suggested = ttk.Button(
            body,
            text="Jump to Suggested Correction",
            command=self.jump_to_suggested_correction,
            **semantic_button_options("secondary"),
        )
        self.btn_jump_suggested.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(SPACING.inner, 0))

        self.btn_ground_truth = ttk.Button(
            body,
            text="Lock current frame as ground truth",
            command=self.toggle_ground_truth_current_frame,
            **semantic_button_options("secondary"),
        )
        self.btn_ground_truth.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(SPACING.inner, 0))

        return section

    def _on_ghost_range_scale_changed(self, val):
        ival = int(round(float(val)))
        self.ghost_range_var.set(ival)
        if hasattr(self, "lbl_ghost_range_val"):
            self.lbl_ghost_range_val.configure(text=str(ival))

    def jump_to_suggested_correction(self):
        suggested = getattr(self.seg_state, "leverage_suggested_frame", None)
        if suggested is not None:
            self.slider.set(suggested)
            if hasattr(self, "log_info"):
                self.log_info("View", f"Jumped to suggested correction frame {suggested + 1}")
        else:
            if hasattr(self, "log_info"):
                self.log_info("View", "No suggested correction frame available")


    def _create_view_panel(self, parent, *, row, column, title, padx=(0, 0)):
        panel = ttk.Frame(parent, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.card), style="AppSurface.TFrame")
        panel.grid(row=row, column=column, sticky="nsew", padx=padx)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text=title, style="AppSectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, SPACING.inner))

        body = ttk.Frame(panel, style="AppInset.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        return panel, body

    def _create_frame_overlay(self, parent):
        overlay = ttk.Frame(parent, padding=(8, 6), style="AppOverlay.TFrame")
        overlay.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)
        overlay.columnconfigure(0, weight=1)
        ttk.Label(overlay, textvariable=self.frame_status_var, style="AppOverlayValue.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(overlay, textvariable=self.frame_meta_var, style="AppOverlayMeta.TLabel").grid(row=1, column=0, sticky="w")
        return overlay

    def _set_tool_mode(self, mode):
        mode = str(mode)
        if self.tool_mode.get() == mode:
            return
        if is_region_tool_mode(mode):
            setter = getattr(self, "_set_selected_region_id", None)
            if callable(setter):
                setter(None)
            reset_range = getattr(self, "_reset_region_options_to_default_range", None)
            if callable(reset_range):
                reset_range()
        self.tool_mode.set(mode)

    def _on_tool_mode_changed(self):
        # StringVar traces fire on every write, including same-value writes from
        # hotkey handlers; skip the expensive sync/render work when nothing changed.
        current = str(self.tool_mode.get())
        previous = getattr(self, "_last_handled_tool_mode", None)
        if previous == current:
            return
        self._last_handled_tool_mode = current
        controller = getattr(self, "interaction_controller", None)
        if previous is not None and controller is not None and hasattr(controller, "on_tool_mode_changed"):
            controller.on_tool_mode_changed(previous, current)
        if is_region_tool_mode(current):
            setter = getattr(self, "_set_selected_region_id", None)
            if callable(setter):
                setter(None)
            reset_range = getattr(self, "_reset_region_options_to_default_range", None)
            if callable(reset_range):
                reset_range()
        self._sync_tool_mode_buttons()
        self._sync_tool_options()
        if hasattr(self, "_queue_display_update"):
            self._queue_display_update(True)
        else:
            self.update_display()

    def _sync_tool_mode_buttons(self):
        current = str(self.tool_mode.get())
        if getattr(self, "_active_tool_mode_button_state", None) == current:
            return
        self._active_tool_mode_button_state = current
        mapping = {
            getattr(self, "btn_tool_select", None): ("select", "select"),
            getattr(self, "btn_tool_point_pos", None): ("point_pos", "point_pos"),
            getattr(self, "btn_tool_point_neg", None): ("point_neg", "point_neg"),
            getattr(self, "btn_tool_brush", None): ("brush", "brush"),
            getattr(self, "btn_tool_eraser", None): ("eraser", "eraser"),
            getattr(self, "btn_tool_fill", None): ("fill", "fill"),
            getattr(self, "btn_tool_fill_erase", None): ("fill_erase", "fill_erase"),
            getattr(self, "btn_tool_box", None): ("box", "box"),
            getattr(self, "btn_tool_region_include", None): (REGION_INCLUDE_TOOL, REGION_INCLUDE_TOOL),
            getattr(self, "btn_tool_region_exclude", None): (REGION_EXCLUDE_TOOL, REGION_EXCLUDE_TOOL),
        }
        normal_icons = getattr(self, "_analysis_toolbar_icons", {}) or {}
        active_icons = getattr(self, "_analysis_toolbar_active_icons", {}) or {}
        for button, (mode, icon_key) in mapping.items():
            if button is None:
                continue
            is_active = current == mode
            options = {"style": "AppSegmentedActive.TButton" if is_active else "AppSegmented.TButton"}
            icon = (active_icons if is_active else normal_icons).get(icon_key)
            if icon is not None:
                options["image"] = icon
            button.configure(**options)

    def _sync_tool_options(self):
        frames = getattr(self, "tool_option_frames", {}) or {}
        tool_mode = getattr(self, "tool_mode", None)
        current = str(tool_mode.get()) if tool_mode is not None else "select"
        active = frames.get(current) or frames.get("select")
        if current == "select" and getattr(self, "selected_region_id", None):
            active = frames.get(REGION_INCLUDE_TOOL) or active
        if active is getattr(self, "_active_tool_option_frame", None):
            self._sync_region_options_state()
            return
        seen = set()
        for frame in frames.values():
            if frame in seen:
                continue
            seen.add(frame)
            try:
                frame.grid_remove()
            except Exception:
                pass
        if active is not None:
            active.grid()
        self._active_tool_option_frame = active
        self._sync_region_options_state()

    def _sync_region_options_state(self):
        title = getattr(self, "lbl_region_options_title", None)
        if title is None:
            return
        current = str(getattr(getattr(self, "tool_mode", None), "get", lambda: "select")())
        selected_region_id = getattr(self, "selected_region_id", None)
        selected_region = self.seg_state.get_persistent_region(selected_region_id) if selected_region_id else None
        draft_points = []
        draft_closed = False
        controller = getattr(self, "interaction_controller", None)
        if controller is not None and hasattr(controller, "get_region_draft_points"):
            draft_points = controller.get_region_draft_points()
            if hasattr(controller, "is_region_draft_closed"):
                draft_closed = bool(controller.is_region_draft_closed())
        has_draft = bool(draft_points)
        can_close = len(draft_points) >= 3 and not draft_closed
        can_add = len(draft_points) >= 3 and draft_closed
        if selected_region is not None and not has_draft:
            mode = str(selected_region.get("mode", "include"))
            title.configure(text=f"Selected {'Exclude' if mode == 'exclude' else 'Include'} Region")
            convert_text = "Convert to Include" if mode == "exclude" else "Convert to Exclude"
            self.btn_region_convert.configure(text=convert_text, state="normal")
            self.btn_region_add.configure(state="disabled")
            self.btn_region_close_shape.configure(state="disabled")
            self.btn_region_discard.configure(state="disabled")
            return
        title.configure(text="Exclude Region" if current == REGION_EXCLUDE_TOOL else "Include Region")
        self.btn_region_convert.configure(text="Convert Selected", state="disabled")
        self.btn_region_add.configure(state="normal" if can_add else "disabled")
        self.btn_region_close_shape.configure(state="normal" if has_draft and can_close else "disabled")
        self.btn_region_discard.configure(state="normal" if has_draft else "disabled")

    def _lock_tool_options_slot_size(self):
        slot = getattr(self, "tool_options_slot", None)
        frames = getattr(self, "tool_option_frames", {}) or {}
        if slot is None or not frames:
            return
        try:
            self.root.update_idletasks()
        except Exception:
            pass

        unique_frames = []
        seen = set()
        for frame in frames.values():
            if frame in seen:
                continue
            seen.add(frame)
            unique_frames.append(frame)

        widths = []
        heights = []
        for frame in unique_frames:
            was_mapped = bool(frame.winfo_ismapped())
            if not was_mapped:
                frame.grid()
            try:
                frame.update_idletasks()
                widths.append(int(frame.winfo_reqwidth()))
                heights.append(int(frame.winfo_reqheight()))
            except Exception:
                pass
            if not was_mapped:
                frame.grid_remove()

        if not widths or not heights:
            return

        slot.configure(width=max(widths), height=max(heights))
        slot.grid_propagate(False)
        self._sync_tool_options()

    def _parse_entry_frame_range(self):
        total = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if total <= 0:
            return 0, 0, 0
        try:
            start_idx = max(0, min(total - 1, int(float(self.spin_prop_start.get())) - 1))
        except Exception:
            start_idx = 0
        try:
            end_idx = max(0, min(total - 1, int(float(self.spin_prop_end.get())) - 1))
        except Exception:
            end_idx = total - 1
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        return total, start_idx, end_idx

    def _redraw_propagation_range_bar(self):
        canvas = getattr(self, "propagation_range_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        canvas.create_rectangle(0, 0, width, height, fill=SLIDER_OVERLAY_BACKGROUND, outline="")
        total, start_idx, end_idx = self._parse_entry_frame_range()
        if total <= 0:
            return
        left = int((start_idx / max(1, total - 1)) * (width - 1))
        right = int((end_idx / max(1, total - 1)) * (width - 1))
        if right <= left:
            right = min(width, left + 3)
        canvas.create_rectangle(left, 3, right, height - 3, fill=APP_COLORS["accent"], outline="")
        canvas.create_rectangle(max(0, left - 1), 1, min(width, left + 2), height - 1, fill=APP_COLORS["success"], outline="")
        canvas.create_rectangle(max(0, right - 2), 1, min(width, right + 1), height - 1, fill=APP_COLORS["danger"], outline="")

    def _ensure_overlay_tooltip(self):
        return getattr(self, "_tooltip_manager", None) or _tooltip_manager_for_widget(self.root)

    def _show_overlay_tooltip(self, event, text):
        if not text:
            self._hide_overlay_tooltip()
            return
        self._ensure_overlay_tooltip().show_at_event(event, text)

    def _hide_overlay_tooltip(self, _event=None):
        self._ensure_overlay_tooltip().hide()

    def _on_slider_overlay_motion(self, event):
        regions = list(getattr(self, "_slider_overlay_regions", []))
        for left, right, text in regions:
            if float(left) <= float(event.x) <= float(right):
                self._show_overlay_tooltip(event, text)
                return
        self._hide_overlay_tooltip()

    def _add_strip_separator(self, parent, column, *, vertical=True):
        separator = ttk.Separator(parent, orient="vertical" if vertical else "horizontal")
        if vertical:
            separator.grid(row=0, column=column, sticky="ns", padx=SPACING.inner)
        else:
            separator.grid(row=0, column=column, sticky="ns", padx=SPACING.inner)

    def _configure_text_cursor(self):
        insert_cursor = APP_COLORS["text"]
        for text_widget in [getattr(self, "spin_prop_start", None), getattr(self, "spin_prop_end", None), getattr(self, "entry_frames_per_sec", None)]:
            if text_widget is None:
                continue
            try:
                text_widget.configure(insertbackground=insert_cursor, insertwidth=2, insertontime=600, insertofftime=300)
            except Exception:
                try:
                    text_widget.configure(insertcolor=insert_cursor, insertwidth=2, insertontime=600, insertofftime=300)
                except Exception:
                    pass

    def _disable_button_focus(self, parent):
        for widget in parent.winfo_children():
            try:
                if str(widget.winfo_class()) in {"TButton", "Button"}:
                    widget.configure(takefocus=False)
            except Exception:
                pass
            self._disable_button_focus(widget)

    def _bind_clicks_to_clear_text_focus(self, parent):
        text_classes = {"TEntry", "Entry", "TSpinbox", "Spinbox", "Text", "TCombobox", "Combobox"}
        skip_classes = {"Treeview"}
        for widget in parent.winfo_children():
            try:
                widget_class = str(widget.winfo_class())
            except Exception:
                widget_class = ""
            if widget_class not in text_classes | skip_classes:
                try:
                    widget.bind("<Button-1>", self._focus_clicked_widget, add="+")
                except Exception:
                    pass
            self._bind_clicks_to_clear_text_focus(widget)

    def _focus_clicked_widget(self, event):
        widget = getattr(event, "widget", None)
        if widget is None:
            return None
        try:
            widget.focus_set()
        except Exception:
            try:
                self.root.focus_set()
            except Exception:
                return None
        return None

    def _bind_shortcuts(self):
        is_mac = sys.platform == "darwin"
        mod_key = "Command" if is_mac else "Control"

        self.root.bind(f"<{mod_key}-z>", self.on_undo)
        self.root.bind(f"<{mod_key}-Z>", self.on_redo)
        self.root.bind(f"<{mod_key}-Shift-z>", self.on_redo)
        self.root.bind(f"<{mod_key}-s>", self._save_current_masks_hotkey)
        self.root.bind(f"<{mod_key}-S>", self._save_current_masks_hotkey)
        self.root.bind("<Left>", self.on_nav_left)
        self.root.bind("<Right>", self.on_nav_right)
        self.root.bind("<Delete>", self.delete_selected_point)
        self.root.bind("<BackSpace>", self.delete_selected_point)
        self.root.bind("<b>", self._set_tool_brush_hotkey)
        self.root.bind("<B>", self._set_tool_brush_hotkey)
        self.root.bind("<e>", self._set_tool_eraser_hotkey)
        self.root.bind("<E>", self._set_tool_eraser_hotkey)
        self.root.bind("<g>", self._set_tool_fill_hotkey)
        self.root.bind("<G>", self._set_tool_fill_erase_hotkey)
        self.root.bind("<k>", self._set_tool_box_hotkey)
        self.root.bind("<K>", self._set_tool_box_hotkey)
        self.root.bind("<r>", self._set_tool_region_hotkey)
        self.root.bind("<R>", self._set_tool_region_exclude_hotkey)
        self.root.bind("<v>", self._set_tool_select_hotkey)
        self.root.bind("<V>", self._set_tool_select_hotkey)
        self.root.bind("<l>", self._toggle_ground_truth_hotkey)
        self.root.bind("<L>", self._toggle_ground_truth_hotkey)
        self.root.bind("<KeyPress-space>", self._set_space_pan_active, add="+")
        self.root.bind("<KeyRelease-space>", self._clear_space_pan_active, add="+")
        self.root.bind("<KeyPress-p>", self._set_mask_peek_hold_active, add="+")
        self.root.bind("<KeyPress-P>", self._set_mask_peek_hold_active, add="+")
        self.root.bind("<KeyRelease-p>", self._clear_mask_peek_hold_active, add="+")
        self.root.bind("<KeyRelease-P>", self._clear_mask_peek_hold_active, add="+")
        self.root.bind("<Key-plus>", self._set_tool_point_pos_hotkey, add="+")
        self.root.bind("<Key-equal>", self._set_tool_point_pos_hotkey, add="+")
        self.root.bind("<Key-minus>", self._set_tool_point_neg_hotkey, add="+")
        self.root.bind("<Key-underscore>", self._set_tool_point_neg_hotkey, add="+")
        self.root.bind(f"<{mod_key}-plus>", self._zoom_in_hotkey, add="+")
        self.root.bind(f"<{mod_key}-equal>", self._zoom_in_hotkey, add="+")
        self.root.bind(f"<{mod_key}-minus>", self._zoom_out_hotkey, add="+")
        self.root.bind(f"<{mod_key}-underscore>", self._zoom_out_hotkey, add="+")
        self.root.bind("<Key-0>", self._reset_zoom_hotkey, add="+")
