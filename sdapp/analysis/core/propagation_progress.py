from __future__ import annotations

"""Progress logging adapter for propagation operations."""

from dataclasses import dataclass
from typing import Callable


@dataclass
class PropagationProgressState:
    active: bool = False
    total_steps: int = 0
    done_steps: int = 0
    last_pct: int = -1
    bar_width: int = 30
    label: str = "Propagation"
    run_id: int = 0
    prop_start: int | None = None
    prop_end: int | None = None
    anchor: int | None = None
    phase: str | None = None
    direction: str | None = None
    phase_done: int = 0
    phase_total: int = 0
    forward_done: int = 0
    forward_total: int = 0
    backward_done: int = 0
    backward_total: int = 0


class PropagationProgressLogger:
    def __init__(
        self,
        *,
        write_progress: Callable[[str], None],
        log_info: Callable[[str, str], None],
        log_success: Callable[[str, str], None],
        log_warn: Callable[[str, str], None],
        log_error: Callable[[str, str], None],
        on_update: Callable[..., None] | None = None,
        bar_width: int = 30,
    ):
        self._write_progress = write_progress
        self._log_info = log_info
        self._log_success = log_success
        self._log_warn = log_warn
        self._log_error = log_error
        self._on_update = on_update
        self.state = PropagationProgressState(bar_width=max(1, int(bar_width)))

    def _emit_update(self, *, status: str) -> None:
        callback = self._on_update
        if not callable(callback):
            return
        callback(
            active=bool(self.state.active),
            done=int(self.state.done_steps),
            total=int(self.state.total_steps),
            label=str(self.state.label),
            status=str(status),
            run_id=int(self.state.run_id),
            prop_start=self.state.prop_start,
            prop_end=self.state.prop_end,
            anchor=self.state.anchor,
            phase=self.state.phase,
            direction=self.state.direction,
            phase_done=int(self.state.phase_done),
            phase_total=int(self.state.phase_total),
            forward_done=int(self.state.forward_done),
            forward_total=int(self.state.forward_total),
            backward_done=int(self.state.backward_done),
            backward_total=int(self.state.backward_total),
        )

    def render_progress_line(self, done: int, total: int) -> str:
        safe_done = max(0, int(done))
        safe_total = max(0, int(total))
        if safe_total <= 0:
            filled = self.state.bar_width
            pct = 100
        else:
            ratio = min(1.0, safe_done / safe_total)
            filled = int(round(ratio * self.state.bar_width))
            pct = int(ratio * 100)

        filled = max(0, min(self.state.bar_width, filled))
        bar = "#" * filled + "-" * (self.state.bar_width - filled)
        return f"[{bar}] {pct}% ({safe_done}/{safe_total})"

    def start(
        self,
        total_steps: int,
        label: str = "Propagation",
        *,
        prop_start: int | None = None,
        prop_end: int | None = None,
        anchor: int | None = None,
    ) -> int:
        self.state.run_id += 1
        run_id = self.state.run_id
        self.state.active = True
        self.state.label = str(label or "Propagation")
        self.state.total_steps = max(0, int(total_steps))
        self.state.done_steps = 0
        self.state.last_pct = 100 if self.state.total_steps <= 0 else 0
        self.state.prop_start = None if prop_start is None else int(prop_start)
        self.state.prop_end = None if prop_end is None else int(prop_end)
        self.state.anchor = None if anchor is None else int(anchor)
        self.state.phase = None
        self.state.direction = None
        self.state.phase_done = 0
        self.state.phase_total = 0
        self.state.forward_done = 0
        self.state.forward_total = 0
        self.state.backward_done = 0
        self.state.backward_total = 0
        line = self.render_progress_line(self.state.done_steps, self.state.total_steps)
        self._write_progress(f"[INFO][{self.state.label}] {line}")
        self._emit_update(status="started")
        return run_id

    def tick(
        self,
        increment: int = 1,
        run_id: int | None = None,
        *,
        phase: str | None = None,
        direction: str | None = None,
        phase_done: int | None = None,
        phase_total: int | None = None,
    ) -> None:
        if run_id is not None and run_id != self.state.run_id:
            return
        if not self.state.active:
            return

        if phase is not None:
            self.state.phase = str(phase)
        if direction is not None:
            self.state.direction = str(direction)
        if phase_total is not None:
            self.state.phase_total = max(0, int(phase_total))
        if phase_done is not None:
            self.state.phase_done = max(0, min(int(phase_done), self.state.phase_total if self.state.phase_total > 0 else int(phase_done)))
        if self.state.direction == "forward":
            self.state.forward_total = int(self.state.phase_total)
            self.state.forward_done = int(self.state.phase_done)
        elif self.state.direction == "backward":
            self.state.backward_total = int(self.state.phase_total)
            self.state.backward_done = int(self.state.phase_done)

        inc = max(0, int(increment))
        if self.state.total_steps > 0:
            self.state.done_steps = min(self.state.total_steps, self.state.done_steps + inc)
            pct = int((self.state.done_steps / self.state.total_steps) * 100)
        else:
            pct = 100

        if pct == self.state.last_pct:
            self._emit_update(status="progress")
            return

        self.state.last_pct = pct
        line = self.render_progress_line(self.state.done_steps, self.state.total_steps)
        self._write_progress(f"[INFO][{self.state.label}] {line}")
        self._emit_update(status="progress")

    def finish(self, status: str, run_id: int | None = None) -> None:
        if run_id is not None and run_id != self.state.run_id:
            return
        if not self.state.active:
            return

        if status == "complete":
            if self.state.total_steps > 0:
                self.state.done_steps = self.state.total_steps
            line = self.render_progress_line(self.state.done_steps, self.state.total_steps)
            self._write_progress(f"[INFO][{self.state.label}] {line}")

        status_messages = {
            "complete": "Propagation complete",
            "stopped": "Propagation stopped",
            "failed": "Propagation failed",
        }
        status_msg = status_messages.get(status, "Propagation finished")
        if status == "complete":
            self._log_success("Propagation", status_msg)
        elif status == "stopped":
            self._log_warn("Propagation", status_msg)
        elif status == "failed":
            self._log_error("Propagation", status_msg)
        else:
            self._log_info("Propagation", status_msg)
        self.state.active = False
        self._emit_update(status=str(status or "finished"))
