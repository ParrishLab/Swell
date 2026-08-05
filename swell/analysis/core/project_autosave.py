from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import re
from pathlib import Path
from typing import Any, Callable, Optional

from swell.shared.persistence.schema import PROJECT_EXTENSION


@dataclass
class AutosaveSnapshot:
    project_state: dict[str, Any]
    images_manifest: dict[str, Any]
    roi_data: dict[str, Any]
    event_payloads: dict[str, Any]
    embed_images: bool
    session_snapshot: Any | None = None


class ProjectAutosaveManager:
    _MAIN_DISPATCH_TIMEOUT_SEC = 5.0

    def __init__(
        self,
        snapshot_callable: Callable[[], AutosaveSnapshot | None],
        write_callable: Callable[[AutosaveSnapshot, Path], None],
        autosave_dir: str | Path,
        max_slots: int = 3,
        debounce_sec: float = 2.5,
        name_tag_provider: Callable[[], str | None] | None = None,
        dispatch_to_main: Callable[[Callable[[], None]], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
    ):
        self.snapshot_callable = snapshot_callable
        self.write_callable = write_callable
        self.autosave_dir = Path(autosave_dir)
        self.autosave_dir.mkdir(parents=True, exist_ok=True)
        self.max_slots = max(1, int(max_slots))
        self.debounce_sec = max(0.1, float(debounce_sec))
        self.name_tag_provider = name_tag_provider
        self.dispatch_to_main = dispatch_to_main
        self.on_error = on_error
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._slot_counter = {}
        # Only the newest not-yet-written snapshot matters. A slow disk write
        # must not grow a queue of dense, obsolete project payloads.
        self._write_queue: queue.Queue[tuple[AutosaveSnapshot, Path] | None] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _sanitize_tag(self, raw: str | None) -> str:
        if raw is None:
            return "autosave"
        tag = str(raw).strip().lower()
        if not tag:
            return "autosave"
        tag = re.sub(r"[^a-z0-9._-]+", "_", tag)
        tag = tag.strip("._-")
        return tag or "autosave"

    def _active_tag(self) -> str:
        if self.name_tag_provider is None:
            return "autosave"
        try:
            return self._sanitize_tag(self.name_tag_provider())
        except Exception:
            return "autosave"

    def _slot_prefix(self, tag: str) -> str:
        return "autosave_" if tag == "autosave" else f"{tag}_autosave_"

    def _slot_filename(self, tag: str, idx: int) -> str:
        return f"{self._slot_prefix(tag)}{idx}{PROJECT_EXTENSION}"

    def _highest_existing_slot(self, tag: str) -> int:
        pattern = re.compile(rf"^{re.escape(self._slot_prefix(tag))}(\d+){re.escape(PROJECT_EXTENSION)}$")
        highest = 0
        for p in self.autosave_dir.glob(f"{self._slot_prefix(tag)}*{PROJECT_EXTENSION}"):
            match = pattern.match(p.name.lower())
            if match:
                highest = max(highest, int(match.group(1)))
        return highest

    def _next_slot_path(self) -> Path:
        tag = self._active_tag()
        with self._lock:
            if tag not in self._slot_counter:
                # Continue the round-robin from whatever slots already exist on
                # disk instead of restarting at 1, which would immediately
                # overwrite the newest recovery file from a prior session.
                self._slot_counter[tag] = self._highest_existing_slot(tag)
            current = int(self._slot_counter.get(tag, 0))
            next_idx = (current % self.max_slots) + 1
            self._slot_counter[tag] = next_idx
        return self.autosave_dir / self._slot_filename(tag, next_idx)

    def schedule(self, reason: str = "") -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_sec, self._run_once, args=(str(reason or ""),))
            self._timer.daemon = True
            self._timer.start()

    def _run_once(self, reason: str) -> None:
        if self._stop_event.is_set():
            return
        slot_path = self._next_slot_path()
        try:
            snapshot = self._get_snapshot_on_main()
        except Exception as exc:
            self._report_error(exc, f"snapshot:{reason}")
            return
        if snapshot is None:
            return
        item = (snapshot, slot_path)
        try:
            self._write_queue.put_nowait(item)
        except queue.Full:
            try:
                self._write_queue.get_nowait()
                self._write_queue.task_done()
            except queue.Empty:
                pass
            self._write_queue.put_nowait(item)

    def _get_snapshot_on_main(self) -> AutosaveSnapshot | None:
        if self.dispatch_to_main is None:
            return self.snapshot_callable()

        done = threading.Event()
        out: dict[str, Any] = {"snapshot": None, "error": None}

        def _runner() -> None:
            try:
                out["snapshot"] = self.snapshot_callable()
            except Exception as exc:  # pragma: no cover - covered via caller path
                out["error"] = exc
            finally:
                done.set()

        self.dispatch_to_main(_runner)
        if not done.wait(timeout=self._MAIN_DISPATCH_TIMEOUT_SEC):
            raise TimeoutError(
                f"Timed out after {self._MAIN_DISPATCH_TIMEOUT_SEC}s waiting for the main "
                "thread to produce an autosave snapshot."
            )
        if out["error"] is not None:
            raise out["error"]
        return out["snapshot"]

    def _worker_loop(self) -> None:
        while True:
            item = self._write_queue.get()
            if item is None:
                self._write_queue.task_done()
                break
            snapshot, slot_path = item
            try:
                self.write_callable(snapshot, slot_path)
            except Exception as exc:
                self._report_error(exc, f"write:{slot_path}")
            finally:
                self._write_queue.task_done()

    def _report_error(self, exc: Exception, context: str) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(exc, context)
        except Exception:
            # Never allow error reporters to crash app threads.
            pass

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._stop_event.set()
        try:
            self._write_queue.put_nowait(None)
        except queue.Full:
            try:
                self._write_queue.get_nowait()
                self._write_queue.task_done()
            except queue.Empty:
                pass
            self._write_queue.put_nowait(None)
        self._worker.join(timeout=2.0)

    def autosave_paths(self) -> list[Path]:
        tag = self._active_tag()
        return [self.autosave_dir / self._slot_filename(tag, i) for i in range(1, self.max_slots + 1)]

    def _all_autosave_candidates(self) -> list[Path]:
        ext = re.escape(PROJECT_EXTENSION)
        candidates = [p for p in self.autosave_dir.glob(f"*{PROJECT_EXTENSION}") if p.is_file()]
        out = []
        for p in candidates:
            name = p.name.lower()
            if re.fullmatch(rf"autosave_\d+{ext}", name) or re.fullmatch(rf".+_autosave_\d+{ext}", name):
                out.append(p)
        return out

    def newest_autosave(self) -> Optional[Path]:
        candidates = self._all_autosave_candidates()
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def newest_autosave_if_newer_than(self, project_path: str | Path | None) -> Optional[Path]:
        newest = self.newest_autosave()
        if newest is None:
            return None
        if project_path is None:
            return newest
        p = Path(project_path)
        if not p.exists():
            return newest
        if newest.stat().st_mtime > p.stat().st_mtime:
            return newest
        return None
