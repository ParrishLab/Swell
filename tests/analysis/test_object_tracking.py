from __future__ import annotations

import json

import numpy as np
import pytest

from swell.analysis.core.object_tracking import PhysicalTrackingConfig, TrackingConfig, build_object_lineage


@pytest.mark.parametrize(
    ("scale_px_per_mm", "expected_area_px", "expected_centroid_px", "expected_boundary_px"),
    [
        (130.0, 5, 13.0, 6.5),
        (396.0, 40, 39.6, 19.8),
    ],
)
def test_physical_tracking_config_converts_to_pixel_thresholds(
    scale_px_per_mm: float,
    expected_area_px: int,
    expected_centroid_px: float,
    expected_boundary_px: float,
) -> None:
    config = PhysicalTrackingConfig().to_pixel_config(scale_px_per_mm)

    assert config.min_component_area_px == expected_area_px
    assert config.min_persistence_frames == 2
    assert config.max_centroid_distance_px == pytest.approx(expected_centroid_px)
    assert config.max_boundary_distance_px == pytest.approx(expected_boundary_px)


@pytest.mark.parametrize("scale_px_per_mm", [130.0, 396.0])
def test_physical_component_area_filter_is_resolution_invariant(scale_px_per_mm: float) -> None:
    config = PhysicalTrackingConfig().to_pixel_config(scale_px_per_mm)
    threshold = config.min_component_area_px
    below_height, below_width = ((2, 2) if threshold == 5 else (3, 13))
    kept_height, kept_width = ((1, 5) if threshold == 5 else (4, 10))
    mask = np.zeros((24, 32), dtype=bool)
    mask[1 : 1 + below_height, 1 : 1 + below_width] = True
    mask[12 : 12 + kept_height, 12 : 12 + kept_width] = True

    result = build_object_lineage([0], [mask], config=config)

    assert result["summary"]["raw_track_count"] == 2
    assert result["summary"]["kept_track_count"] == 1
    assert result["summary"]["noise_filtered_track_count"] == 1


def test_object_tracker_filters_small_one_frame_noise() -> None:
    frame_indices = [10, 11, 12]
    masks: list[np.ndarray] = []
    for frame_idx in frame_indices:
        mask = np.zeros((12, 12), dtype=bool)
        if frame_idx in {10, 11, 12}:
            mask[2:5, 2:5] = True
        if frame_idx == 11:
            mask[9, 9] = True
        masks.append(mask)

    result = build_object_lineage(
        frame_indices,
        masks,
        config=TrackingConfig(min_component_area_px=4, min_persistence_frames=2),
    )

    summary = dict(result["summary"])
    assert int(summary["kept_track_count"]) == 1
    assert int(summary["noise_filtered_track_count"]) == 1
    lineage_rows = list(result["lineage_rows"])
    assert len(lineage_rows) == 1
    assert lineage_rows[0]["birth_frame"] == 10
    assert lineage_rows[0]["end_frame"] == 12


def test_object_tracker_preserves_lineage_when_objects_merge() -> None:
    frame_indices = [20, 21, 22]
    masks: list[np.ndarray] = []
    mask_a = np.zeros((14, 14), dtype=bool)
    mask_a[2:5, 2:5] = True
    mask_a[8:11, 8:11] = True
    masks.append(mask_a)

    mask_b = np.zeros((14, 14), dtype=bool)
    mask_b[2:6, 2:6] = True
    mask_b[7:11, 7:11] = True
    masks.append(mask_b)

    mask_c = np.zeros((14, 14), dtype=bool)
    mask_c[2:11, 2:11] = True
    masks.append(mask_c)

    result = build_object_lineage(
        frame_indices,
        masks,
        config=TrackingConfig(min_component_area_px=4, min_persistence_frames=2),
    )

    summary = dict(result["summary"])
    assert int(summary["merge_event_count"]) == 1
    lineage_rows = sorted(list(result["lineage_rows"]), key=lambda row: int(row["track_id"]))
    assert len(lineage_rows) == 3
    merged_rows = [row for row in lineage_rows if row["terminal_status"] == "merged"]
    child_rows = [row for row in lineage_rows if row["parent_track_ids"] != "[]"]
    assert len(merged_rows) == 2
    assert len(child_rows) == 1
    child = child_rows[0]
    assert child["merge_frame"] == ""
    assert child["birth_frame"] == 22
    assert child["parent_track_ids"] != "[]"
    parent_ids = set(int(value) for value in json.loads(child["parent_track_ids"]))
    assert len(parent_ids) == 2
    for row in merged_rows:
        assert int(row["merge_frame"]) == 22
        assert int(row["end_frame"]) == 21
        assert int(row["merged_into_track_id"]) == int(child["track_id"])
        assert int(row["root_track_id"]) == int(child["root_track_id"])
