# GitHub Release Packaging Plan

## Objective
Package `sdapp` into reproducible GitHub Releases for a SAM2.1 scientific desktop workflow that ships:
- Python package artifacts (`sdist` + `wheel`) for source installs.
- End-user desktop binaries (macOS first, then Windows) for no-Python installs.
- Checksums + release notes + explicit runtime compatibility metadata.

## Current Repo Signals (quick read)
- Packaging baseline exists in `pyproject.toml` (`setuptools`, script entrypoint `sdapp`).
- GUI runtime is `tkinter` and app startup is `python -m sdapp.main`.
- Runtime path utilities already include frozen-app handling (`sys.frozen`, `_MEIPASS`), which aligns with PyInstaller.
- No `.github/workflows` automation is present yet.
- Model weights are intentionally excluded from git (`*.pt`, `models/`), so release design must define model/model-file delivery.

## Release Runtime Contract (v1)
These decisions are required before implementing release automation.

### 1) Model Delivery Contract
Primary supported behavior:
- Packaged binaries ship without model files.
- First launch offers download of approved model files into a managed app-data directory.
- Offline/manual mode is first-class: users can point to a local model directory without download.
- Advanced mode allows custom model override (with explicit "unsupported/custom" indicator in UI/logs).

Default managed directory targets:
- macOS: `~/Library/Application Support/sdapp/models/`
- Windows: `%APPDATA%/sdapp/models/`
- Source installs may also use project-local paths for developers.

### 1b) Model Versioning vs Project State
- `.sdproj` metadata must persist the model identifier used for segmentation outputs (at minimum model filename, ideally immutable hash).
- On project open, app compares stored project-recorded model metadata against the active runtime model.
- If mismatched, app warns clearly and offers explicit choices (continue with active model, switch to project-recorded model file, or open read-only review mode).
- Release notes must document model changes that can alter segmentation behavior.

### 2) Compatibility Matrix Requirement
Every release must include a machine-readable compatibility manifest (for example `compatibility.json`) mapping:
- app version
- SAM2.1 code reference/version
- PyTorch version range
- Python version
- supported model IDs/files
- supported OS/arch
- runtime policy flags (CPU required, MPS/CUDA support level)

### 3) Runtime Backend Policy (initial)
- Official packaged binaries: CPU path is guaranteed.
- macOS packaged app: MPS may be enabled when detected, but CPU remains the guaranteed fallback.
- Source install: advanced GPU setups supported as best-effort with documented constraints.
- Windows packaged GPU support is deferred until after stable CPU release.

### 4) Segmentation Smoke-Test Contract
Release gating must include:
- Startup test: app launches and core imports succeed.
- Model test: model-file resolution and model initialization succeed (tiny model file or deterministic test backend).
- Workflow test: open sample image stack, run one segmentation operation, write output artifacts.

### 5) macOS Distribution Hardening
For public macOS binary releases:
- Sign `.app` with Developer ID.
- Notarize release archive.
- Staple notarization ticket.
- Verify first-launch and quarantine-safe path on a clean machine.

## Release Artifact Strategy
1. Always publish source artifacts:
- `sdapp-X.Y.Z.tar.gz`
- `sdapp-X.Y.Z-py3-none-any.whl`

2. Publish platform binaries (phased):
- Phase 1: macOS app archives built separately per architecture:
  - `sdapp-macos-arm64.zip`
  - `sdapp-macos-x86_64.zip`
- Phase 2: Windows app archive (`sdapp-windows-x64.zip`)
- Universal2 is deferred until separate-arch packaging and tests are stable.

3. Attach integrity metadata:
- `SHA256SUMS.txt` for all artifacts.

4. Publish compatibility metadata:
- `compatibility.json` as a release asset.

## Proposed Tooling
- Build backend: existing `setuptools` via `python -m build`.
- Binary bundling: `PyInstaller` with checked-in deterministic spec + runtime hooks.
- CI/CD: GitHub Actions + draft releases via `gh release` or `softprops/action-gh-release`.
- Version source of truth: `pyproject.toml` (`project.version`) until migrated.

## Implementation Plan

### Phase 0: Packaging + Runtime Readiness (foundation)
- Finalize model distribution policy (managed-download + offline/manual override + custom override rules).
- Finalize model-in-project policy (`.sdproj` stores model ID/hash + mismatch behavior on open).
- Define hardware/backend policy (CPU/MPS/CUDA guarantees by install type and platform).
- Establish compatibility manifest schema and ownership.
- Perform licensing review for SAM2.1 code + model-file redistribution.
- Define standard output layout for masks/overlays/logs/project files.
- Create tiny reproducible sample dataset for segmentation smoke tests.
- Confirm supported Python + OS/arch matrix.

