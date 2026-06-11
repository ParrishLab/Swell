from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import cv2
import numpy as np


class _ArrayTensor:
    def __init__(self, array: np.ndarray) -> None:
        self._array = np.asarray(array, dtype=np.float32)

    def cpu(self) -> "_ArrayTensor":
        return self

    def numpy(self) -> np.ndarray:
        return np.asarray(self._array)

    def squeeze(self) -> np.ndarray:
        return np.asarray(self._array).squeeze()

    def __gt__(self, threshold: float) -> "_ArrayTensor":
        return _ArrayTensor((np.asarray(self._array) > float(threshold)).astype(np.float32))


@dataclass
class FallbackInferenceState:
    frame_count: int
    frame_shape: tuple[int, int]
    seeded_masks: dict[int, np.ndarray]


class DeterministicCpuFallbackPredictor:
    """Lightweight predictor that mimics SAM2 predictor APIs for CPU fallback mode."""

    def __init__(self, *, frame_count: int, frame_shape: tuple[int, int]) -> None:
        self.frame_count = int(max(1, frame_count))
        self.frame_shape = (int(frame_shape[0]), int(frame_shape[1]))

    def init_state(self, video_path: str | None = None) -> FallbackInferenceState:
        _ = video_path
        return FallbackInferenceState(
            frame_count=self.frame_count,
            frame_shape=self.frame_shape,
            seeded_masks={},
        )

    def reset_state(self, inference_state: FallbackInferenceState) -> None:
        if not isinstance(inference_state, FallbackInferenceState):
            return
        # Keep seeded masks; reset is a no-op for fallback determinism.
        return

    def add_new_mask(
        self,
        *,
        inference_state: FallbackInferenceState,
        frame_idx: int,
        obj_id: int,
        mask: np.ndarray,
    ) -> tuple[int, list[int], list[_ArrayTensor]]:
        idx = int(frame_idx)
        arr = np.asarray(mask, dtype=bool)
        if arr.shape != inference_state.frame_shape:
            arr = cv2.resize(arr.astype(np.uint8), (inference_state.frame_shape[1], inference_state.frame_shape[0])) > 0
        inference_state.seeded_masks[idx] = arr.astype(bool)
        logits = _ArrayTensor(arr.astype(np.float32))
        return idx, [int(obj_id)], [logits]

    def add_new_points_or_box(
        self,
        *,
        inference_state: FallbackInferenceState,
        frame_idx: int,
        obj_id: int,
        points: np.ndarray | None = None,
        labels: np.ndarray | None = None,
        box: np.ndarray | None = None,
        clear_old_points: bool = True,
    ) -> tuple[int, list[int], list[_ArrayTensor]]:
        _ = clear_old_points
        idx = int(frame_idx)
        h, w = inference_state.frame_shape
        mask = np.zeros((h, w), dtype=np.float32)
        if box is not None:
            x0, y0, x1, y1 = (float(v) for v in np.asarray(box, dtype=np.float32).reshape(-1)[:4])
            left = max(0, min(w - 1, int(round(min(x0, x1)))))
            right = max(0, min(w - 1, int(round(max(x0, x1)))))
            top = max(0, min(h - 1, int(round(min(y0, y1)))))
            bottom = max(0, min(h - 1, int(round(max(y0, y1)))))
            if right > left and bottom > top:
                mask[top : bottom + 1, left : right + 1] = 1.0
        pts = np.asarray(points if points is not None else [], dtype=np.float32).reshape(-1, 2)
        lbl = np.asarray(labels if labels is not None else [], dtype=np.int32).reshape(-1)
        radius = max(3, int(round(min(h, w) * 0.025)))
        for (x, y), lab in zip(pts, lbl):
            cx = int(round(float(x)))
            cy = int(round(float(y)))
            if lab > 0:
                cv2.circle(mask, (cx, cy), radius, 1.0, thickness=-1)
            else:
                cv2.circle(mask, (cx, cy), radius, 0.0, thickness=-1)
        # Smooth to approximate a model-logit map.
        mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=1.25, sigmaY=1.25)
        inference_state.seeded_masks[idx] = (mask > 0.5)
        logits = _ArrayTensor(mask[np.newaxis, ...])
        return idx, [int(obj_id)], [logits]

    def propagate_in_video(
        self,
        inference_state: FallbackInferenceState,
        *,
        start_frame_idx: int,
        reverse: bool,
    ) -> Iterable[tuple[int, list[int], list[_ArrayTensor]]]:
        indices = range(int(start_frame_idx), -1, -1) if reverse else range(int(start_frame_idx), inference_state.frame_count)
        last_mask = None
        for idx in indices:
            if idx in inference_state.seeded_masks:
                last_mask = np.asarray(inference_state.seeded_masks[idx], dtype=bool)
            if last_mask is None:
                continue
            logits = _ArrayTensor(last_mask.astype(np.float32)[np.newaxis, ...])
            yield int(idx), [1], [logits]
