from __future__ import annotations

from dataclasses import dataclass
from tkinter import ttk as tk_ttk

from sdapp.shared.ui.bootstrap import BOOTSTRAP_AVAILABLE, Style


@dataclass(frozen=True)
class LayoutSpacing:
    outer: int = 14
    inner: int = 10
    gap: int = 6
    card: int = 8


SPACING = LayoutSpacing()
CANVAS_BACKGROUND = "#0c1015"
SLIDER_OVERLAY_BACKGROUND = "#1a2027"


def _theme_palette(style) -> dict[str, str]:
    colors = getattr(style, "colors", None)
    if colors is None:
        return {
            "app_bg": "#171b20",
            "surface_bg": "#1f242b",
            "strip_bg": "#1c2128",
            "sidebar_bg": "#1d2229",
            "subpanel_bg": "#222830",
            "inset_bg": "#0f1318",
            "control_bg": "#2a3038",
            "control_active": "#313842",
            "text": "#edf1f3",
            "muted": "#8d97a2",
            "muted_soft": "#aeb7bf",
            "border": "#2a3139",
            "danger": "#7e4348",
            "danger_active": "#915157",
            "accent": "#1b75bc",
        }
    return {
        "app_bg": "#171b20",
        "surface_bg": "#1f242b",
        "strip_bg": "#1c2128",
        "sidebar_bg": "#1d2229",
        "subpanel_bg": "#222830",
        "inset_bg": "#0f1318",
        "control_bg": "#2a3038",
        "control_active": "#313842",
        "text": str(getattr(colors, "fg", "#edf1f3")),
        "muted": "#8d97a2",
        "muted_soft": "#aeb7bf",
        "border": "#2a3139",
        "danger": "#7e4348",
        "danger_active": "#915157",
        "accent": "#1b75bc",
    }