### Phase 1: Local Reproducible Builds
- Add `scripts/release/build_python_artifacts.sh`:
  - Clean `dist/`
  - `python -m build`
  - Optional `twine check dist/*`
- Add `packaging/sdapp.spec` (deterministic PyInstaller config).
- Add macOS architecture-specific build scripts using `sdapp.spec`:
  - `scripts/release/build_macos_app_arm64.sh`
  - `scripts/release/build_macos_app_x86_64.sh`
- Add runtime hooks for:
  - model/model-file path resolution
  - resource/config resolution
  - backend/device mode selection and fallback logging
- Configure macOS `Info.plist` (via PyInstaller spec) to register `.sdproj` document type/UTI so double-click open works.
- Add/verify app-level file-open handler path for `.sdproj` launch events.
- Ensure multiprocessing frozen-app safeguards:
  - call `multiprocessing.freeze_support()` in `sdapp.main` before UI startup
  - validate multi-window/child-process behavior in packaged builds (no duplicate host window bootstrap)
- Add hidden-import audit and explicit data inclusion (configs/icons/templates/assets).
- Add `scripts/release/generate_checksums.sh`.
- Add `docs/release_runbook.md` with clean-machine validation steps.
- Add `--smoke-test` or equivalent non-interactive verification mode in app entrypoint.

### Phase 2: CI Validation Gates (PRs)
Prioritize runtime reliability checks over broad style gates while refactor is active.
- Build `sdist` + `wheel` in CI on every PR.
- Run startup/import smoke test.
- Run model-resolution/model-init smoke test.
- Run segmentation workflow smoke test against sample fixture.
- Run packaged-binary smoke test for both macOS architectures once builds exist.
- Run `.sdproj` association/open test (open sample project via file argument/open event path).
- Run multi-window/process smoke test to verify analysis window creation does not spawn duplicate host app instances.
- Add lint/type checks as secondary gates if they do not block release-critical checks.

### Phase 3: Tag-Driven Draft GitHub Releases
- Trigger on tags `v*`.
- Build assets:
  - Job A: `sdist` + `wheel`
  - Job B: macOS arm64 binary archive
  - Job C: macOS x86_64 binary archive
  - Job D (later): Windows binary archive
  - Job E: checksums + compatibility manifest
- Publish as draft release first (no immediate public publish).
- Maintainer promotes draft after quick manual validation.

### Phase 4: Versioning + Release Notes Discipline
- Enforce SemVer tag format (`vMAJOR.MINOR.PATCH`).
- Maintain `CHANGELOG.md` (or equivalent generated notes).
- Add release-note sections specific to scientific runtime behavior:
  - model compatibility (required changelog heading literal: `Model/checkpoint compatibility`)
  - platform limitations (CPU/MPS/CUDA)
  - migration notes for `.sdproj`/session format changes
  - known segmentation caveats/regressions
- Support pre-release tags (`-rc.N`) for stabilization windows.

## Definition of Done (first dependable public release)
A tagged release is considered complete only when:
- CI produces `wheel` + `sdist` + both macOS architecture binaries + checksums + compatibility manifest.
- Segmentation smoke tests pass in CI and clean-machine validation passes.
- `.sdproj` file association works for packaged macOS app (double-click opens project in app).
- Multi-window packaged runtime behavior is validated (no duplicate host bootstrap from child process creation).
- macOS artifact is signed, notarized, and stapled.
- Release notes include compatibility and known limitations.
- Users can complete at least one documented segmentation workflow from a clean install.

## Risks and Mitigations
- Refactor churn breaks packaged runtime:
  - Mitigation: deterministic spec, runtime hooks, segmentation smoke tests as release gates.
- Runtime mismatch (app/model/torch):
  - Mitigation: compatibility manifest + strict model policy.
- Large model payloads or network issues:
  - Mitigation: managed download with resumable/manual offline fallback.
- macOS distribution friction:
  - Mitigation: sign/notarize/staple and verify on a clean machine.

## Immediate Next Steps (updated)
1. Finalize model distribution and runtime backend policy in writing.
2. Finalize `.sdproj` model metadata/mismatch policy (model ID/hash persisted in project).
3. Add tiny reproducible segmentation fixture data and `--smoke-test` mode.
4. Create `packaging/sdapp.spec` + runtime hooks for model/resource/device resolution + `.sdproj` file association.
5. Add architecture-specific macOS build scripts (`arm64`, `x86_64`) and validate on clean machines.
6. Add PR CI for `sdist`/`wheel` builds plus startup/model/workflow/open-file/multiprocess smoke tests.
7. Add tag-triggered draft release workflow for Python artifacts + dual macOS binaries.
8. Add macOS signing/notarization steps once binary builds are stable.
