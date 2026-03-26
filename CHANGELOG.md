# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

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
