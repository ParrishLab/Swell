from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from swell.shared.ui.theme import apply_theme, _theme_palette


def _get_parent_and_verify(parent=None):
    if parent is None:
        if hasattr(tk, "_default_root") and tk._default_root is not None:
            parent = tk._default_root
    if parent is not None:
        try:
            return parent.winfo_toplevel()
        except Exception:
            pass
    return parent


class CustomDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        title: str,
        message: str,
        dialog_type: str = "info",
        buttons: list[tuple[str, object, str]] = None,
        default_button: str | None = None,
        cancel_button: str | None = None,
        has_input: bool = False,
        initial_value: str = "",
    ):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)

        self.parent = parent
        self.result = None

        # Apply styles and retrieve colors
        apply_theme(self)
        style = ttk.Style(self)
        palette = _theme_palette(style)

        # Set dialog background explicitly to match theme
        self.configure(background=palette.get("app_bg", "#171b20"))

        # Grid config
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Outer padding frame
        shell = ttk.Frame(self, padding=20, style="AppShell.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)  # Message area
        shell.rowconfigure(1, weight=0)  # Entry if input
        shell.rowconfigure(2, weight=0)  # Separator
        shell.rowconfigure(3, weight=0)  # Buttons

        # Body frame (Icon + Message layout)
        body_frame = ttk.Frame(shell, style="AppShell.TFrame")
        body_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 15))
        body_frame.columnconfigure(1, weight=1)

        # Draw icon
        icon_text, icon_color = self._get_icon_props(dialog_type, palette)
        if icon_text:
            icon_lbl = ttk.Label(
                body_frame,
                text=icon_text,
                font=("TkDefaultFont", 24, "bold"),
                foreground=icon_color,
                style="TLabel",
            )
            icon_lbl.grid(row=0, column=0, sticky="nw", padx=(0, 15))

        # Message Text
        msg_lbl = ttk.Label(
            body_frame,
            text=message,
            wraplength=380,
            style="TLabel",
            justify="left",
            anchor="nw",
        )
        msg_lbl.grid(row=0, column=1, sticky="nsew")

        # Input Prompt Field
        if has_input:
            self.input_var = tk.StringVar(value=initial_value)
            self.entry = ttk.Entry(shell, textvariable=self.input_var, style="AppCompact.TEntry")
            self.entry.grid(row=1, column=0, sticky="ew", pady=(0, 15))
            self.entry.focus_set()
            if initial_value:
                self.entry.selection_range(0, tk.END)

        # Separator line
        sep = ttk.Separator(shell, orient="horizontal")
        sep.grid(row=2, column=0, sticky="ew", pady=(0, 15))

        # Action Buttons Area
        btns_frame = ttk.Frame(shell, style="AppShell.TFrame")
        btns_frame.grid(row=3, column=0, sticky="e")

        buttons = buttons or [("OK", True, "primary")]
        self.btn_widgets = []
        for idx, (btn_text, btn_val, btn_style) in enumerate(buttons):
            if btn_style == "primary":
                btn_style_class = "AppAccent.TButton"
            elif btn_style == "danger":
                btn_style_class = "AppDanger.TButton"
            else:
                btn_style_class = "AppQuiet.TButton"

            btn = ttk.Button(
                btns_frame,
                text=btn_text,
                style=btn_style_class,
                command=lambda v=btn_val: self._on_button_click(v),
            )
            btn.pack(side="left", padx=(0 if idx == 0 else 10, 0))
            self.btn_widgets.append(btn)

            if btn_text == default_button:
                btn.focus_set()
                self.bind("<Return>", lambda e, v=btn_val: self._on_button_click(v), add="+")

            if btn_text == cancel_button:
                self.bind("<Escape>", lambda e, v=btn_val: self._on_button_click(v), add="+")

        # Fallbacks for safety:
        if cancel_button is not None:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        else:
            self.protocol("WM_DELETE_WINDOW", lambda: self._on_button_click(None))

        # Center, display and make modal
        self._center_window()
        self.deiconify()

        if parent is not None:
            self.transient(parent)
        self.grab_set()

    def _get_icon_props(self, dialog_type: str, palette: dict) -> tuple[str, str]:
        if dialog_type == "info":
            return "ℹ", palette.get("accent", "#1b75bc")
        elif dialog_type == "warning":
            return "⚠", "#e0a800"
        elif dialog_type == "error":
            return "🛑", palette.get("danger", "#7e4348")
        elif dialog_type == "question":
            return "❓", palette.get("accent", "#1b75bc")
        return "", ""

    def _on_button_click(self, value):
        if hasattr(self, "entry") and self.entry.winfo_exists():
            if value is not None and value is not False:
                self.result = self.input_var.get()
            else:
                self.result = None
        else:
            self.result = value
        self.destroy()

    def _on_close(self):
        self._on_button_click(None)

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()

        w = max(420, w)
        h = max(150, h)

        parent = self.parent
        if parent is not None and parent.winfo_viewable():
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        else:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2

        x = max(0, x)
        y = max(0, y)
        self.geometry(f"{w}x{h}+{x}+{y}")


