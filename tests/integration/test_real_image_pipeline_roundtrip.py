from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

from swell.analysis.core.project_schema import default_project_state
from swell.analysis.core.project_store import ProjectStore
from swell.analysis.model.cpu_fallback_predictor import DeterministicCpuFallbackPredictor
from swell.host.config import EventCandidate
from swell.host.exporter import export_analysis
from swell.host.stack_reader import StackReader
from swell.shared.frame_source import PreparedFrameSource, StackReaderFrameSource


def _event(frame_count: int) -> EventCandidate:
    return EventCandidate(
        event_id="event_001",
        start_idx=0,
        end_idx=frame_count - 1,
        duration_frames=frame_count,
        duration_sec=None,
        flags={},
        label="event_001",
    )


def test_real_files_flow_through_host_preprocessing_segmentation_persistence_and_export(tmp_path: Path) -> None:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    height, width = 32, 40
    frame0 = np.zeros((height, width), dtype=np.uint8)
    frame1 = np.zeros((height, width), dtype=np.uint16)
    frame2 = np.zeros((height, width, 3), dtype=np.uint8)
    frame0[8:18, 10:22] = 100
    frame1[8:18, 10:22] = 25_000
    frame2[8:18, 10:22, :] = (30, 120, 220)
    Image.fromarray(frame0).save(images_dir / "frame_000.png")
    tifffile.imwrite(images_dir / "frame_001.tif", frame1, compression="deflate")
    Image.fromarray(frame2).save(images_dir / "frame_002.png")

    reader = StackReader(channel_mode_resolver=lambda: "average")
    info = reader.open_stack(images_dir)
    prepared = PreparedFrameSource(
        StackReaderFrameSource(reader),
        baseline_frames=1,
        apply_smoothing=False,
    )
    visual_frames = np.stack([prepared.get_visual_frame(i) for i in range(info.frame_count)])

    assert visual_frames.shape == (3, height, width)
    assert visual_frames.dtype == np.uint8
    assert np.all(np.isfinite(visual_frames))

    predictor = DeterministicCpuFallbackPredictor(
        frame_count=info.frame_count,
        frame_shape=(height, width),
    )
    inference_state = predictor.init_state()
    seed = np.zeros((height, width), dtype=bool)
    seed[8:18, 10:22] = True
    predictor.add_new_mask(
        inference_state=inference_state,
        frame_idx=0,
        obj_id=1,
        mask=seed,
    )
    propagated = list(predictor.propagate_in_video(inference_state, start_frame_idx=0, reverse=False))
    masks = np.stack([np.asarray(item[2][0].cpu().numpy()).squeeze() > 0.5 for item in propagated])

    project_state = default_project_state("integration-test")
    project_state["events"] = [
        {
            "id": "event_001",
            "masks_ref": "events/event_001/masks.npz",
            "prompts_ref": "events/event_001/prompts.json",
        }
    ]
    project_path = tmp_path / "pipeline.swell"
    store = ProjectStore()
    store.save(
        project_path,
        project_state=project_state,
        images_manifest={"images": [str(reader.get_frame_ref(i).source_path) for i in range(info.frame_count)]},
        roi_data={"roi_points": []},
        event_payloads={"event_001": {"masks": masks, "prompts": {"frames": {}}}},
        embed_images=False,
    )
    loaded = store.load(project_path)
    loaded_masks = loaded.event_payloads["event_001"]["masks"]

    np.testing.assert_array_equal(loaded_masks, masks)

    export_dir = tmp_path / "export"
    export_analysis(
        reader=reader,
        events=[_event(info.frame_count)],
        output_dir=str(export_dir),
        baseline_pre_frames=0,
        trace=None,
        selected_event_ids=["event_001"],
        analysis_sidecar={
            "event_001": {
                "masks_committed": loaded_masks,
                "metrics_settings": {
                    "scale_px_per_mm": 10.0,
                    "scale_unit": "px_per_mm",
                    "frames_per_sec": 2.0,
                    "roi_mask": np.ones((height, width), dtype=bool),
                },
            }
        },
        include_metric_area_recruited=True,
        include_metric_propagation_speed=False,
    )
    csv_path = export_dir / "event_001" / "metrics" / "area_recruited_event_001.csv"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == info.frame_count
    assert all(float(row["area_mm2"]) > 0 for row in rows)
