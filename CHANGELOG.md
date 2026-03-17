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

## [0.1.3] - 2026-03-17

### Model/checkpoint compatibility
- TBD

### Platform/backend limitations
- TBD

### .sdproj/migration notes
- TBD

### Known segmentation caveats/regressions
- TBD

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
