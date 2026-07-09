# Maintenance & Releases Guide

This guide details documentation maintenance procedures, pre-release checklists, and instructions for building and verifying the documentation site.

---

## 1. Documentation Update Checklist

Whenever new features, UI changes, or state persistence modifications are merged, complete this checklist to prevent documentation drift:

- [ ] **UI Screenshots**: Check if screenshots in `docs/gui/host-window.md` or `docs/gui/analysis-window.md` need to be updated.
- [ ] **Keyboard Shortcuts**: Update the hotkey tables in the GUI reference pages if any keyboard bindings are added, modified, or removed.
- [ ] **Data Schema**: If the `.swell` zip structure or logical prompt JSON schema is updated, increment and document the changes in `docs/file-formats.md`.
- [ ] **Troubleshooting**: Add entries for any new failure modes, dependency errors, or hardware warning flags to `docs/troubleshooting.md`.
- [ ] **Zenodo DOI**: Update the BibTeX entry in `docs/citation.md` with the new release version and Zenodo DOI after minting the release archive.

---

## 2. Release Notes & Changelog Checklist

Swell enforces strict release governance rules via automated CI checks in `.github/workflows/release_phase3_tag.yml`. Before creating a release tag:

1. **Verify Version Alignment**:
   Ensure `pyproject.toml` version matches the target release tag:
   ```toml
   [project]
   name = "swell"
   version = "0.1.9"  # Must match the v0.1.9 tag base version
   ```

2. **Changelog Section Format**:
   Add a release section in `CHANGELOG.md` matching this exact header layout:
   ```markdown
   ## [X.Y.Z] - YYYY-MM-DD
   ```

3. **Required Governance Headings**:
   The release validation job will fail if the new release section is missing any of these four literal headings:
   * `### Model/checkpoint compatibility`
   * `### Platform/backend limitations`
   * `### .swell/migration notes`
   * `### Known segmentation caveats/regressions`

4. **Scaffolding Tool**:
   To automate version bumping and changelog scaffolding in one step, use the bump script:
   ```bash
   python scripts/release/bump_version.py patch   # Options: patch, minor, major, or explicit version
   ```

---

## 3. Running & Verifying the Documentation Site

The Swell documentation is built using MkDocs and the Material theme.

### Installing Dependencies
To run the documentation server locally, install the required packages:
```bash
pip install -e ".[docs]"
```
This installs `mkdocs`, `mkdocs-material`, `mkdocs-include-markdown-plugin`, and `pymdown-extensions`.

### Local Development Server
To launch a local hot-reloading web server:
```bash
mkdocs serve
```
Open `http://127.0.0.1:8000/` in your browser. Changes to markdown files will automatically reload in the browser.

### Strictly Verifying the Build
Before committing updates or cutting a release, compile the site using strict validation to treat warnings (e.g. broken links, missing nav references) as build errors:

```bash
mkdocs build --strict
```

If the compilation succeeds without errors, the production site is generated under the `site/` folder and is ready to be published.

### Publishing to GitHub Pages
Documentation is published to GitHub Pages by the `Deploy docs` workflow. Before
merging documentation changes, run:

```bash
mkdocs build --strict
```

After changes are merged to `main`, confirm the `Deploy docs` workflow succeeds,
then check the published site at `https://parrishlab.github.io/Swell/`.

The repository's GitHub Pages settings must use `GitHub Actions` as the Pages
build and deployment source. The generated `site/` directory is build output and
should not be committed.
