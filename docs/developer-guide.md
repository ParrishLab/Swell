# Developer Guide

This document outlines the internal architecture, design principles, and service patterns of Swell for developers and future maintainers.

---

## 1. Directory Layout & Dependency Boundaries

Swell is structured as a unified single-package Python codebase:

```text
swell/
├── main.py                     # App entry point
├── host/                       # Host window UI and controllers
│   ├── ui/                     # Tkinter Views
│   ├── controllers/            # User interaction logic
│   └── exporter.py             # Event metrics and image exporter
├── analysis/                   # Analysis window UI, core, and model predictor
│   ├── core/                   # State controllers and geometry metrics
│   ├── model/                  # SAM2 runtime and CPU fallback predictor
│   └── ui/                     # Canvas viewport and panels
├── shared/                     # Services and data models
│   ├── frame_source/           # Stack rendering adapters
│   ├── persistence/            # Project load and save store
│   └── services/               # Shared project/model controllers
└── resources/                  # App icons and model catalogs
tests/                          # Pytest suite
```

### Dependency Rules
To avoid circular imports and maintain modular boundaries, the following rules are strictly enforced:
* **`shared`** may **not** import from `host` or `analysis`.
* **`host`** and **`analysis`** may import from `shared`.
* Cross-window runtime communication must be handled through shared service interfaces and callback contracts, never by direct UI view manipulation.

---

## 2. Host vs. Analysis Workspace Handoff (Seam Contract)

The handoff and synchronization between the Host Window (parent) and the child Analysis Window are dictated by a versioned, transport-agnostic **Seam Contract (v1)**.

### Handoff Payload (Host → Analysis)
When opening an event, the host compiles a JSON handoff payload containing:
* `contract_version`: Must be `1`.
* `session`: Contains `session_id`, `project_path`, and `active_event_id`.
* `stack`: Identifies the `stack_id`, `frame_count`, `frame_shape` `[height, width]`, and `capabilities` (e.g., raw, subtracted, visual support).
* `event`: Contains `event_id`, `label`, and inclusive absolute coordinates (`start_idx` and `end_idx`).
* `analysis_state_ref`: An opaque reference pointer the analysis window uses to sync data back to the parent session.

### Sync Payload (Analysis → Host)
When the user clicks **Save Current Masks**, the analysis window compiles a sync payload and sends it back to the host:
* `contract_version`: Must be `1`.
* `session_id`, `stack_id`, `event_id`: IDs matching the handoff state.
* `analysis_state_ref`: The opaque reference pointer received during handoff.
* `analysis`: Contains the committed binary mask byte arrays (`masks_committed` encoded as `npz_uint8_3d`), draft masks (`masks_draft`), user prompts (`prompts` encoded as `portable_prompts_json`), and export directories.
* `ui_hints`: Playback playhead location (`last_frame`) and `active_tool`.

> [!IMPORTANT]
> **Conflict Policy**: The Host Window owns event identity and bounds. The Analysis Window never regenerates `event_id` or modifies event frame boundaries directly. If a sync payload's `stack_id` or `session_id` does not match the active host state, the sync is immediately rejected to prevent project corruption.

---

## 3. Shared Services

Swell relies on a series of singleton-like services located under `swell/shared/services/`:

* **`UnifiedProjectService`**: The in-memory source of truth for the active session. It handles event catalog operations, active event selections, and coordinates with the persistence layer to commit saves.
* **`CheckpointRuntimeService`**: Manages SAM-2 model resolution. It parses `resources/checkpoints_catalog.json` and automatically resolves weights using this priority order:
    1. Stored project-recorded model metadata.
    2. Managed app-data default directory.
    3. Explicit manual override paths.
    It also handles secure Hugging Face downloads, verifying file hashes using SHA-256 digests.
* **`SingleInstanceBridge`**: Restricts the application to a single instance. When a packaged app is launched by double-clicking a `.swell` file, the bridge detects if another instance is already running and sends an IPC file-open request to the active instance before exiting.
* **`torch_device` (`swell/shared/torch_device.py`)**: Resolves the torch execution device across both host analysis pipelines (model propagation and grid median trace calculations). Auto-detects in the order of Apple MPS → NVIDIA CUDA → CPU fallback, and supports forcing a specific device via the `SWELL_DEVICE` environment override.

---

## 4. Frame Sources & Preprocessing

To support fast rendering across different zoom levels, Swell uses a pipeline of frame sources implementing a shared protocol:

* **`StackReaderFrameSource`**: Wraps the raw `StackReader` to yield raw image arrays.
* **`PreparedFrameSource`**: Handles contrast normalization, channel reduction, and caches rendered canvases.
* **`DownsampledFrameSource`**: Computes approximate preview-only rendering stats at $0.25\times$ resolution, then converts baseline arrays and stabilization offsets back to full-resolution coordinates. Preview stats are not reused as canonical model input.
* **`EventScopedFrameSource`**: Scopes frame index queries to the bounds of a specific event.

---

## 5. Model Predictor & CPU Fallback

Segmentation is handled by the `SAM2Runtime` class.
* **GPU/MPS Acceleration**: PyTorch attempts to initialize CUDA (Windows) or MPS (macOS).
* **`CPUFallbackPredictor`**: If PyTorch imports fail, or if VRAM allocations hit Out-of-Memory (OOM) limits, the system initializes a deterministic CPU-based fallback. This ensures brush, eraser, and manual edit tools remain fully functional.

---

## 6. Export Pipeline

The exporter located in `swell/host/exporter.py` is designed for parallel processing:
* **Worker Pools**: Uses `ThreadPoolExecutor` (defaulting to 4 concurrent workers) to read image frames, render masks, apply overlay blending, and save PNG/TIFF frames.
* **`memoryview` Optimization**: Array serializations use Python `memoryview` bounds rather than copying memory with `tobytes()`, significantly reducing VRAM/RAM overhead when exporting long frame sequences.

---

## 7. Testing Strategy

Swell has a comprehensive test suite of 876 tests covering all architectural layers. Run tests locally using:

```bash
pytest
```

### Test Directory structure
* `tests/unit/`: Verifies isolated behaviors (e.g., version bump scripts, SHA-256 check-summing, path sanitizers, frame pipelines).
* `tests/host/`: Tests host project lifecycles, preview calculations, exporter outputs, and DC trace bindings.
* `tests/analysis/`: Tests tool interactions, viewport coordinate mapping, undo/redo state trackers, and region inclusion/exclusion logic.
* `tests/integration/`: Validates host-to-analysis handoff payload sync, round-trip reproducibility, and contract conformance.
* `tests/migration/`: Asserts schema upgrades and file-store migrations from legacy formats.

### CI Validation Gates (PR PRs)
Pull Requests run automated checks under `.github/workflows/release_phase2_pr.yml` across Linux, macOS, and Windows. Each runner validates:
1. Complete `pytest` test suite.
2. Startup smoke check (`python -m swell.main --smoke-test` returns `SMOKE_TEST:PASS`).
3. Model and workflow smoke checks (`run_model_smoke.py` and `run_segmentation_workflow_smoke.py`).
4. Packaged binary build success.
