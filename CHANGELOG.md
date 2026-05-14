# Changelog

All notable changes to this project are documented in this file.

## [0.1.7] - 2026-05-14

### Auto-detect and ROI improvements
- Overhauled the auto-detect window with a dual-pane overview/detail timeline, interactive ROI selection, grid opacity control, and per-cell border rendering for clearer event visualization.
- Added incremental algorithm rerun scheduling so parameter changes (scale, opacity, ROI) trigger a debounced re-evaluation without blocking the UI.
- Active-cell overlay and cell-border rendering are now cached by pipeline generation, avoiding redundant recomputation across frame scrubs.
- Exporter now selects ROI-scoped speed metrics when an ROI is defined, falling back to full-frame metrics otherwise.

### Performance
- Added `DownsampledFrameSource` (`sdapp/shared/frame_source/downsampled.py`) and `compute_visualization_stats_for_preview` to compute visualization stats at 0.25× resolution during the analysis-launch preview, then upsample the baseline back to full resolution — significantly reducing preview wait time on large stacks.
- Added `sdapp/shared/diagnostics/` with `OpenPerfTrace`: a lightweight wall-clock stage/mark tracer for the analysis-window open path. Traces are dumped to the app log on completion and silently discarded on failure.
- Analysis launch flow now wraps the full open sequence in a perf trace, attributing time to import, preview preparation, frame rendering, and options-dialog interactions.

### Model/checkpoint compatibility
- No checkpoint format or project schema bump in this release; existing managed and local SAM2 model selections remain compatible.

### .sdproj/migration notes
- No `.sdproj` schema version bump is required; existing projects remain loadable.
- `_save_project_after_metrics_apply` now persists project state immediately after metrics are applied from the host window, reducing the chance of unsaved metric changes.

### Known segmentation caveats/regressions
- No new release-blocking segmentation regressions are known from the automated suite (708 tests pass).
- SAM2 post-processing/native extension availability may still vary by environment.
- Auto-update behavior still depends on platform packaging/signing state; validate against final signed release artifacts.

## [0.1.6] - 2026-04-02

### UI overhaul
- Reworked the host and analysis interfaces around a shared visual system with improved layout hierarchy, clearer surfaces, and more consistent button/dialog styling.
- Updated the main review flows, preview surfaces, and popup tooling to feel more coherent during event review, export, and analysis handoff.
- Improved the scale and ROI calibration dialogs so calibration state is preserved more reliably and the interaction model is easier to follow.

### Model/checkpoint compatibility
- No checkpoint format or project schema bump is introduced in this release; existing managed and local SAM2 model selections remain compatible.
- Refactored host and analysis model/runtime flows around a shared managed-model workflow, including background download/selection handling for packaged and development runs.
- Added `h5py`, continued packaging of Sparkle/WinSparkle updater runtimes, and hardened PyInstaller metadata so packaged builds resolve runtime assets more reliably.

### Platform/backend limitations
- Added DC trace import/filtering improvements and corrected WaveSurfer scaling so imported traces align more consistently with event review workflows.
- Refined the host and analysis UI around shared runtime controllers, centered dialogs, improved preview handling, and a higher-fidelity visual hierarchy for core review/calibration screens.
- Export flows now produce richer operator-facing artifacts, including markdown summaries alongside JSON/CSV outputs and a combined spreadsheet export path.

### .sdproj/migration notes
- No `.sdproj` schema version bump is required for this release; existing projects remain loadable.
- Project metadata now preserves more session context, including DC trace attachment references and autosaved metric/default updates.
- Event labels now flow into derived project/export naming, so newly generated folders and summaries may use human-readable event labels instead of raw event IDs.

### Known segmentation caveats/regressions
- No new release-blocking segmentation regressions are currently known from the automated suite.
- SAM2 post-processing/native extension availability may still vary by environment; segmentation remains usable, but optional optimized paths can still be unavailable.
- Auto-update behavior still depends on platform packaging/signing state and bundled updater assets, so update reliability should be validated against the final signed release artifacts.

## [0.1.5] - 2026-03-30

### Model/checkpoint compatibility
- TBD

### Platform/backend limitations
- TBD

### .sdproj/migration notes
- TBD

### Known segmentation caveats/regressions
- TBD

## [0.1.4] - 2026-03-26

### Model/checkpoint compatibility
- TBD

### Platform/backend limitations
- TBD

### .sdproj/migration notes
- TBD

### Known segmentation caveats/regressions
- TBD

## [0.1.3] - 2026-03-17

### Model/checkpoint compatibility
- No checkpoint format changes in this release; existing SAM2-managed checkpoint selection remains compatible.
- Windows packaged/runtime validation continues to use CPU Torch install fallback in CI when the CPU wheel index is unavailable.

### Platform/backend limitations
- Fixed Windows host-stack shape normalization for color-backed TIFF inputs so host metrics validation, analysis handoff, and mask sync no longer misinterpret frames as `width x channels`.
- Fixed Windows analysis UI behavior where propagation range spinboxes could ignore programmatic writes while disabled.
- macOS signing, notarization, and stapling are still not part of the release workflow.

### .sdproj/migration notes
- No `.sdproj` schema version bump in this release.
- Existing projects remain loadable, but Windows-authored saves now preserve generated masks and mask dimensions correctly when analysis is opened from the host window.

### Known segmentation caveats/regressions
- SAM2 post-processing may still log an optional extension warning at runtime when native `_C` bindings are unavailable; segmentation remains usable, but some post-processing is limited.
- Packaged desktop builds do not have an auto-update mechanism yet; application updates are still distributed as manual install/package refreshes.
- Axis-locked scale capture now defaults on in the shared scale dialog, which changes the initial interaction behavior for manual scale selection.

## [0.1.2] - 2026-03-16

### Model/checkpoint compatibility
- TBD

### Platform/backend limitations
- TBD

### .sdproj/migration notes
- TBD

### Known segmentation caveats/regressions
- TBD

## [0.1.1] - 2026-03-16

### Model/checkpoint compatibility
- Added generated release compatibility manifest (`compatibility.json`) and checksum metadata contract for published assets.
- Kept SAM2 policy declaration in packaging metadata (no bundled checkpoint weights in release assets).

### Platform/backend limitations
- Released source artifacts plus macOS arm64/x86_64 desktop archives.
- Windows is validated as a runtime/test gate only in CI for this phase; packaged Windows binary is deferred.

### .sdproj/migration notes
- No `.sdproj` schema changes in release packaging phases 1-4.
- Canonical single-stack project structure remains unchanged.

### Known segmentation caveats/regressions
- Missing SAM2/model dependencies continues to disable model-based segmentation tools at runtime.
- macOS signing/notarization/stapling is not yet part of this phase and remains deferred.
