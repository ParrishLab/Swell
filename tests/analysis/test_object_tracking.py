from __future__ import annotations

import json

import numpy as np

from swell.analysis.core.object_tracking import TrackingConfig, build_object_lineage


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
