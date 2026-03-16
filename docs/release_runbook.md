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
