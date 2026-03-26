from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

APP_TITLE = "IOS SD Event Marker"
SUPPORTED_EXTENSIONS = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")
DEFAULT_BASELINE_PRE_FRAMES = 30
MAX_PREVIEW_CACHE = 16


@dataclass(frozen=True)
class FrameRef:
    frame_idx: int
    source_path: Path
    page_index: Optional[int]
    source_ext: str
    frame_name: str


@dataclass(frozen=True)
class StackInfo:
    input_dir: Path
    frame_count: int
    frame_height: int
    frame_width: int
    dtype: str


@dataclass
class EventCandidate:
    event_id: str
    start_idx: int
    end_idx: int
    duration_frames: int
    duration_sec: Optional[float] = None
    flags: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceResult:
    frame_indices: list[int] = field(default_factory=list)
    time_sec: list[Optional[float]] = field(default_factory=list)
    mean: list[float] = field(default_factory=list)
    median: list[float] = field(default_factory=list)
    std: list[float] = field(default_factory=list)


@dataclass
class ExportRecord:
    event_id: str
    role: str
    frame_idx: int
    frame_name: str
    source_path: str
    output_path: str
    timestamp_sec: Optional[float]
