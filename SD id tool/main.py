from __future__ import annotations

import tkinter as tk

from sd_gui import SDAnalyzerApp


def main() -> None:
    root = tk.Tk()
    SDAnalyzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
