"""Lightweight perf tracer for the analysis-window open path.

Used to attribute wall-clock time to discrete stages between the user
clicking "Open Analysis" and the window becoming interactive. One trace
per open attempt; emit a single consolidated log block on dump().
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from typing import Any, Callable, ContextManager, Iterator


@dataclass
class _Stage:
    name: str
    start: float
    end: float | None
    thread: str
    note: str | None = None


@dataclass
class _Mark:
    name: str
    at: float
    thread: str


class OpenPerfTrace:
    """Records ordered stages + instant marks for one open attempt."""

    def __init__(self, label: str = "analysis_window") -> None:
        self.label = str(label)
        self._t0 = time.perf_counter()
        self._stages: list[_Stage] = []
        self._marks: list[_Mark] = []
        self._lock = threading.Lock()
        self._dumped = False
        self.torch_was_loaded_at_start = "torch" in sys.modules

    @contextmanager
    def stage(self, name: str, *, note: str | None = None) -> Iterator[_Stage]:
        rec = _Stage(
            name=str(name),
            start=time.perf_counter(),
            end=None,
            thread=threading.current_thread().name,
            note=note,
        )
        with self._lock:
            self._stages.append(rec)
        try:
            yield rec
        finally:
            rec.end = time.perf_counter()

    def mark(self, name: str, *, note: str | None = None) -> None:
        rec = _Mark(name=str(name), at=time.perf_counter(), thread=threading.current_thread().name)
        with self._lock:
            self._marks.append(rec)
        if note:
            # store as a zero-duration stage so dump shows the note
            self._stages.append(
                _Stage(name=f"{name} ({note})", start=rec.at, end=rec.at, thread=rec.thread)
            )

    def annotate(self, **kwargs: Any) -> None:
        # attach arbitrary key/value notes that will be printed in the dump header
        if not hasattr(self, "_meta"):
            self._meta: dict[str, Any] = {}
        self._meta.update({str(k): v for k, v in kwargs.items()})

    def dump(self, log_fn: Callable[[str, str], None] | Callable[[str], None]) -> None:
        """Emit one consolidated log block. Idempotent."""
        with self._lock:
            if self._dumped:
                return
            self._dumped = True
            stages = list(self._stages)
            marks = list(self._marks)
            meta = dict(getattr(self, "_meta", {}))

        total_ms = (time.perf_counter() - self._t0) * 1000.0
        lines: list[str] = []
        header_bits = [f"label={self.label}", f"total={total_ms:.1f}ms"]
        header_bits.append(f"torch_preloaded={self.torch_was_loaded_at_start}")
        for k, v in meta.items():
            header_bits.append(f"{k}={v}")
        lines.append("Perf/Open " + " | ".join(header_bits))

        events: list[tuple[float, str]] = []
        for st in stages:
            dur_ms = ((st.end or st.start) - st.start) * 1000.0
            offset_ms = (st.start - self._t0) * 1000.0
            suffix = f" note={st.note}" if st.note else ""
            events.append(
                (
                    st.start,
                    f"  +{offset_ms:7.1f}ms  stage  {st.name:<40} {dur_ms:8.1f}ms  thread={st.thread}{suffix}",
                )
            )
        for mk in marks:
            offset_ms = (mk.at - self._t0) * 1000.0
            events.append(
                (
                    mk.at,
                    f"  +{offset_ms:7.1f}ms  mark   {mk.name:<40} {'-':>8}    thread={mk.thread}",
                )
            )
        events.sort(key=lambda e: e[0])
        lines.extend(line for _, line in events)

        msg = "\n".join(lines)
        # Adapt to either single-arg or (tag, msg) loggers.
        try:
            log_fn("Perf/Open", msg)  # type: ignore[arg-type]
        except TypeError:
            log_fn(msg)  # type: ignore[misc]
        except Exception:
            # last-ditch: print
            print(msg)


_active_lock = threading.Lock()
_active_trace: OpenPerfTrace | None = None


def set_active(trace: OpenPerfTrace | None) -> None:
    global _active_trace
    with _active_lock:
        _active_trace = trace


def get_active() -> OpenPerfTrace | None:
    with _active_lock:
        return _active_trace


def stage(name: str, *, note: str | None = None) -> ContextManager[Any]:
    """Convenience wrapper: opens a stage on the active trace, or a no-op."""
    trace = get_active()
    if trace is None:
        return nullcontext()
    return trace.stage(name, note=note)


def mark(name: str, *, note: str | None = None) -> None:
    trace = get_active()
    if trace is None:
        return
    trace.mark(name, note=note)
