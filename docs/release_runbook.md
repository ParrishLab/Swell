# Local Release Runbook (No CI)

This runbook produces local release artifacts for the unified `sdapp` app.

## Prerequisites
- Python 3.12+
- Build tooling installed in active env:
  - `python3 -m pip install build`
  - `python3 -m pip install pyinstaller`
- Optional: `twine` for package validation (`python3 -m pip install twine`)

## Commands (run from repo root)
0. Optional: bump release version + scaffold changelog section in one step:
   ```bash
   python3 scripts/release/bump_version.py patch
   ```
   - Also supports `minor`, `major`, or explicit version (`python3 scripts/release/bump_version.py 0.2.0`).
   - Add `--tag` to create `v<new_version>` locally.
1. Build Python artifacts (`sdist` + `wheel`):
   ```bash
   ./scripts/release/build_python_artifacts.sh
   ```
2. Build macOS app archives:
   ```bash
   ./scripts/release/build_macos_app_arm64.sh
   ./scripts/release/build_macos_app_x86_64.sh
   ```
3. Run non-interactive startup/import smoke test:
   ```bash
   python3 -m sdapp.main --smoke-test
   ```
4. Run model + segmentation workflow smoke tests:
   ```bash
   python3 scripts/release/run_model_smoke.py
   python3 scripts/release/run_segmentation_workflow_smoke.py
   ```
5. Build Windows x64 portable archive (on Windows runner):
   ```powershell
   ./scripts/release/build_windows_app_x64.ps1
   ```
6. Generate compatibility manifest:
   ```bash
   ./scripts/release/generate_compatibility_manifest.py
   ```
7. Generate checksums:
   ```bash
   ./scripts/release/generate_checksums.sh
   ```

## Expected artifacts
After a successful run, `dist/` should contain:
- `sdapp-<version>.tar.gz`
- `sdapp-<version>-py3-none-any.whl`
- `sdapp-macos-arm64.zip`
- `sdapp-macos-x86_64.zip`
- `sdapp-windows-x64.zip` (when built on Windows)
- `compatibility.json`
- `SHA256SUMS.txt`

## Minimum validation checklist
- Smoke output is exactly `SMOKE_TEST:PASS`.
- Model smoke output is exactly `MODEL_SMOKE:PASS`.
- Segmentation workflow smoke output is exactly `SEGMENTATION_WORKFLOW_SMOKE:PASS`.
- `dist/compatibility.json` exists and includes:
  - `app_version`
  - `python_requires`
  - `supported_platforms`
  - `runtime_policy`
- `dist/SHA256SUMS.txt` exists and includes hashes for produced top-level `dist` files.

## CI Phase 2 Gates (PR)
PR validation now includes four required jobs in `.github/workflows/release_phase2_pr.yml`:
- `linux-validation`
- `macos-arm64-validation`
- `macos-x86_64-validation`
- `windows-validation`

### What each job validates
- Linux:
  - full test suite,
  - Python artifact build (`sdist` + wheel),
  - startup smoke (`SMOKE_TEST:PASS`),
  - model + segmentation workflow smokes,
  - compatibility manifest + checksums generation.
- macOS arm64:
  - startup smoke,
  - native arm64 app bundle build + zip output checks.
- macOS x86_64:
  - startup smoke,
  - native x86_64 app bundle build + zip output checks.
- Windows:
  - full test suite,
  - startup smoke,
  - model + segmentation workflow smokes,
  - Windows x64 package build (`dist/sdapp-windows-x64.zip`),
  - compatibility manifest + checksums generation.

### Deferred checks (not Phase 2 gates)
- packaged app open-file association smoke tests,
- segmentation workflow smoke with a real sample dataset fixture,
- macOS signing/notarization/stapling.

## CI Phase 3 Draft Releases (Tag-Triggered)
Draft release automation is defined in `.github/workflows/release_phase3_tag.yml`.

### Trigger modes
- Tag push: any tag matching `v*` (for example `v0.1.0`).
- Manual backfill/rerun: `workflow_dispatch` with optional `release_tag` input.

### Release contract enforced in Phase 4
- Accepted tags only:
  - stable: `vMAJOR.MINOR.PATCH`
  - prerelease: `vMAJOR.MINOR.PATCH-rc.N`
- `pyproject.toml` version must match tag base version.
- `CHANGELOG.md` must include a section for that version.
- Required changelog headings in that section:
  - `Model/checkpoint compatibility`
  - `Platform/backend limitations`
  - `.sdproj/migration notes`
  - `Known segmentation caveats/regressions`