def apply_theme(root, *, themename: str = "darkly"):
    bootstrap_style = Style(root) if not BOOTSTRAP_AVAILABLE else getattr(root, "style", None) or Style()
    try:
        if BOOTSTRAP_AVAILABLE:
            current_theme = bootstrap_style.theme_use()
            if current_theme != themename:
                bootstrap_style.theme_use(themename)
        else:
            bootstrap_style.theme_use("clam")
    except Exception:
        pass

    # ttkbootstrap's Style.configure()/map() auto-builder is fragile for
    # built-in ttk styles in frozen macOS apps. After the theme is selected,
    # switch to plain ttk styling against the same themed root.
    style = tk_ttk.Style(root) if BOOTSTRAP_AVAILABLE and root is not None else bootstrap_style

    palette = _theme_palette(style)
    base_font = ("TkDefaultFont", 10)

    if root is not None:
        try:
            root.configure(background=palette["app_bg"])
        except Exception:
            pass

    style.configure("TFrame", background=palette["app_bg"])
    style.configure("AppShell.TFrame", background=palette["app_bg"])
    style.configure("AppCard.TFrame", background=palette["surface_bg"], borderwidth=0, relief="flat")
    style.configure("AppCardBody.TFrame", background=palette["surface_bg"])
    style.configure("AppSurface.TFrame", background=palette["surface_bg"], borderwidth=0, relief="flat")
    style.configure("AppStrip.TFrame", background=palette["strip_bg"], borderwidth=0, relief="flat")
    style.configure("AppSubpanel.TFrame", background=palette["subpanel_bg"], borderwidth=0, relief="flat")
    style.configure("AppSidebar.TFrame", background=palette["sidebar_bg"], borderwidth=0, relief="flat")
    style.configure("AppInset.TFrame", background=palette["inset_bg"], borderwidth=0, relief="flat")
    style.configure("AppDivider.TFrame", background=palette["border"], borderwidth=0, relief="flat")

    style.configure("TPanedwindow", background=palette["app_bg"], sashwidth=6)
    style.configure("TSeparator", background=palette["border"])

    style.configure("TLabel", background=palette["app_bg"], foreground=palette["text"], font=base_font)
    for label_style, background in {
        "AppCard.TLabel": palette["surface_bg"],
        "AppStrip.TLabel": palette["strip_bg"],
        "AppSidebar.TLabel": palette["sidebar_bg"],
        "AppSubpanel.TLabel": palette["subpanel_bg"],
    }.items():
        style.configure(label_style, background=background, foreground=palette["text"], font=base_font)

    style.configure(
        "AppSectionTitle.TLabel",
        background=palette["surface_bg"],
        foreground=palette["muted_soft"],
        font=("TkDefaultFont", 8, "bold"),
    )
    style.configure(
        "AppStripTitle.TLabel",
        background=palette["strip_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 8, "bold"),
    )
    style.configure(
        "AppSidebarTitle.TLabel",
        background=palette["sidebar_bg"],
        foreground=palette["muted_soft"],
        font=("TkDefaultFont", 8, "bold"),
    )
    style.configure(
        "AppSubpanelTitle.TLabel",
        background=palette["subpanel_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 8, "bold"),
    )
    style.configure(
        "AppValue.TLabel",
        background=palette["strip_bg"],
        foreground=palette["text"],
        font=("TkDefaultFont", 10, "bold"),
    )
    style.configure(
        "AppDataValue.TLabel",
        background=palette["app_bg"],
        foreground=palette["text"],
        font=("TkDefaultFont", 10, "bold"),
    )
    style.configure(
        "AppMeta.TLabel",
        background=palette["app_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 8),
    )
    style.configure(
        "AppMicro.TLabel",
        background=palette["app_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 7),
    )
    style.configure(
        "AppSurfaceMeta.TLabel",
        background=palette["surface_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 8),
    )
    style.configure(
        "AppSurfaceMicro.TLabel",
        background=palette["surface_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 7),
    )
    style.configure(
        "AppStripMeta.TLabel",
        background=palette["strip_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 8),
    )
    style.configure(
        "AppSubpanelMeta.TLabel",
        background=palette["subpanel_bg"],
        foreground=palette["muted"],
        font=("TkDefaultFont", 8),
    )
    style.configure(
        "AppOverlay.TFrame",
        background="#161b21",
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "AppOverlayValue.TLabel",
        background="#161b21",
        foreground=palette["text"],
        font=("TkDefaultFont", 9, "bold"),
    )
    style.configure(
        "AppOverlayMeta.TLabel",
        background="#161b21",
        foreground=palette["muted"],
        font=("TkDefaultFont", 8),
    )

    style.configure(
        "AppPreviewGrip.TLabel",
        background=palette["inset_bg"],
        foreground=palette["text"],
        font=("TkDefaultFont", 10, "bold"),
        anchor="center",
    )
    style.configure("AppPreview.TFrame", background=palette["inset_bg"], borderwidth=0, relief="flat")

    button_common = {
        "font": ("TkDefaultFont", 9),
        "padding": (8, 4),
        "borderwidth": 0,
        "focuscolor": palette["control_bg"],
        "focusthickness": 0,
        "foreground": palette["text"],
    }
    style.configure(
        "AppQuiet.TButton",
        background=palette["control_bg"],
        darkcolor=palette["control_bg"],
        lightcolor=palette["control_bg"],
        bordercolor=palette["border"],
        **button_common,
    )
    style.map(
        "AppQuiet.TButton",
        background=[("active", palette["control_active"]), ("pressed", palette["control_active"])],
        darkcolor=[("active", palette["control_active"]), ("pressed", palette["control_active"])],
        lightcolor=[("active", palette["control_active"]), ("pressed", palette["control_active"])],
        foreground=[("disabled", palette["muted"])],
    )
    style.configure(
        "AppAccent.TButton",
        background=palette["accent"],
        darkcolor=palette["accent"],
        lightcolor=palette["accent"],
        bordercolor=palette["accent"],
        **(button_common | {"font": ("TkDefaultFont", 10, "bold")}),
    )
    style.map(
        "AppAccent.TButton",
        background=[("active", "#2484d1"), ("pressed", "#165f98")],
        darkcolor=[("active", "#2484d1"), ("pressed", "#165f98")],
        lightcolor=[("active", "#2484d1"), ("pressed", "#165f98")],
        foreground=[("disabled", palette["muted"])],
    )
    style.configure(
        "AppDanger.TButton",
        background=palette["danger"],
        darkcolor=palette["danger"],
        lightcolor=palette["danger"],
        bordercolor=palette["danger"],
        **button_common,
    )
    style.map(
        "AppDanger.TButton",
        background=[("active", palette["danger_active"]), ("pressed", palette["danger_active"])],
        darkcolor=[("active", palette["danger_active"]), ("pressed", palette["danger_active"])],
        lightcolor=[("active", palette["danger_active"]), ("pressed", palette["danger_active"])],
        foreground=[("disabled", palette["muted"])],
    )
    segmented_common = {
        "padding": (10, 4),
        "font": ("TkDefaultFont", 9),
        "borderwidth": 0,
        "focuscolor": palette["control_bg"],
        "focusthickness": 0,
    }
    for style_name in ("AppSegmented.TButton", "AppSegmentedActive.TButton"):
        style.configure(
            style_name,
            background=palette["control_bg"] if style_name == "AppSegmented.TButton" else palette["accent"],
            darkcolor=palette["control_bg"] if style_name == "AppSegmented.TButton" else palette["accent"],
            lightcolor=palette["control_bg"] if style_name == "AppSegmented.TButton" else palette["accent"],
            bordercolor=palette["border"] if style_name == "AppSegmented.TButton" else palette["accent"],
            foreground=palette["text"],
            **segmented_common,
        )
    style.map(
        "AppSegmented.TButton",
        background=[("active", palette["control_active"]), ("pressed", palette["control_active"])],
        darkcolor=[("active", palette["control_active"]), ("pressed", palette["control_active"])],
        lightcolor=[("active", palette["control_active"]), ("pressed", palette["control_active"])],
    )
    style.map(
        "AppSegmentedActive.TButton",
        background=[("active", "#2484d1"), ("pressed", "#165f98")],
        darkcolor=[("active", "#2484d1"), ("pressed", "#165f98")],
        lightcolor=[("active", "#2484d1"), ("pressed", "#165f98")],
    )

    style.configure(
        "AppCompact.TEntry",
        fieldbackground=palette["control_bg"],
        foreground=palette["text"],
        bordercolor=palette["border"],
        lightcolor=palette["control_bg"],
        darkcolor=palette["control_bg"],
        padding=(6, 3),
        insertcolor=palette["text"],
    )
    style.map(
        "AppCompact.TEntry",
        fieldbackground=[("readonly", palette["control_bg"]), ("disabled", palette["control_bg"])],
        foreground=[("disabled", palette["muted"])],
    )
    style.configure(
        "AppCompact.TSpinbox",
        fieldbackground=palette["control_bg"],
        foreground=palette["text"],
        bordercolor=palette["border"],
        lightcolor=palette["control_bg"],
        darkcolor=palette["control_bg"],
        arrowsize=10,
        padding=(6, 2),
        insertcolor=palette["text"],
    )
    style.configure(
        "AppFlat.Horizontal.TScale",
        background=palette["strip_bg"],
        troughcolor=palette["control_bg"],
        bordercolor=palette["border"],
        darkcolor=palette["control_bg"],
        lightcolor=palette["control_bg"],
    )
    style.configure(
        "AppLoading.Horizontal.TProgressbar",
        background=palette["accent"],
        troughcolor=palette["control_bg"],
        bordercolor=palette["border"],
        lightcolor=palette["accent"],
        darkcolor=palette["accent"],
        thickness=8,
    )
    style.configure(
        "AppSubtle.Horizontal.TProgressbar",
        background=palette["accent"],
        troughcolor=palette["inset_bg"],
        bordercolor=palette["border"],
        lightcolor=palette["accent"],
        darkcolor=palette["accent"],
        thickness=8,
    )
    check_common = {
        "foreground": palette["text"],
        "font": ("TkDefaultFont", 9),
        "focuscolor": palette["control_bg"],
        "indicatorbackground": palette["control_bg"],
        "indicatorforeground": palette["text"],
        "indicatormargin": (0, 0, 6, 0),
        "padding": (0, 2),
    }
    style.configure("TCheckbutton", background=palette["app_bg"], **check_common)
    style.configure("AppStrip.TCheckbutton", background=palette["strip_bg"], **check_common)
    style.configure("AppSurface.TCheckbutton", background=palette["surface_bg"], **check_common)
    style.configure("AppSubpanel.TCheckbutton", background=palette["subpanel_bg"], **check_common)
    style.map(
        "TCheckbutton",
        background=[("active", palette["app_bg"]), ("selected", palette["app_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    style.map(
        "AppStrip.TCheckbutton",
        background=[("active", palette["strip_bg"]), ("selected", palette["strip_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    style.map(
        "AppSurface.TCheckbutton",
        background=[("active", palette["surface_bg"]), ("selected", palette["surface_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    style.map(
        "AppSubpanel.TCheckbutton",
        background=[("active", palette["subpanel_bg"]), ("selected", palette["subpanel_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    radio_common = {
        "foreground": palette["text"],
        "font": ("TkDefaultFont", 9),
        "focuscolor": palette["control_bg"],
        "indicatorbackground": palette["control_bg"],
        "indicatorforeground": palette["text"],
        "indicatormargin": (0, 0, 6, 0),
        "padding": (0, 2),
    }
    style.configure("TRadiobutton", background=palette["app_bg"], **radio_common)
    style.configure("AppStrip.TRadiobutton", background=palette["strip_bg"], **radio_common)
    style.configure("AppSurface.TRadiobutton", background=palette["surface_bg"], **radio_common)
    style.configure("AppSubpanel.TRadiobutton", background=palette["subpanel_bg"], **radio_common)
    style.map(
        "TRadiobutton",
        background=[("active", palette["app_bg"]), ("selected", palette["app_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    style.map(
        "AppStrip.TRadiobutton",
        background=[("active", palette["strip_bg"]), ("selected", palette["strip_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    style.map(
        "AppSurface.TRadiobutton",
        background=[("active", palette["surface_bg"]), ("selected", palette["surface_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    style.map(
        "AppSubpanel.TRadiobutton",
        background=[("active", palette["subpanel_bg"]), ("selected", palette["subpanel_bg"])],
        foreground=[("disabled", palette["muted"])],
        indicatorbackground=[("selected", palette["accent"]), ("active", palette["control_active"])],
    )
    style.configure(
        "AppCompact.TCombobox",
        fieldbackground=palette["control_bg"],
        foreground=palette["text"],
        bordercolor=palette["border"],
        lightcolor=palette["control_bg"],
        darkcolor=palette["control_bg"],
        arrowcolor=palette["muted"],
        insertcolor=palette["text"],
        padding=(6, 3),
    )
    style.map(
        "AppCompact.TCombobox",
        fieldbackground=[("readonly", palette["control_bg"]), ("disabled", palette["control_bg"])],
        foreground=[("readonly", palette["text"]), ("disabled", palette["muted"])],
        arrowcolor=[("disabled", palette["muted"])],
    )

    style.configure("Treeview", font=("TkDefaultFont", 9), background=palette["inset_bg"], fieldbackground=palette["inset_bg"], foreground=palette["text"], borderwidth=0)
    style.map("Treeview", background=[("selected", "#31597c")], foreground=[("selected", palette["text"])])
    style.configure("Treeview.Heading", background=palette["surface_bg"], foreground=palette["muted"], font=("TkDefaultFont", 8, "bold"), borderwidth=0)
    _configure_scrollbar_style(
        style,
        background=palette["control_bg"],
        troughcolor=palette["inset_bg"],
        bordercolor=palette["inset_bg"],
        darkcolor=palette["control_bg"],
        lightcolor=palette["control_bg"],
        arrowcolor=palette["muted"],
        borderwidth=0,
        relief="flat",
        width=12,
        arrowsize=0,
    )

    return style


def _configure_scrollbar_style(style, **kwargs) -> None:
    for style_name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        _configure_single_scrollbar_style(style, style_name, **kwargs)
    _configure_scrollbar_layouts(style)


def _configure_single_scrollbar_style(style, style_name: str, **kwargs) -> None:
    try:
        style.configure(style_name, **kwargs)
        return
    except Exception:
        if not BOOTSTRAP_AVAILABLE:
            raise

    # ttkbootstrap's auto-style builder can choke on the built-in scrollbar
    # style when the theme has already created the underlying elements.
    tk_ttk.Style.configure(style, style_name, **kwargs)
    register = getattr(style, "_register_ttkstyle", None)
    if callable(register):
        try:
            register(style_name)
        except Exception:
            pass


def _configure_scrollbar_layouts(style) -> None:
    layout = getattr(style, "layout", None)
    if not callable(layout):
        return
    layouts = {
        "Vertical.TScrollbar": [
            (
                "Vertical.Scrollbar.trough",
                {
                    "sticky": "ns",
                    "children": [
                        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
                    ],
                },
            )
        ],
        "Horizontal.TScrollbar": [
            (
                "Horizontal.Scrollbar.trough",
                {
                    "sticky": "ew",
                    "children": [
                        ("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
                    ],
                },
            )
        ],
    }
    for style_name, style_layout in layouts.items():
        try:
            layout(style_name, style_layout)
        except Exception:
            pass
