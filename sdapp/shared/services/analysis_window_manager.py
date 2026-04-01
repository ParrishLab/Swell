from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalysisWindowRef:
    key: tuple[str, str]
    window: object
    app: object


@dataclass
class AnalysisWindowCloseResult:
    key: tuple[str, str]
    closed: bool
    forced: bool


class AnalysisWindowManager:
    def __init__(self) -> None:
        self._windows: dict[tuple[str, str], AnalysisWindowRef] = {}

    def get(self, scope_id: str, event_id: str) -> AnalysisWindowRef | None:
        return self._windows.get((str(scope_id), str(event_id)))

    def open_event_window(self, scope_id: str, event_id: str, window, app) -> AnalysisWindowRef:
        key = (str(scope_id), str(event_id))
        ref = AnalysisWindowRef(key=key, window=window, app=app)
        self._windows[key] = ref
        return ref

    def list_windows(self) -> list[AnalysisWindowRef]:
        return list(self._windows.values())

    def focus_event_window(self, scope_id: str, event_id: str) -> bool:
        ref = self.get(scope_id, event_id)
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

    @staticmethod
    def _window_exists(window: object) -> bool:
        try:
            if hasattr(window, "winfo_exists"):
                return bool(window.winfo_exists())
            return True
        except Exception:
            return False

    def _invoke_close(self, ref: AnalysisWindowRef, *, force: bool) -> AnalysisWindowCloseResult:
        key = tuple(ref.key)
        if not self._window_exists(ref.window):
            self._windows.pop(key, None)
            return AnalysisWindowCloseResult(key=key, closed=True, forced=bool(force))
        try:
            if force:
                if hasattr(ref.app, "force_close"):
                    ref.app.force_close()
                elif hasattr(ref.window, "destroy"):
                    ref.window.destroy()
            elif hasattr(ref.app, "on_close"):
                ref.app.on_close()
            elif hasattr(ref.window, "destroy"):
                ref.window.destroy()
        except Exception:
            return AnalysisWindowCloseResult(key=key, closed=False, forced=bool(force))
        closed = not self._window_exists(ref.window)
        if closed:
            self._windows.pop(key, None)
        return AnalysisWindowCloseResult(key=key, closed=closed, forced=bool(force))

    def close_event_window(self, scope_id: str, event_id: str, *, force: bool = False) -> AnalysisWindowCloseResult:
        key = (str(scope_id), str(event_id))
        ref = self._windows.get(key)
        if ref is None:
            return AnalysisWindowCloseResult(key=key, closed=True, forced=bool(force))
        return self._invoke_close(ref, force=force)

    def unregister(self, scope_id: str, event_id: str) -> None:
        self._windows.pop((str(scope_id), str(event_id)), None)

    def close_all(self, *, force: bool = False) -> list[AnalysisWindowCloseResult]:
        results: list[AnalysisWindowCloseResult] = []
        for ref in list(self._windows.values()):
            results.append(self._invoke_close(ref, force=force))
        return results
