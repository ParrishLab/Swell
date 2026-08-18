# Changelog

All notable changes to this project are documented in this file.

## [0.3.7] - 2026-08-17

### Dialog accessibility and navigation
- Long messages and content-heavy workflows now use auto-sizing, scrollable dialog bodies with pinned action rows, keeping confirmation and cancellation controls reachable on short displays. This applies to application alerts, propagation-gap warnings, export options, metrics generation, DC-trace import, and Analysis launch options.
- Dialog scrollbars appear only when content overflows, while shorter dialogs retain their natural height instead of expanding to the full screen budget.
- The Model Manager now provides a vertical scrollbar for catalogs that exceed the visible rows, so every available checkpoint remains reachable.
- ROI and scale dialogs now share the same navigation behavior: hold **Shift** or **Space** while dragging to pan. Both dialogs display the navigation hint alongside their zoom controls.

### Window behavior
- Shared UI sizing helpers now keep scrollable content within the usable display area while allowing footer controls and status rows to remain fixed and visible.
- Host dialog controllers use the shared overflow layout consistently, reducing platform-specific clipping when fonts, display scaling, or content length increase a dialog's requested height.

### Model/checkpoint compatibility
- No checkpoint format, catalog, model-selection, or SAM2 inference change in this release; existing managed and local SAM2 selections remain compatible.

### Platform/backend limitations
- Dialog work-area budgets still rely on Tk's screen dimensions and reserved margins because Tk does not expose a portable operating-system work-area API. Exact window placement can vary slightly across desktop environments and display-scaling configurations.
- CPU fallback behavior is unchanged and remains substantially slower than accelerated SAM2 inference on large stacks.

### .swell/migration notes
- No schema-number change is required. Existing `.swell` projects, model selections, DC-trace attachments, metric settings, and saved analysis data remain compatible.

### Known segmentation caveats/regressions
- The dialog and navigation changes affect presentation and input handling only; they do not alter source images, ROI coordinates, scale calculations, masks, prompts, or exported measurements.
- Mask-generation thresholds are still not persisted in `.swell` files. Restored masks begin with an unknown threshold and are treated as fresh until regenerated during the current session.
- Changing **Mask Threshold** still re-thresholds prompted frames on slider release; propagated frames remain visibly stale until propagation is rerun. Ground-truth and manually painted frames are never marked stale.
- No known SAM2 inference or stored-mask regression is introduced by this release.

## [0.3.6] - 2026-08-17

### Preview and window layout
- The Host frame viewer and Mark/Edit Event preview now constrain rendered images to the available window area instead of allowing tall frames to push sliders, navigation, baseline controls, or confirmation buttons below the screen edge.
- Main and popup previews re-fit after their containers are resized, using debounced rerenders to avoid repeated work during active window resizing.
- Mark/Edit Event windows clamp their initial and minimum sizes to the available display area, and loading progress is placed directly below the preview rather than after the bottom action controls.
- Shared window centering now accounts for reserved operating-system screen space and relaxes minimum sizes that exceed the usable display area.

### Release packaging
- macOS and Windows release archives now include the application version in their download names, for example `swell-0.3.6-macos-arm64.zip` and `swell-0.3.6-windows-x64.zip`. Release assembly, checksums, updater feeds, and the release checklist use the same versioned names.

### Model/checkpoint compatibility
- No checkpoint format, catalog, model-selection, or SAM2 inference change in this release; existing managed and local SAM2 selections remain compatible.

### Platform/backend limitations
- Usable display bounds are derived from Tk's screen dimensions with reserved margins for operating-system chrome because Tk does not expose a portable work-area API. Window-manager placement may still vary slightly across desktop environments.
- CPU fallback behavior is unchanged and remains substantially slower than accelerated SAM2 inference on large stacks.

### .swell/migration notes
- No schema-number change is required. Existing `.swell` projects, embedded images, event ranges, metric settings, and saved analysis data remain compatible.

### Known segmentation caveats/regressions
- Preview resizing changes display geometry only; it does not resample source frames, masks, prompts, or exported measurements.
- Mask-generation thresholds are still not persisted in `.swell` files. Restored masks begin with an unknown threshold and are treated as fresh until regenerated during the current session.
- Changing **Mask Threshold** still re-thresholds prompted frames on slider release; propagated frames remain visibly stale until propagation is rerun. Ground-truth and manually painted frames are never marked stale.
- No known SAM2 inference or stored-mask regression is introduced by this release.

