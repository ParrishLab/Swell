from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any


class BackgroundTaskRunner:
    """Run worker functions on daemon threads and marshal completion back to Tk."""

    def __init__(self, root) -> None:
        self._root = root
        self._active: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(
        self,
        target: Callable[[], Any],
        *,
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        key: str | None = None,
        drop_if_running: bool = False,
    ) -> threading.Thread | None:
        if key is not None:
            with self._lock:
                running = self._active.get(key)
                if drop_if_running and running is not None and running.is_alive():
                    return None

        def _worker() -> None:
            try:
                result = target()
            except Exception as exc:  # noqa: BLE001
                if callable(on_error):
                    self._dispatch(lambda e=exc: on_error(e))
            else:
                if callable(on_success):
                    self._dispatch(lambda r=result: on_success(r))
            finally:
                if key is not None:
                    with self._lock:
                        active = self._active.get(key)
                        if active is thread:
                            self._active.pop(key, None)

        thread = threading.Thread(target=_worker, daemon=True)
        if key is not None:
            with self._lock:
                self._active[key] = thread
        thread.start()
        return thread

    def is_running(self, key: str) -> bool:
        with self._lock:
            thread = self._active.get(str(key))
            return bool(thread is not None and thread.is_alive())

    def _dispatch(self, callback: Callable[[], None]) -> None:
        root = self._root
        if root is None:
            callback()
            return
        try:
            root.after(0, callback)
        except Exception:
            callback()
