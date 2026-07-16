# Changelog

All notable changes to this project are documented in this file.

## [0.3.0] - 2026-07-16

### Renamed to Swell
- The application, Python package, and desktop bundles are now named Swell. The import root is `swell` (previously `sdapp`), and the macOS bundle is `Swell.app` with identifier `com.swell.desktop`.
- Settings from an existing SDApp installation are copied into the Swell configuration directory on first packaged launch.
- SAM2 checkpoints downloaded by SDApp are migrated to the Swell model directory instead of being downloaded again.
- Legacy `.sdproj` projects continue to open, and the `sdapp` command-line alias and `SDAPP_DEVICE` environment variable are retained for existing launch scripts.

### Region drafting
- Region draft vertices can now be dragged after placement, and the selected handle stays highlighted after the mouse is released.
- Added an **Undo Point** button that steps back the last placed vertex without discarding the draft.
- Double-clicking the first vertex closes an open region draft, matching ROI behavior. Enter closes an open draft; Enter again commits a closed one.

### Export
- Added optional ROI-cropped binary mask export (`binary_masks_roi_cropped/`), written alongside a `roi_crop_metadata.json` recording the full-frame shape and crop bounds.

### Documentation
- Published a documentation site with a ten-part user guide, a glossary, and interactive demos covering prompting, mask editing, regions, and propagation.

### Project
- Swell is now released under the BSD 3-Clause license, with `CITATION.cff` and `codemeta.json` for citation metadata.

### Removed
- Automatic update checking has been removed. Swell no longer bundles the Sparkle/WinSparkle updater and the **Check for Updates** menu item is gone. New versions are downloaded manually from the GitHub releases page.

### Fixes
- Frame slider jump markers now track the slider thumb across the full width instead of drifting away from it toward the ends.
- Git metadata lookups no longer fork the running application process, which could emit allocator warnings once Torch, Tk, and SAM2 had started threads.

### Model/checkpoint compatibility
- No checkpoint format or model selection change in this release; existing managed and local SAM2 model selections remain compatible.
- Checkpoints downloaded by SDApp 0.2.0 and earlier are migrated automatically and do not need to be re-downloaded.

### Platform/backend limitations
- Because the bundle was renamed from `SDApp.app` to `Swell.app` (identifier `com.sdapp.desktop` to `com.swell.desktop`), Swell 0.3.0 installs alongside an existing SDApp installation rather than replacing it. Remove the old bundle manually once settings and checkpoints have migrated.
- SDApp 0.2.0 installs with automatic update checking enabled will not discover this release; 0.3.0 publishes no updater appcast. Upgrading from 0.2.0 is a manual download.

### .swell/migration notes
- No schema change in this release. `.swell` writers still emit schema 3, and schema 2 projects remain loadable.
- Legacy `.sdproj` files continue to open via the retained `com.sdapp.project` type association.

### Known segmentation caveats/regressions
- No known segmentation regressions in this release.

## [0.2.0] - 2026-06-12

### Auto-detect and ROI improvements
- Auto-detect now defaults to positive-going SD signals in the workbench, reset state, committed event metadata, and detector preset. Negative-going and both-polarity detection remain selectable for dark-going recordings.

### Host project persistence
- Added `.swell` container schema 3 with optional embedded source images (`images_embedded.json` plus `images/`) so projects can remain usable when the original stack folder moves.
- Embedded fallback loads now preserve the original recorded stack folder in `stack.json`; extracted temp directories are used only as live read sources and are not persisted as source folders.
- Saving with embedding enabled now fails clearly if no source image files can be embedded, instead of silently producing a project without its image payload.
- Saving a project from embedded fallback with embedding disabled is blocked until the user re-enables embedding or rebinds to a real source folder.
- Embedded extraction cleanup now runs after successful close saves or successful context replacement, and live extraction dirs are protected by an active marker.

### Export metrics
- Added the intensity export metric, including per-frame mean ROI intensity, baseline intensity, relative `delta_i_over_baseline_i`, plots, summaries, and workbook output.

### Model/checkpoint compatibility
- No checkpoint format or model selection change in this release; existing managed and local SAM2 model selections remain compatible.

### Platform/backend limitations
- Embedding source images can substantially increase `.swell` size; save-time confirmation reports the source stack size before copying frames into the project.

### .swell/migration notes
- Host `.swell` writers now emit schema 3. Schema 2 projects remain loadable.
- Swell 0.1.9 may open schema 3 projects but does not understand embedded source images; if a 0.1.9 build re-saves such a project, the embedded image payload can be dropped. Use 0.2.0 or later for projects that rely on embedded source images.

### Known segmentation caveats/regressions
- No new release-blocking segmentation regressions are known from the automated suite.
- SAM2 post-processing/native extension availability may still vary by environment.
- Auto-update behavior still depends on platform packaging/signing state; validate against final signed release artifacts.

## [0.1.9] - 2026-06-12

