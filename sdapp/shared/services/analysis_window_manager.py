from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalysisWindowRef:
    key: tuple[str, str]
    window: object
    app: object


class AnalysisWindowManager:
    def __init__(self) -> None:
        self._windows: dict[tuple[str, str], AnalysisWindowRef] = {}

    def get(self, sd_set_id: str, event_id: str) -> AnalysisWindowRef | None:
        return self._windows.get((str(sd_set_id), str(event_id)))

    def open_event_window(self, sd_set_id: str, event_id: str, window, app) -> AnalysisWindowRef:
        key = (str(sd_set_id), str(event_id))
        ref = AnalysisWindowRef(key=key, window=window, app=app)
        self._windows[key] = ref
        return ref

    def focus_event_window(self, sd_set_id: str, event_id: str) -> bool:
        ref = self.get(sd_set_id, event_id)
        if ref is None:
            return False
        win = ref.window
        try:
            if hasattr(win, "winfo_exists") and win.winfo_exists():
                win.lift()
                win.focus_force()
                return True
        except Exception:
            return False
        return False

    def close_event_window(self, sd_set_id: str, event_id: str) -> None:
        key = (str(sd_set_id), str(event_id))
        ref = self._windows.pop(key, None)
        if ref is None:
            return
        try:
            if hasattr(ref.window, "winfo_exists") and ref.window.winfo_exists():
                if hasattr(ref.app, "on_close"):
                    ref.app.on_close()
                else:
                    ref.window.destroy()
        except Exception:
            pass

    def unregister(self, sd_set_id: str, event_id: str) -> None:
        self._windows.pop((str(sd_set_id), str(event_id)), None)

    def close_all(self) -> None:
        refs = list(self._windows.values())
        self._windows.clear()
        for ref in refs:
            try:
                if hasattr(ref.window, "winfo_exists") and ref.window.winfo_exists():
                    if hasattr(ref.app, "on_close"):
                        ref.app.on_close()
                    else:
                        ref.window.destroy()
            except Exception:
                pass
