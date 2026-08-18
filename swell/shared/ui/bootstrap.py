from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk as tk_ttk

BOOTSTRAP_AVAILABLE = False
ttk = tk_ttk
Style = tk_ttk.Style


# Shown in the image dialogs that pan and zoom a canvas (Set ROI, Set Scale). Panning
# and the zoom keys are otherwise undiscoverable -- nothing on screen mentions them.
VIEW_NAVIGATION_HINT = "Hold Space or Shift and drag to pan. Press + or - to zoom, 0 to fit."

# Bit for Shift in a Tk event's `state` mask.
_SHIFT_MASK = 0x0001


def pan_modifier_active(event, *, space_requested: bool) -> bool:
    """True when a click should pan the view instead of acting on the image."""
    try:
        shift_held = bool(int(getattr(event, "state", 0)) & _SHIFT_MASK)
    except (TypeError, ValueError):
        shift_held = False
    return bool(space_requested) or shift_held


def create_root_window(*, themename: str = "darkly"):
    return tk.Tk()


# Reserved for OS chrome (menu bar, dock, taskbar) and window decorations. Tk cannot
# report the usable work area portably, so we approximate it from the raw screen size.
SCREEN_MARGIN_W = 40
SCREEN_MARGIN_H = 80


def screen_work_area(window) -> tuple[int, int]:
    """Usable screen area in pixels, or (0, 0) when it cannot be determined."""
    try:
        screen_w = int(window.winfo_screenwidth())
        screen_h = int(window.winfo_screenheight())
    except Exception:
        return (0, 0)
    if screen_w <= 1 or screen_h <= 1:
        return (0, 0)
    return (max(1, screen_w - SCREEN_MARGIN_W), max(1, screen_h - SCREEN_MARGIN_H))


def clamp_to_work_area(window, width: int, height: int) -> tuple[int, int]:
    """Shrink a desired window size so it fits on the current display."""
    avail_w, avail_h = screen_work_area(window)
    target_w = int(width)
    target_h = int(height)
    if avail_w > 0:
        target_w = min(target_w, avail_w)
    if avail_h > 0:
        target_h = min(target_h, avail_h)
    return max(1, target_w), max(1, target_h)


def center_window_on_screen(window, *, width: int | None = None, height: int | None = None) -> None:
    try:
        # Check current geometry string (e.g. "680x1+0+0" or "1x1+0+0").
        # If geometry was locked with a placeholder dimension (typically height=1),
        # we temporarily release it by setting geometry("") to let Tkinter layout propagate.
        try:
            geom = window.geometry()
            if not isinstance(geom, str):
                geom = ""
        except Exception:
            geom = ""
        match = re.match(r"^(\d+)x(\d+)", geom) if geom else None
        current_w, current_h = (int(match.group(1)), int(match.group(2))) if match else (None, None)

        if (width is None and (current_w is None or current_w <= 1)) or \
           (height is None and (current_h is None or current_h <= 1)):
            try:
                window.geometry("")
            except Exception:
                pass

        window.update_idletasks()
        target_width = int(width) if width is not None else int(window.winfo_width())
        target_height = int(height) if height is not None else int(window.winfo_height())
        if target_width <= 1:
            target_width = int(window.winfo_reqwidth())
        if target_height <= 1:
            target_height = int(window.winfo_reqheight())
        
        # Check minsize of window and clamp to it if it is configured
        try:
            min_w, min_h = window.minsize()
            if min_w > 0:
                target_width = max(target_width, min_w)
            if min_h > 0:
                target_height = max(target_height, min_h)
        except Exception:
            pass

        target_width, target_height = clamp_to_work_area(window, max(1, target_width), max(1, target_height))

        # A minsize larger than the display would let the window manager override the clamp
        # above and push the bottom of the window off-screen, so relax it to what fits.
        try:
            min_w, min_h = window.minsize()
            if int(min_w) > target_width or int(min_h) > target_height:
                window.minsize(min(int(min_w), target_width), min(int(min_h), target_height))
        except Exception:
            pass

        x = max(0, int((int(window.winfo_screenwidth()) - target_width) / 2))
        y = max(0, int((int(window.winfo_screenheight()) - target_height) / 2))
        window.geometry(f"{target_width}x{target_height}+{x}+{y}")
    except Exception:
        return


def semantic_button_options(kind: str) -> dict[str, str]:
    normalized = str(kind or "secondary").strip().lower() or "secondary"
    mapping = {
        "primary": "AppAccent.TButton",
        "success": "AppAccent.TButton",
        "secondary": "AppQuiet.TButton",
        "danger": "AppDanger.TButton",
    }
    return {"style": mapping.get(normalized, "AppQuiet.TButton")}


def scrollable_body_budget(window, *, chrome_height: int) -> int:
    """Tallest a scrollable body may grow before it should start scrolling.

    `chrome_height` is the vertical room the dialog needs outside that body -- its
    padding plus any pinned rows such as a status line or the action buttons.
    """
    _, work_h = screen_work_area(window)
    if work_h <= 0:
        return 400
    return max(120, int(work_h) - int(chrome_height))


_WHEEL_SEQUENCES = ("<MouseWheel>", "<Button-4>", "<Button-5>")


