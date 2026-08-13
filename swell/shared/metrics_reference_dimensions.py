from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


ReferenceDimensionAction = Literal["accept", "confirm", "reject"]


@dataclass(frozen=True)
class ReferenceDimensionDecision:
    action: ReferenceDimensionAction
    message: str = ""


def assess_metrics_reference_dimensions(
    *,
    purpose: str,
    expected_shape: Sequence[int] | None,
    actual_shape: Sequence[int] | None,
) -> ReferenceDimensionDecision:
    """Choose the safe UI policy for a metrics reference image.

    Shapes use NumPy's ``(height, width)`` order. A scale measurement may come
    from a larger, uncropped acquisition because it does not share ROI
    coordinates with the active stack. ROI references must remain in the
    stack's coordinate space.
    """

    expected = _shape_hw(expected_shape)
    actual = _shape_hw(actual_shape)
    if expected is None or actual is None or expected == actual:
        return ReferenceDimensionDecision("accept")

    expected_h, expected_w = expected
    actual_h, actual_w = actual
    dimensions = (
        f"Loaded stack: {expected_w}x{expected_h}\n"
        f"Selected image: {actual_w}x{actual_h}"
    )
    if str(purpose or "").strip().lower() == "scale":
        return ReferenceDimensionDecision(
            "confirm",
            (
                "The selected scale reference has different pixel dimensions "
                "from the loaded stack.\n\n"
                f"{dimensions}\n\n"
                "This can be correct when the reference comes from the same "
                "acquisition and the stack was only cropped or split without "
                "resizing. If the reference was resized, resampled, or acquired "
                "at a different pixel resolution, the pixels/mm calibration may "
                "be incorrect.\n\n"
                "Continue with this scale reference?"
            ),
        )

    return ReferenceDimensionDecision(
        "reject",
        (
            "Selected ROI image dimensions do not match the loaded stack.\n\n"
            f"{dimensions}\n\n"
            "ROI coordinates must use the same pixel dimensions as the stack."
        ),
    )


def _shape_hw(shape: Sequence[int] | None) -> tuple[int, int] | None:
    if shape is None:
        return None
    try:
        height = int(shape[0])
        width = int(shape[1])
    except (IndexError, TypeError, ValueError):
        return None
    if height <= 0 or width <= 0:
        return None
    return height, width