def _run_dialog_thread_safe(func, parent, *args, **kwargs):
    parent = _get_parent_and_verify(parent)
    if threading.current_thread() is threading.main_thread():
        return func(parent, *args, **kwargs)

    if parent is None:
        return func(parent, *args, **kwargs)

    q = queue.Queue()

    def worker():
        try:
            res = func(parent, *args, **kwargs)
            q.put((res, None))
        except Exception as e:
            q.put((None, e))

    parent.after(0, worker)
    res, err = q.get()
    if err is not None:
        raise err
    return res


def showinfo(title: str, message: str, parent=None, **options) -> bool:
    def show(p):
        dlg = CustomDialog(
            p,
            title,
            message,
            dialog_type="info",
            buttons=[("OK", True, "primary")],
            default_button="OK",
            cancel_button="OK",
        )
        if p is not None:
            p.wait_window(dlg)
        else:
            dlg.wait_window(dlg)
        return True
    return _run_dialog_thread_safe(show, parent)


def showwarning(title: str, message: str, parent=None, **options) -> bool:
    def show(p):
        dlg = CustomDialog(
            p,
            title,
            message,
            dialog_type="warning",
            buttons=[("OK", True, "primary")],
            default_button="OK",
            cancel_button="OK",
        )
        if p is not None:
            p.wait_window(dlg)
        else:
            dlg.wait_window(dlg)
        return True
    return _run_dialog_thread_safe(show, parent)


def showerror(title: str, message: str, parent=None, **options) -> bool:
    def show(p):
        dlg = CustomDialog(
            p,
            title,
            message,
            dialog_type="error",
            buttons=[("OK", True, "danger")],
            default_button="OK",
            cancel_button="OK",
        )
        if p is not None:
            p.wait_window(dlg)
        else:
            dlg.wait_window(dlg)
        return True
    return _run_dialog_thread_safe(show, parent)


def askyesno(title: str, message: str, parent=None, **options) -> bool:
    def show(p):
        dlg = CustomDialog(
            p,
            title,
            message,
            dialog_type="question",
            buttons=[("Yes", True, "primary"), ("No", False, "secondary")],
            default_button="Yes",
            cancel_button="No",
        )
        if p is not None:
            p.wait_window(dlg)
        else:
            dlg.wait_window(dlg)
        return bool(dlg.result)
    return _run_dialog_thread_safe(show, parent)


def askyesnocancel(title: str, message: str, parent=None, **options) -> bool | None:
    def show(p):
        dlg = CustomDialog(
            p,
            title,
            message,
            dialog_type="question",
            buttons=[
                ("Yes", True, "primary"),
                ("No", False, "secondary"),
                ("Cancel", None, "secondary"),
            ],
            default_button="Yes",
            cancel_button="Cancel",
        )
        if p is not None:
            p.wait_window(dlg)
        else:
            dlg.wait_window(dlg)
        return dlg.result
    return _run_dialog_thread_safe(show, parent)


def askstring(title: str, prompt: str, parent=None, initialvalue: str = "", **options) -> str | None:
    def show(p):
        dlg = CustomDialog(
            p,
            title,
            prompt,
            dialog_type="question",
            buttons=[("OK", True, "primary"), ("Cancel", False, "secondary")],
            default_button="OK",
            cancel_button="Cancel",
            has_input=True,
            initial_value=initialvalue,
        )
        if p is not None:
            p.wait_window(dlg)
        else:
            dlg.wait_window(dlg)
        return dlg.result
    return _run_dialog_thread_safe(show, parent)