def build_scrollable_body(
    parent,
    *,
    style: str = "AppShell.TFrame",
    canvas_bg: str | None = None,
    max_height: int | None = None,
):
    """Build a vertically scrolling region inside ``parent``.

    Returns ``(container, body, refresh)``. Callers grid/pack ``container`` with weight,
    put their widgets in ``body`` using whatever geometry manager they already use, and
    call ``refresh()`` once the body is populated. ``refresh`` recomputes the scrollregion,
    hides the scrollbar while everything fits, and binds the mouse wheel to the current
    descendants of ``body``.

    A canvas does not inherit the requested height of the window item inside it, so a
    window sized from ``winfo_reqheight()`` would collapse around the canvas default
    rather than growing with its content. Pass ``max_height`` to have ``refresh`` size the
    canvas to its content up to that cap, which restores the natural-size propagation the
    caller had before the content was made scrollable.
    """
    container = tk_ttk.Frame(parent, style=style)
    container.columnconfigure(0, weight=1)
    # The themed scrollbar reports a 1px requested width, so reserve the track width
    # the theme intends (see `width=12` in theme._configure_scrollbar_style).
    container.columnconfigure(1, weight=0, minsize=12)
    container.rowconfigure(0, weight=1)

    canvas_options = {"highlightthickness": 0, "bd": 0}
    if canvas_bg:
        canvas_options["bg"] = canvas_bg
    canvas = tk.Canvas(container, **canvas_options)
    canvas.grid(row=0, column=0, sticky="nsew")

    scrollbar = tk_ttk.Scrollbar(container, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
    scrollbar.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scrollbar.set)

    body = tk_ttk.Frame(canvas, style=style)
    window_id = canvas.create_window((0, 0), window=body, anchor="nw")

    # `applied_*` hold the last values pushed into Tk. Re-applying an unchanged value
    # still schedules a relayout, and each relayout re-enters these handlers, so the
    # pair can trade idle work forever on a window whose geometry never settles.
    state = {
        "scrollbar_visible": True,
        "bound": set(),
        "applied_scrollregion": None,
        "applied_canvas_height": None,
        "syncing": False,
    }

    def _content_height() -> int:
        try:
            bbox = canvas.bbox("all")
        except Exception:
            return 0
        if not bbox:
            return 0
        return int(bbox[3]) - int(bbox[1])

    def _sync_scrollregion() -> None:
        try:
            bbox = canvas.bbox("all")
            if bbox is None or bbox == state["applied_scrollregion"]:
                return
            state["applied_scrollregion"] = bbox
            canvas.configure(scrollregion=bbox)
        except Exception:
            return

    def _sync_scrollbar() -> None:
        # Hide the scrollbar entirely while the body fits, so short dialogs keep
        # looking like plain dialogs.
        try:
            visible = _content_height() > int(canvas.winfo_height()) + 1
        except Exception:
            return
        if visible == state["scrollbar_visible"]:
            return
        try:
            if visible:
                scrollbar.grid()
            else:
                scrollbar.grid_remove()
                canvas.yview_moveto(0.0)
        except Exception:
            return
        state["scrollbar_visible"] = visible

    def _on_wheel(event):
        if _content_height() <= int(canvas.winfo_height()) + 1:
            return None
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        direction = 0
        if delta:
            direction = -1 if float(delta) > 0 else 1
        elif num == 4:
            direction = -1
        elif num == 5:
            direction = 1
        if direction:
            try:
                canvas.yview_scroll(direction, "units")
            except Exception:
                return None
        return "break"

    def _bind_wheel(widget) -> None:
        ident = id(widget)
        if ident in state["bound"]:
            return
        for sequence in _WHEEL_SEQUENCES:
            try:
                widget.bind(sequence, _on_wheel, add="+")
            except Exception:
                return
        state["bound"].add(ident)

    def _bind_wheel_tree(widget) -> None:
        _bind_wheel(widget)
        try:
            children = list(widget.winfo_children())
        except Exception:
            return
        for child in children:
            _bind_wheel_tree(child)

    def _on_body_configure(_event=None):
        if state["syncing"]:
            return
        state["syncing"] = True
        try:
            _sync_scrollregion()
            _sync_scrollbar()
        finally:
            state["syncing"] = False

    def _on_canvas_configure(event=None):
        if state["syncing"]:
            return
        state["syncing"] = True
        try:
            try:
                width = max(1, int(getattr(event, "width", canvas.winfo_width())))
                canvas.itemconfigure(window_id, width=width)
            except Exception:
                pass
            _sync_scrollregion()
            _sync_scrollbar()
        finally:
            state["syncing"] = False

    body.bind("<Configure>", _on_body_configure, add="+")
    canvas.bind("<Configure>", _on_canvas_configure, add="+")

    def _sync_canvas_height() -> None:
        if max_height is None:
            return
        try:
            content = _content_height()
            if content <= 0:
                return
            target = max(1, min(content, int(max_height)))
            if target == state["applied_canvas_height"]:
                return
            state["applied_canvas_height"] = target
            canvas.configure(height=target)
        except Exception:
            return

    def refresh() -> None:
        try:
            canvas.update_idletasks()
        except Exception:
            pass
        _sync_scrollregion()
        _sync_canvas_height()
        _sync_scrollbar()
        _bind_wheel(canvas)
        _bind_wheel_tree(body)

    return container, body, refresh