## [0.3.5] - 2026-08-13

### Detection and metric calibration
- Auto-detection timing windows are now defined in seconds and converted to frames using the project's **Frames per second** value. The Auto-Detect window exposes that shared FPS setting, so smoothing, lookback, lookahead, event duration, persistence, splitting, and coherence baselines retain their intended real-time durations across acquisition rates.
- Scale calibration can use a reference image with different pixel dimensions after an explicit warning, supporting uncropped or unsplit references from the same acquisition. ROI reference images still require an exact stack-dimension match because their coordinates map directly onto the loaded stack.
- The event-metrics guide now explains when a differently sized scale reference is valid and when resizing or resampling would make the calibration unsafe.

### Release reliability
- Packaged macOS and Windows ZIPs are uploaded directly to an idempotent draft GitHub release instead of passing large build directories through GitHub Actions artifact storage. Final compatibility metadata and checksums are assembled from those release assets, avoiding organization storage-quota failures while preserving rerun safety.
- Source and editable checkouts now read the application version from `pyproject.toml` before installed package metadata, preventing a stale environment from reporting the previous release immediately after a version bump.

### Model/checkpoint compatibility
- No checkpoint format, catalog, model-selection, or SAM2 inference change in this release; existing managed and local SAM2 selections remain compatible.

### Platform/backend limitations
- Differently sized scale references are valid only when they preserve the loaded stack's pixel resolution, such as an image cropped or split without resizing. References that were resampled or acquired at another resolution can produce incorrect pixels-per-millimeter calibration.
- ROI reference images must still match the loaded stack dimensions exactly. CPU fallback behavior is unchanged and remains substantially slower than accelerated SAM2 inference on large stacks.

### .swell/migration notes
- No schema-number change is required. Existing `.swell` projects remain compatible, and their stored project FPS continues to drive time-based metrics and now also scales Auto-Detect timing windows.

### Known segmentation caveats/regressions
- Mask-generation thresholds are still not persisted in `.swell` files. Restored masks begin with an unknown threshold and are treated as fresh until regenerated during the current session.
- Changing **Mask Threshold** still re-thresholds prompted frames on slider release; propagated frames remain visibly stale until propagation is rerun. Ground-truth and manually painted frames are never marked stale.
- At 1 frame per second, Auto-Detect retains the original calibrated frame counts. At other acquisition rates, candidate windows can differ from earlier Swell versions because timing now preserves seconds rather than fixed frame counts; no known SAM2 inference or stored-mask regression is introduced.

## [0.3.4] - 2026-08-05

### Documentation and guided workflows
- Added interactive documentation for event marking, opening Analysis, segmentation prompts, propagation review, correction strategy, preprocessing choices, and metrics calibration.
- Expanded the correction-strategy and calibration guidance so users can practice common review decisions before applying them to experimental data.

### Reliability and data integrity
- Autosave rotation now resumes after the newest existing recovery slot, main-thread snapshot dispatches time out cleanly, and stale extraction cleanup reports only directories that were actually removed.
- Legacy project migration determines propagation completion from loaded mask payloads instead of generated reference paths, and rejected host saves no longer appear successful.
- TIFF indexing falls back to Pillow when tifffile cannot parse a single-frame image. Per-file reads and non-aggressive cleanup no longer hold the global TIFF pool lock while waiting on an active handle.
- DC-trace imports tolerate incomplete channel metadata, preserve active-only scaling rows and vectors, and bound resized display-data caches.
- Invalid nonpositive metric calibration values are rejected, repeated out-of-memory recovery retains its target calculator, and the metrics dialog closes after reporting save failures.

### Model/checkpoint compatibility
- No checkpoint format, catalog, model-selection, or SAM2 inference change in this release; existing managed and local SAM2 selections remain compatible.

### Platform/backend limitations
- The Pillow TIFF fallback indexes files as single-frame images; multi-page and multidimensional TIFF stacks still require tifffile-compatible metadata and codecs for full fidelity.
- CPU fallback behavior is unchanged and remains substantially slower than accelerated SAM2 inference on large stacks.

### .swell/migration notes
- No schema-number change is required. Schema 2 projects still migrate to the current schema, but propagation completion is now inferred from the masks actually loaded for each event when payloads are available.
- Existing `.swell` projects, autosave slots, external image references, and DC-trace attachments remain compatible.

