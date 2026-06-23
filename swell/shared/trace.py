from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np


@dataclass(frozen=True)
class TraceRecord:
    source_type: str
    channel_names: list[str]
    units: list[str]
    sample_rate_hz: float | None
    timestamps_s: np.ndarray | None
    signals: np.ndarray
    segments: list[tuple[int, int]] = field(default_factory=list)
    start_time_s: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TimeAlignment:
    mode: Literal["manual_offset"] = "manual_offset"
    video_t0_s: float = 0.0
    trace_t0_s: float = 0.0
    offset_s: float = 0.0
    drift_ppm: float | None = None
    notes: str = ""


@dataclass(frozen=True)
class TraceAttachment:
    source_type: str
    source_path: str
    channel_index: int
    channel_name: str
    sample_rate_hz: float | None
    unit: str
    alignment: TimeAlignment = field(default_factory=TimeAlignment)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "source_type": str(self.source_type),
            "source_path": str(Path(self.source_path).expanduser()),
            "channel_index": int(self.channel_index),
            "channel_name": str(self.channel_name),
            "sample_rate_hz": None if self.sample_rate_hz is None else float(self.sample_rate_hz),
            "unit": str(self.unit),
            "alignment": {
                "mode": str(self.alignment.mode),
                "video_t0_s": float(self.alignment.video_t0_s),
                "trace_t0_s": float(self.alignment.trace_t0_s),
                "offset_s": float(self.alignment.offset_s),
                "drift_ppm": None if self.alignment.drift_ppm is None else float(self.alignment.drift_ppm),
                "notes": str(self.alignment.notes),
            },
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_metadata_dict(cls, payload: dict[str, Any] | None) -> TraceAttachment | None:
        if not isinstance(payload, dict):
            return None
        raw_alignment = dict(payload.get("alignment") or {})
        try:
            alignment = TimeAlignment(
                mode="manual_offset",
                video_t0_s=float(raw_alignment.get("video_t0_s", 0.0) or 0.0),
                trace_t0_s=float(raw_alignment.get("trace_t0_s", 0.0) or 0.0),
                offset_s=float(raw_alignment.get("offset_s", 0.0) or 0.0),
                drift_ppm=(
                    None
                    if raw_alignment.get("drift_ppm") is None
                    else float(raw_alignment.get("drift_ppm"))
                ),
                notes=str(raw_alignment.get("notes", "") or ""),
            )
            return cls(
                source_type=str(payload.get("source_type", "") or ""),
                source_path=str(payload.get("source_path", "") or ""),
                channel_index=int(payload.get("channel_index", 0)),
                channel_name=str(payload.get("channel_name", "") or ""),
                sample_rate_hz=(
                    None if payload.get("sample_rate_hz") is None else float(payload.get("sample_rate_hz"))
                ),
                unit=str(payload.get("unit", "") or ""),
                alignment=alignment,
                metadata=dict(payload.get("metadata") or {}),
            )
        except (TypeError, ValueError):
            return None


class TraceAdapter(Protocol):
    def sniff(self, path: Path) -> bool: ...

    def load_metadata(self, path: Path) -> dict[str, Any]: ...

    def load_trace(self, path: Path, channel_selection: int | None = None) -> TraceRecord: ...