### Analysis window and tools UI
- Replaced the text-labeled segmentation tool buttons with icon buttons (select, point +/-, box, brush +/-, fill +/-, include/exclude region, clear frame), falling back to text labels when an icon asset is unavailable.
- Refreshed the application icon (macOS `.icns`, Windows `.ico`, runtime PNG) and added a reproducible icon-generation pipeline (`scripts/release/generate_app_icons.py`).
- Tool-mode changes are now routed through a single guarded handler so same-value hotkey re-presses no longer trigger redundant re-renders.

### Bug fixes
- Arrow-key timeline navigation and Delete/Backspace point deletion no longer fire while the user is typing in a text entry (e.g. the region frame-range fields), preventing accidental frame scrubbing and region deletion.
- Events are now returned in a stable chronological order (start, end, id) from both the host and unified project services.

### Performance
- Cached the per-cell quiet MAD across coherence-gate candidates and reused mask statistics across neighbor pairs in trouble scoring.
- Added a cached no-regions mask-frame set in segmentation state and tightened the render photo-cache key so tool switches no longer force cache misses.
- Hash full-stack exports via `memoryview` instead of duplicating arrays with `tobytes()`.

### Model/checkpoint compatibility
- No checkpoint format or model selection change in this release; existing managed and local SAM2 model selections remain compatible.

### Platform/backend limitations
- New toolbar icon assets are bundled from the `swell` package via PyInstaller `collect_data_files`; no backend behavior changes.

### .swell/migration notes
- No `.swell` schema version bump is required; existing projects remain loadable. Event ordering is normalized on load but does not alter stored data.

### Known segmentation caveats/regressions
- No new release-blocking segmentation regressions are known from the automated suite.
- SAM2 post-processing/native extension availability may still vary by environment.
- Auto-update behavior still depends on platform packaging/signing state; validate against final signed release artifacts.

## [0.1.8] - 2026-05-14

### Auto-detect and ROI improvements
- Fixed dialog sizing on Windows: replaced hardcoded `geometry()` calls with `minsize()` across the ROI dialog, scale dialog, auto-detect window, and mark popup so windows open at the correct size without overriding the window manager's placement.
- `center_window_on_screen` now uses the window's actual size rather than a hardcoded override, fixing off-center placement on Windows.

### Model/checkpoint compatibility
- No checkpoint format or project schema bump in this release; existing managed and local SAM2 model selections remain compatible.

### Platform/backend limitations
- Visual sizing and centering fixes are Windows-specific; no behavioral changes on macOS.

### .swell/migration notes
- No `.swell` schema version bump is required; existing projects remain loadable.

### Known segmentation caveats/regressions
- No new release-blocking segmentation regressions are known from the automated suite.
- SAM2 post-processing/native extension availability may still vary by environment.
- Auto-update behavior still depends on platform packaging/signing state; validate against final signed release artifacts.

## [0.1.7] - 2026-05-14

### Auto-detect and ROI improvements
- Overhauled the auto-detect window with a dual-pane overview/detail timeline, interactive ROI selection, grid opacity control, and per-cell border rendering for clearer event visualization.
- Added incremental algorithm rerun scheduling so parameter changes (scale, opacity, ROI) trigger a debounced re-evaluation without blocking the UI.
- Active-cell overlay and cell-border rendering are now cached by pipeline generation, avoiding redundant recomputation across frame scrubs.
- Exporter now selects ROI-scoped speed metrics when an ROI is defined, falling back to full-frame metrics otherwise.

### Performance
- Added `DownsampledFrameSource` (`swell/shared/frame_source/downsampled.py`) and `compute_visualization_stats_for_preview` to compute visualization stats at 0.25× resolution during the analysis-launch preview, then upsample the baseline back to full resolution — significantly reducing preview wait time on large stacks.
- Added `swell/shared/diagnostics/` with `OpenPerfTrace`: a lightweight wall-clock stage/mark tracer for the analysis-window open path. Traces are dumped to the app log on completion and silently discarded on failure.
- Analysis launch flow now wraps the full open sequence in a perf trace, attributing time to import, preview preparation, frame rendering, and options-dialog interactions.

### Model/checkpoint compatibility
- No checkpoint format or project schema bump in this release; existing managed and local SAM2 model selections remain compatible.

### Platform/backend limitations
- No platform-specific regressions are known from the automated suite.
- DC trace controller and host window controller received minor fixes to align with the updated auto-detect and analysis launch flows.

### .swell/migration notes
- No `.swell` schema version bump is required; existing projects remain loadable.
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

### .swell/migration notes
- No `.swell` schema version bump is required for this release; existing projects remain loadable.
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

### .swell/migration notes
- TBD

### Known segmentation caveats/regressions
- TBD

## [0.1.4] - 2026-03-26

### Model/checkpoint compatibility
- TBD

### Platform/backend limitations
- TBD

### .swell/migration notes
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

### .swell/migration notes
- No `.swell` schema version bump in this release.
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

### .swell/migration notes
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

### .swell/migration notes
- No `.swell` schema changes in release packaging phases 1-4.
- Canonical single-stack project structure remains unchanged.

### Known segmentation caveats/regressions
- Missing SAM2/model dependencies continues to disable model-based segmentation tools at runtime.
- macOS signing/notarization/stapling is not yet part of this phase and remains deferred.
