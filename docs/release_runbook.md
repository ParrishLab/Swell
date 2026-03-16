# Local Release Runbook (No CI)

This runbook produces local release artifacts for the unified `sdapp` app.

## Prerequisites
- Python 3.12+
- Build tooling installed in active env:
  - `python3 -m pip install build`
  - `python3 -m pip install pyinstaller`
- Optional: `twine` for package validation (`python3 -m pip install twine`)

## Commands (run from repo root)
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
4. Generate compatibility manifest:
   ```bash
   ./scripts/release/generate_compatibility_manifest.py
   ```
5. Generate checksums:
   ```bash
   ./scripts/release/generate_checksums.sh
   ```

## Expected artifacts
After a successful run, `dist/` should contain:
- `sdapp-<version>.tar.gz`
- `sdapp-<version>-py3-none-any.whl`
- `sdapp-macos-arm64.zip`
- `sdapp-macos-x86_64.zip`
- `compatibility.json`
- `SHA256SUMS.txt`

## Minimum validation checklist
- Smoke output is exactly `SMOKE_TEST:PASS`.
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
  - compatibility manifest + checksums generation.

### Deferred checks (not Phase 2 gates)
- model initialization smoke,
- segmentation workflow smoke with sample dataset,
- tag-triggered draft release automation,
- Windows packaged binary build/release jobs,
- macOS signing/notarization/stapling.

## CI Phase 3 Draft Releases (Tag-Triggered)
Draft release automation is defined in `.github/workflows/release_phase3_tag.yml`.

### Trigger modes
- Tag push: any tag matching `v*` (for example `v0.1.0`).
- Manual backfill/rerun: `workflow_dispatch` with optional `release_tag` input (must start with `v`).

### Phase 3 jobs and pass criteria
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
  - startup smoke returns `SMOKE_TEST:PASS`.
- `release-assemble`:
  - collects Linux/macOS artifacts,
  - generates `dist/compatibility.json`,
  - generates `dist/SHA256SUMS.txt`,
  - verifies required release files are present.
- `publish-draft`:
  - creates/updates a GitHub draft release for the resolved tag,
  - uploads all files in `dist/` as release assets.

### Tag flow (example)
1. Ensure `pyproject.toml` version is finalized for release.
2. Create and push tag:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
3. Wait for `release-phase3-tag` workflow to finish.
4. Open GitHub Releases and validate draft contents.

### Draft validation checklist
- Draft release exists for the expected tag.
- Assets attached:
  - `sdapp-<version>.tar.gz`
  - `sdapp-<version>-py3-none-any.whl`
  - `sdapp-macos-arm64.zip`
  - `sdapp-macos-x86_64.zip`
  - `compatibility.json`
  - `SHA256SUMS.txt`
- `compatibility.json` reflects current `pyproject.toml` version and policy fields.
- `SHA256SUMS.txt` includes all published artifacts.

### Re-run behavior
- Re-running the workflow for the same tag updates the existing draft release assets.
- `workflow_dispatch` can be used to rebuild and republish a draft for an existing `v*` tag.