### Known segmentation caveats/regressions
- Mask-generation thresholds are still not persisted in `.swell` files. Restored masks begin with an unknown threshold and are treated as fresh until regenerated during the current session.
- Changing **Mask Threshold** still re-thresholds prompted frames on slider release; propagated frames remain visibly stale until propagation is rerun. Ground-truth and manually painted frames are never marked stale.
- No known SAM2 inference or stored-mask regression is introduced by this release.

## [0.3.3] - 2026-07-27

### Analysis responsiveness and memory
- Navigation prewarming, leverage-map recomputation, and metrics previews now coalesce superseded work and keep expensive computation off the UI thread. Interactive point, box, and region drags redraw only editable vector overlays until release instead of rebuilding the full frame.
- Mask rendering now uses bounded, frame-scoped composition and ghost-contour caches. Brush and fill tools avoid repeated full-frame scratch allocations while preserving their previous rasterization, and unchanged paint gestures no longer create undo entries.
- Boolean mask snapshots are bit-packed for undo, autosave, and background project serialization. Undo history now has both action-count and memory limits, autosave retains only the newest pending snapshot, and object-lineage tracking stores cropped component masks and uses bounded nearest-boundary searches.

### Project and stack portability
- Stack identity v2 normalizes Unicode frame names and fingerprints sampled source-file content independently of absolute paths and decoder output. Saved RGB channel policy and a separate decoded-pixel fingerprint prevent silent channel reinterpretation while allowing the same unchanged source stack to move between operating systems and codec environments.
- Structurally incompatible replacement stacks remain blocked. A structurally compatible stack with a different saved identity can now be accepted explicitly after a detailed warning, and legacy unversioned stack fingerprints remain supported.
- Project image references are rewritten relative to the `.swell` file and resolved relative to that project before stale absolute or working-directory paths. Content fingerprints no longer change solely because a file timestamp changed.
- Embedded images, event folders, and exported frames now use normalized, length-bounded, Windows-safe names with case-insensitive collision handling. Project names derived from Windows paths also work when Swell is running on another platform.
- Missing external DC traces can be rebound during project restore, with the replacement path persisted after a successful load.

### Image and metrics behavior
- Host and Analysis imports now reject stacks containing mixed pixel dtypes instead of accepting a partial stack. Natural filename ordering has a deterministic Unicode-aware tie-breaker and is shared by image and mask-folder imports.
- Scale calibration now defaults to an unlocked axis in new state and in older projects that do not contain an explicit axis-lock preference.
- Multi-monitor tooltip placement now respects negative virtual-desktop coordinates and keeps tooltips within the active application window.

### Model/checkpoint compatibility
- No checkpoint format, catalog, model-selection, or SAM2 inference change in this release; existing managed and local SAM2 selections remain compatible.
- Prepared-frame cache identity now follows the portable source identity rather than absolute source paths, so moving an unchanged stack does not invalidate otherwise equivalent cache content.

### Platform/backend limitations
- Every frame in a stack must now share both its oriented dimensions and canonical pixel dtype. Mixed-dtype stacks are rejected with the mismatching files listed; convert them to one common dtype before import.
- RGB stacks saved with a persisted `average` or `first` channel policy reopen with that policy without prompting. Older projects without the field retain the existing selection prompt when needed.
- CPU fallback behavior is unchanged and remains substantially slower than accelerated SAM2 inference on large stacks.

### .swell/migration notes
- No schema-number change is required. `.swell` writers still emit schema 3, and schema 2 projects plus unversioned 0.3.2 stack fingerprints remain loadable.
- Newly saved stack references may include versioned source/name fingerprints, a decoded-pixel fingerprint, RGB channel mode, and decode-policy version. Older projects can omit all of these fields.
- Newly saved image manifests include paths relative to the project location. Existing absolute paths remain readable, and embedded image extraction remains compatible while applying portable output names.

### Known segmentation caveats/regressions
- Mask-generation thresholds are still not persisted in `.swell` files. Restored masks begin with an unknown threshold and are treated as fresh until regenerated during the current session.
- Changing **Mask Threshold** still re-thresholds prompted frames on slider release; propagated frames remain visibly stale until propagation is rerun. Ground-truth and manually painted frames are never marked stale.
- The rendering, paint, undo, autosave, and object-tracking changes are storage and execution optimizations with output-parity regression coverage; no known SAM2 inference or stored-mask regression is introduced.

## [0.3.2] - 2026-07-21

