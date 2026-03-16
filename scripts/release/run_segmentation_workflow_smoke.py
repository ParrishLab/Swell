#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sdapp.analysis.model import DeterministicCpuFallbackPredictor


def main() -> int:
    frame_count = 10
    frame_shape = (64, 64)
    predictor = DeterministicCpuFallbackPredictor(frame_count=frame_count, frame_shape=frame_shape)
    inference_state = predictor.init_state(video_path=None)

    points = np.array([[32.0, 32.0], [22.0, 32.0], [42.0, 32.0]], dtype=np.float32)
    labels = np.array([1, 1, 0], dtype=np.int32)
    predictor.add_new_points_or_box(
        inference_state=inference_state,
        frame_idx=2,
        obj_id=1,
        points=points,
        labels=labels,
        clear_old_points=True,
    )

    masks = np.zeros((frame_count, frame_shape[0], frame_shape[1]), dtype=np.uint8)
    produced = 0
    for out_frame_idx, _obj_ids, out_mask_logits in predictor.propagate_in_video(
        inference_state,
        start_frame_idx=2,
        reverse=False,
    ):
        mask = (out_mask_logits[0] > 0.5).cpu().numpy().squeeze().astype(np.uint8)
        masks[int(out_frame_idx)] = mask
        if np.any(mask):
            produced += 1

    if produced <= 0:
        print("SEGMENTATION_WORKFLOW_SMOKE:FAIL:no_nonempty_masks")
        return 1

    with tempfile.TemporaryDirectory(prefix="sdapp_seg_smoke_") as tmp:
        output = Path(tmp) / "workflow_masks.npz"
        np.savez_compressed(output, masks=masks)
        if not output.exists():
            print("SEGMENTATION_WORKFLOW_SMOKE:FAIL:no_output")
            return 1

    print("SEGMENTATION_WORKFLOW_SMOKE:PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
