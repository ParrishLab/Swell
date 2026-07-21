from __future__ import annotations

import cv2
import numpy as np

MASK_OVERLAY_COLOR_RGB = (0, 255, 255)
MASK_OVERLAY_ALPHA = 0.3

# Masks generated at a threshold that no longer matches the current one are
# drawn amber and hatched. Hatching reads as "provisional" where a plain hue
# change would read as "different object", and amber stays distinguishable
# from cyan under the common forms of colour vision deficiency.
MASK_OVERLAY_STALE_COLOR_RGB = (245, 196, 81)
_HATCH_PERIOD = 8
_HATCH_WIDTH = 4


def normalize_image_u8(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image)
    if arr.dtype == np.uint8:
        return arr.copy()
    if arr.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    work = np.asarray(arr, dtype=np.float32)
    finite_mask = np.isfinite(work)
    if not np.any(finite_mask):
        return np.zeros(arr.shape, dtype=np.uint8)
    finite_values = work[finite_mask]
    lo = float(np.min(finite_values))
    hi = float(np.max(finite_values))
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    work = np.where(finite_mask, work, lo)
    return cv2.normalize(work, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def frame_to_rgb_u8(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame)
    if arr.ndim == 2:
        return cv2.cvtColor(normalize_image_u8(arr), cv2.COLOR_GRAY2RGB)
    if arr.ndim == 3 and arr.shape[2] == 1:
        return cv2.cvtColor(normalize_image_u8(arr[:, :, 0]), cv2.COLOR_GRAY2RGB)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        rgb = normalize_image_u8(arr[:, :, :3])
        if rgb.ndim == 2:
            return cv2.cvtColor(rgb, cv2.COLOR_GRAY2RGB)
        return rgb
    squeezed = np.squeeze(arr)
    if squeezed.ndim == 2:
        return cv2.cvtColor(normalize_image_u8(squeezed), cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(normalize_image_u8(arr.reshape(arr.shape[0], -1)), cv2.COLOR_GRAY2RGB)


def apply_mask_overlay(
    frame: np.ndarray,
    mask: np.ndarray,
    *,
    alpha: float = MASK_OVERLAY_ALPHA,
    color: tuple[int, int, int] | None = None,
    hatch: bool = False,
) -> np.ndarray:
    rgb = frame_to_rgb_u8(frame)
    mask_bool = np.asarray(mask, dtype=bool)
    if mask_bool.ndim != 2 or not np.any(mask_bool):
        return rgb
    if hatch:
        height, width = mask_bool.shape
        rows, cols = np.ogrid[:height, :width]
        # Opacity is deliberately not reduced for the provisional state: it
        # would blur the boundary, which is the thing being judged.
        mask_bool = mask_bool & (((rows + cols) % _HATCH_PERIOD) < _HATCH_WIDTH)
        if not np.any(mask_bool):
            return rgb
    overlay = rgb.copy()
    overlay[mask_bool] = color if color is not None else MASK_OVERLAY_COLOR_RGB
    return cv2.addWeighted(rgb, float(1.0 - alpha), overlay, float(alpha), 0.0)