### Analysis workflow
- The global **Mask Threshold** control now lives with propagation settings. Releasing the slider re-thresholds every prompted frame, while propagated masks generated at a meaningfully different threshold are marked amber and hatched on the canvas and timeline until propagation is rerun.
- Host-launched Analysis windows now restore committed and draft masks, prompts, ground-truth frames, scoped timeline state, and the active frame consistently. Unsaved prompt-only work is included in close warnings.
- Host-to-Analysis mapping signatures reject stale mask, metrics, and project saves after event bounds, baseline scope, or preprocessing settings change. Baseline-scope edits remap saved analysis state; stabilization changes require clearing coordinate-dependent masks, prompts, and ROI geometry.

### Image stacks and preprocessing
- Added shared, metadata-aware image decoding for EXIF/TIFF orientation, planar and interleaved color, multi-frame TIFF axes, high-bit-depth grayscale, and consistent Host/Analysis results.
- Stack imports now reject mixed oriented dimensions atomically instead of silently dropping frames, sanitize non-finite pixels throughout preprocessing, and preserve the previous open stack when a replacement fails.
- New stack identity fingerprints prevent a different recording with matching dimensions from being rebound accidentally. When the recorded source folder has changed, an embedded matching stack is preferred when available.
- Baseline subtraction now uses only available pre-event frames and permits a true zero-frame baseline; preview stabilization offsets are converted back to full-resolution coordinates before reuse.

### Reliability and quality
- SAM2 cache keys now include source content, visualization content, baseline data, and stabilization offsets, preventing stale prepared frames from being reused across materially different inputs.
- Model runtime initialization validates checkpoint files earlier and fully cleans partial state after failed builds or model switches.
- Improved extreme-aspect-ratio viewport fitting, tooltip scheduling, ROI downsampling, and analysis-window shutdown safety.
- CI now enforces branch coverage and runs image-decoding and persistence tests on macOS and Windows in addition to Linux.

### Model/checkpoint compatibility
- No checkpoint format, catalog, or model-selection change in this release; existing managed and local SAM2 selections remain compatible.
- Frame-cache identities changed, so cached prepared frames from earlier versions are not reused when their source or preprocessing content differs.

### Platform/backend limitations
- Every frame in a stack must resolve to the same dimensions after EXIF/TIFF orientation is applied. Mixed-size stacks are rejected with the mismatching files listed; resize, crop, or pad them before import.
- CPU fallback behavior is unchanged and remains substantially slower than accelerated SAM2 inference on large stacks.

### .swell/migration notes
- No schema-number change in this release. `.swell` writers still emit schema 3, and schema 2 projects remain loadable.
- Newly saved stack references include optional frame-name and source-content fingerprints. Older projects without these fields remain compatible and gain fingerprints when their stack is rebound or saved through the current workflow.

### Known segmentation caveats/regressions
- Mask-generation thresholds are tracked in memory but are not persisted in `.swell` files. Restored masks therefore begin with an unknown threshold and are treated as fresh until regenerated during the current session.
- Changing **Mask Threshold** re-thresholds prompted frames on slider release; propagated frames remain visibly stale until propagation is rerun. Ground-truth and manually painted frames are never marked stale.
- No known SAM2 inference or stored-mask regressions in this release.

## [0.3.1] - 2026-07-17

### Metrics and export
- Propagation displacement and object-lineage tracking thresholds now use physical units and are converted from each dataset's pixels-per-millimeter calibration, keeping filtering behavior consistent across image resolutions. Export summaries record both the physical thresholds and their pixel equivalents; propagation retains the existing 2 px fallback when calibration is unavailable.
- Programmatic object-lineage exports can omit source-frame overlays and the overview montage while retaining lineage summaries, tables, and numerical metrics.

### Fixes
- Checkpoint data-root and legacy-model migration routing now use one consistent platform signal, so Linux XDG paths are selected correctly in cross-platform validation.

### Model/checkpoint compatibility
- No checkpoint format, catalog, or model-selection change in this release; existing managed and local SAM2 selections remain compatible.

### Platform/backend limitations
- Physically scaled propagation and lineage thresholds require a valid pixels-per-millimeter calibration. Propagation falls back to the legacy 2 px threshold when calibration is unavailable, and lineage metrics continue to require their existing ROI and scale inputs.

### .swell/migration notes
- No schema change in this release. `.swell` writers still emit schema 3, and schema 2 projects remain loadable.

### Known segmentation caveats/regressions
- No known segmentation regressions in this release. The threshold changes affect exported propagation and lineage measurements, not SAM2 inference or stored masks.

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
