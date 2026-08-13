from swell.shared.metrics_reference_dimensions import assess_metrics_reference_dimensions


def test_matching_reference_dimensions_are_accepted() -> None:
    decision = assess_metrics_reference_dimensions(
        purpose="ROI",
        expected_shape=(8, 9),
        actual_shape=(8, 9),
    )

    assert decision.action == "accept"
    assert decision.message == ""


def test_mismatched_scale_dimensions_require_confirmation() -> None:
    decision = assess_metrics_reference_dimensions(
        purpose="Scale",
        expected_shape=(8, 9),
        actual_shape=(8, 18),
    )

    assert decision.action == "confirm"
    assert "Loaded stack: 9x8" in decision.message
    assert "Selected image: 18x8" in decision.message
    assert "cropped or split" in decision.message
    assert "resized, resampled" in decision.message


def test_mismatched_roi_dimensions_are_rejected() -> None:
    decision = assess_metrics_reference_dimensions(
        purpose="ROI",
        expected_shape=(8, 9),
        actual_shape=(8, 18),
    )

    assert decision.action == "reject"
    assert "ROI coordinates" in decision.message
