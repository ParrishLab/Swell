from tkinter import ttk


def apply_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background="#1e1f22")
    style.configure("TLabel", background="#1e1f22", foreground="#e6e6e6")
    style.configure("TLabelFrame", background="#1e1f22", foreground="#e6e6e6")
    style.configure("TLabelFrame.Label", background="#1e1f22", foreground="#e6e6e6")
    style.configure("TButton", padding=6)
    style.configure("TEntry", padding=4)
    style.configure("TSpinbox", padding=4)
    style.configure("Preview.TFrame", background="#2a2b2f")
    style.map("TButton", foreground=[("disabled", "#9a9a9a")])