- Draft release body is generated from the matching `CHANGELOG.md` section (`_release/release_notes.md`).

### Phase 3 jobs and pass criteria
- `release-validate`:
  - resolves release tag from event input/tag ref,
  - validates tag format, `pyproject.toml` version match, and changelog section/headings.
- `linux-python-artifacts`:
  - full test suite passes,
  - startup smoke returns `SMOKE_TEST:PASS`,
  - wheel + sdist build succeeds.
- `macos-arm64-package`:
  - startup smoke passes,
  - `dist/macos-arm64/SDApp.app` exists,
  - `dist/sdapp-macos-arm64.zip` exists.
- `macos-x86_64-package`:
  - startup smoke passes,
  - `dist/macos-x86_64/SDApp.app` exists,
  - `dist/sdapp-macos-x86_64.zip` exists.
- `windows-runtime-gate`:
  - full test suite passes,
  - startup smoke returns `SMOKE_TEST:PASS`,
  - model + segmentation workflow smokes pass,
  - Windows x64 package is produced.
- `release-assemble`:
  - collects Linux/macOS artifacts,
  - collects Windows x64 package,
  - generates `_release/release_notes.md` from changelog,
  - generates `dist/compatibility.json`,
  - generates `dist/SHA256SUMS.txt`,
  - verifies required release files are present.
- `publish-draft`:
  - creates/updates a GitHub draft release for the resolved tag,
  - uses `_release/release_notes.md` as release body,
  - uploads all files in `dist/` as release assets.

### Release-cut checklist (strict)
1. Update `pyproject.toml` `[project].version` to target release version.
2. Add/update `CHANGELOG.md` section for that version with all required headings.
3. Create and push tag:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Wait for `release-phase3-tag` workflow to finish.
5. Open GitHub Releases and validate draft contents and notes body.
6. Publish draft manually only after validation.

### Draft validation checklist
- Draft release exists for the expected tag.
- Assets attached:
  - `sdapp-<version>.tar.gz`
  - `sdapp-<version>-py3-none-any.whl`
  - `sdapp-macos-arm64.zip`
  - `sdapp-macos-x86_64.zip`
  - `sdapp-windows-x64.zip`
  - `compatibility.json`
  - `SHA256SUMS.txt`
- Release body text matches the version section in `CHANGELOG.md`.
- `compatibility.json` reflects current `pyproject.toml` version and policy fields.
- `SHA256SUMS.txt` includes all published artifacts.

### Re-run behavior
- Re-running the workflow for the same tag updates the existing draft release assets.
- `workflow_dispatch` can be used to rebuild and republish a draft for an existing `v*` tag.

### Troubleshooting (validation failures)
- Invalid tag format:
  - Use only `vX.Y.Z` or `vX.Y.Z-rc.N` (for example `v0.2.0` or `v0.2.0-rc.1`).
- Version mismatch:
  - Align `pyproject.toml` version with the tag base version (example: tag `v0.2.0-rc.1` requires `version = "0.2.0"`).
- Missing changelog section:
  - Add `## [X.Y.Z] - YYYY-MM-DD` to `CHANGELOG.md`.
- Missing required changelog headings:
  - Ensure all four required headings exist under the release section exactly as listed above.

## Model Runtime Notes (Phase 5)
- Model checkpoints are resolved in this priority:
  1. project-recorded checkpoint metadata (if valid),
  2. managed default checkpoint directory,
  3. explicit manual override path.
- Managed model directory:
  - macOS: `~/Library/Application Support/sdapp/models`
  - Windows: `%APPDATA%\\sdapp\\models`
- On clean machines without a local checkpoint, analysis prompts for first-run onboarding:
  - download approved checkpoint from catalog, or
  - select local checkpoint manually.
- On project open, when recorded checkpoint metadata differs from active runtime checkpoint, analysis prompts:
  - switch to the recorded checkpoint,
  - continue with current checkpoint,
  - cancel model initialization (review-only mode).
- If SAM2/Torch is unavailable, analysis initializes a deterministic CPU fallback backend so segmentation tools remain usable.

## Manual Clean-Machine Validation (Phase 5)
1. Start with no existing managed model directory.
2. Launch app and open analysis from host.
3. Complete checkpoint onboarding (download or manual select).
4. Run one segmentation action and confirm masks are produced.
5. Save project, reopen, and verify checkpoint metadata warning/choice flow works when checkpoint differs.
6. On Windows, validate portable package:
   - unzip `sdapp-windows-x64.zip`,
   - launch `SDApp.exe`,
   - run startup + one segmentation workflow.
