# Release checklist

Work through these sections top-to-bottom before publishing a release. Steps marked **CI** are verified automatically; all others require a manual check.

---

## 1. Documentation

- [ ] Screenshots in `docs/gui/host-window.md` and `docs/gui/analysis-window.md` are current (UI hasn't changed since last capture).
- [ ] No unresolved `<!-- TODO -->` comments remain in any `docs/` file.
- [ ] `docs/installation.md` reflects the current Python version requirement and install steps.
- [ ] `docs/troubleshooting.md` covers any new error messages or failure modes introduced in this release.
- [ ] `docs/file-formats.md` is updated if the `.sdproj` schema version changed or new export columns were added.
- [ ] `docs/citation.md` DOIs and version references are current (update after Zenodo archive is minted).

---

## 2. Version and changelog

- [ ] `pyproject.toml` `[project].version` is set to the target release version.
- [ ] `CHANGELOG.md` has a new section `## [X.Y.Z] - YYYY-MM-DD` with all four required headings:
  - `Model/checkpoint compatibility`
  - `Platform/backend limitations`
  - `.sdproj/migration notes`
  - `Known segmentation caveats/regressions`
- [ ] The changelog section accurately describes what changed for end users (not just internal refactors).

Use the bump script to do both version and changelog scaffold in one step:
```bash
python scripts/release/bump_version.py patch   # or minor / major / explicit version
```

---

## 3. Local build and smoke tests

- [ ] Python artifacts build cleanly: **(CI)**
  ```bash
  ./scripts/release/build_python_artifacts.sh
  ```
- [ ] macOS app bundles build for both architectures: **(CI)**
  ```bash
  ./scripts/release/build_macos_app_arm64.sh
  ./scripts/release/build_macos_app_x86_64.sh
  ```
- [ ] Startup smoke test passes (`SMOKE_TEST:PASS`): **(CI)**
  ```bash
  python -m sdapp.main --smoke-test
  ```
- [ ] Model and segmentation workflow smokes pass: **(CI)**
  ```bash
  python scripts/release/run_model_smoke.py
  python scripts/release/run_segmentation_workflow_smoke.py
  ```
- [ ] `dist/compatibility.json` includes `app_version`, `python_requires`, `supported_platforms`, `runtime_policy`. **(CI)**
- [ ] `dist/SHA256SUMS.txt` covers all `dist/` artifacts. **(CI)**

---

## 4. Clean-machine validation

Run this on a machine with no existing managed model directory before publishing.

- [ ] Launch app, complete model onboarding (download or manual select).
- [ ] Run one segmentation action and confirm masks are produced.
- [ ] Save project, reopen it, and verify the model mismatch warning/choice flow works.
- [ ] On Windows: unzip `sdapp-windows-x64.zip`, launch `SDApp.exe`, run startup + one segmentation workflow.

---

## 5. Tag and GitHub release

- [ ] All CI phase 2 PR jobs pass (`linux-validation`, `macos-arm64-validation`, `macos-x86_64-validation`, `windows-validation`).
- [ ] Create and push the release tag:
  ```bash
  git tag v0.X.Y
  git push origin v0.X.Y
  ```
- [ ] Wait for the `release-phase3-tag` workflow to finish.
- [ ] Open GitHub Releases and verify the draft:
  - [ ] Assets attached: `sdapp-macos-arm64.zip`, `sdapp-windows-x64.zip`, `compatibility.json`, `SHA256SUMS.txt`.
  - [ ] Release body matches the `CHANGELOG.md` section for this version.
  - [ ] `compatibility.json` version field matches `pyproject.toml`.
- [ ] Publish the draft manually.

---

## 6. Post-release

- [ ] Mint Zenodo archive for the new tag and update the DOI in `docs/citation.md`.
- [ ] Verify the GitHub Releases page shows the correct assets and release notes publicly.
- [ ] Start a new `## [Unreleased]` section in `CHANGELOG.md` for the next cycle.
