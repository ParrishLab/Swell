# Swell Rename / Rebrand Plan

> **Status:** Planning only. No code changed. This is a deduplicated map of every
> surface that must change to rename the tool, merged from two independent read-only
> audits plus targeted verification.
>
> **How to use this doc:** Treat it as a complete *map of surfaces*, grouped by rename
> axis. **Line numbers are approximate** — both source audits showed line-number drift
> (right file, wrong line). Re-grep the exact location at edit time; do **not** pipe
> these line numbers into a sed/scripted replace.

## The three independent rename axes

The renames are tangled in the code but should be decided and staged separately:

1. **Brand:** `swell` / `Swell` / `com.swell.*` → Swell
2. **Domain term:** `SD` (spreading depolarization) → `event`
3. **Extension:** `.sdproj` → new extension (e.g. `.swell`)

**Gating decision (must be made before any mechanical work):** choose the
backward-compatibility policy for persisted project files and OS/user-data identifiers —
*migration/compat shims* vs. *hard cut*. See [Landmines](#landmines--decisions-required).
This single choice determines whether Axis 3 is a find/replace or a schema-migration project.

---

## Axis 1 — Brand: `swell` / `Swell` → Swell

### Distribution identity & imports
- `pyproject.toml` — `name = "swell"`, console script `swell = "swell.main:main"`,
  `packages.find` include `swell*`, package-data key `swell`.
- `swell/` top-level package dir → rename drives **every** `import swell` / `from swell…`
  across **144 source files and 150 test files** (counts verified). Largest mechanical change.
- `swell/shared/app_metadata.py` — version lookup uses distribution name `swell`.
- `swell.egg-info/` — regenerated on build.

### Packaging / OS bundle identity
- `packaging/swell.spec` — executable/collect/.app names `Swell`; `bundle_identifier="com.swell.desktop"`;
  `CFBundleTypeName "Swell Project"`; UTI `com.swell.project`.
- `packaging/windows/swell_windows.spec` — `collect_data_files("swell")`, entry path, `name="Swell"`.
- `packaging/windows/swell_installer.nsi` — `APP_NAME "Swell"`, `APP_EXE "Swell.exe"`,
  `APP_PROG_ID "Swell.Project"`, output name `Swell-Setup-*.exe`, `InstallDir …\Swell`.
- Spec/installer **filenames** themselves: `swell.spec`, `swell_windows.spec`, `swell_installer.nsi`.

### Environment-variable override knobs (user/CI-facing → doc + compat surface)
- `swell/shared/torch_device.py` — `DEVICE_ENV_VAR = "SWELL_DEVICE"`.
- `swell/shared/services/checkpoint_runtime_service.py` — `SWELL_MODELS_DIR`.
- `swell/shared/services/instance_bridge.py` — `SWELL_INSTANCE_BRIDGE_PORT` (+ port-hash derivation).
- Build/CI also set `SWELL_*` flags: `scripts/release/build_macos_app_arm64.sh` (`SWELL_SIGN_UPDATES`),
  `scripts/release/build_windows_app_x64.ps1` (`SWELL_BUILD_INSTALLER`),
  `.github/workflows/release_phase3_tag.yml` (`SWELL_ENABLE_UPDATER_ARTIFACTS`).

### Python class symbols (internal, low risk)
- `swell/host/app.py` — `class SwellHostApp`.
- `swell/analysis/app.py` — `class SwellAnalysisApp`.
- `swell/shared/frame_source/stack_frame_source.py` — `class StackReaderFrameSource`.
- `swell/shared/errors.py` — `class SwellAppError`.

### Externally observable brand strings
- `swell/host/ui/root_window.py` — window title `"Swell"`, splash `"Starting Swell..."`.
- `swell/host/controllers/update_controller.py` — update prompt text.
- `swell/shared/services/update_service.py` — `win_sparkle_set_app_details("Clay Dunford", "Swell", …)`.
- `swell/shared/services/checkpoint_runtime_service.py` — HTTP `User-Agent: …Swell/1.0`.

### Docs / metadata
- `README.md`, `docs/index.md`, `docs/citation.md`, `mkdocs.yml`, `Swell_Instructions_Guide.docx`.

### ⚠ User-data locations (MIGRATION concern — see Landmine D)
- `swell/shared/config.py` — config dirs: Windows `…/Swell`, macOS `…/Application Support/Swell`,
  Linux `…/.config/swell`.
- `swell/shared/services/checkpoint_runtime_service.py` — model cache `…/swell`, fallback `~/.swell/models`
  (holds multi-GB SAM2 checkpoints).

---

## Axis 2 — Domain term: `SD` → `event`

> **Semantic caution:** `SD` is usually a *qualifier* on a word that already exists
> ("Event", "Marked Events", "Swell Project"). Collapse/rephrase — do **not** blind-replace,
> or you get "event Event". Each site needs a human read.

### Module / file / dir names (+ their imports and test mirrors)
- `swell/host/event_gui.py`
- `swell/host/event_detection/` (`detector.py`, `grid.py`, `traces.py`)
- `swell/shared/frame_source/sd_stack_source.py`
- `scripts/benchmark_event_detection.py`; `benchmarks/sd_auto_detection*/`
- Tests: `tests/host/test_multi_sd_sets.py`, `test_event_gui_context_switch.py`,
  `test_event_gui_export_options.py`, `test_event_gui_generate_metrics_picker.py`

### UI-visible strings (rephrase, don't substitute)
- Window titles: `swell/host/config.py` `APP_TITLE = "Swell Event Marker"`;
  `swell/analysis/app.py` `"Swell Analysis"`.
- Buttons/labels: `swell/host/app.py` `"Mark Event"`, `"Marked Events"`, `"manual SD marking mode"`;
  `swell/host/exporter.py` `"Marked Events"`.
- Menus: `swell/shared/menu/factory.py` `"Save Swell Project"`, `"Open Swell Project"`.
- Dialog titles: `swell/host/controllers/project_lifecycle_controller.py` `"Save Swell Project As"`,
  `"Open Swell Project"`; `swell/host/mark_popup_controller.py` `"Mark Event"`, `"Edit Event"`;
  `swell/host/app.py` `"Rename Event"`.
- Cross-window copy: `swell/analysis/app.py` `"Host-provided event scope"`,
  `"…Swell main window"`; `swell/analysis/controllers/host_mode_controller.py` `"managed by SD ID"`;
  `swell/analysis/core/project_workflow.py` `"Swell main window"`.

### Persisted event IDs (data surface — see Landmine C)
- Default `sd_event_001` appears widely: `swell/analysis/app.py`,
  `swell/analysis/core/analysis_workspace.py`, `swell/analysis/core/session_state.py`,
  `swell/analysis/core/project_session.py`.

---

## Axis 3 — Extension: `.sdproj` → `.swell`

> **Chosen extension: `.swell`** (lowercase). Rationale: the file = the product (cf.
> `.blend`, `.sketch`, `.psd`), short, self-documenting, and collision-free. The extension
> string is what OS associations key on (macOS `public.filename-extension`, Windows registry).
>
> - **Rejected `.swellproj`** — only upside is mirroring `.sdproj` one-for-one; not worth the
>   extra length/clunkiness.
> - **Rejected terse `sw*`** (`.swp`/`.swl`/`.swo`) — collide with the **Vim swap-file** family.
> - **Rejected domain-y** (`.event`, `.swevent`) — generic, collision-prone, and re-couples to scope.
>
> Derived strings travel with it: `.sdproj.tmp` → `.swell.tmp`; temp prefix
> `sdproj_embedded_` → `swell_embedded_`; marker `.sdproj_embedded_active` → `.swell_embedded_active`.
>
> **Independent of the owner string:** `.swell` (filename) and `HOST_PERSISTENCE_OWNER`
> (on-disk format identifier, Landmine B) are separate decisions — you can adopt `.swell`
> while keeping `"host_sdproj"` as the owner value for backward compatibility.

> **Two persistence implementations** carry this logic — see Landmine A. Apply every
> extension/format change in **both** and keep them in sync.

### Read/write/validation logic
- `swell/shared/persistence/unified_project_store.py` — suffix coercion + container check + `.sdproj.tmp`.
- `swell/analysis/core/project_store.py` — **second store**; also writes `.sdproj.tmp`.
- `swell/host/project_session_service.py`,
  `swell/host/controllers/project_lifecycle_controller.py` — open/save reject non-`.sdproj`.
- `swell/shared/project_naming.py` — `derive_project_name` / `derive_project_filename` strip/append `.sdproj`.
- `swell/shared/persistence/zip_io.py` — `EXTRACT_ACTIVE_MARKER = ".sdproj_embedded_active"`,
  `*.sdproj.tmp` pattern, `sdproj_embedded_` temp prefix.

### Tk file dialogs (extension + filter)
- `swell/host/controllers/project_lifecycle_controller.py` (`defaultextension`, `("Swell Project","*.sdproj")`).
- `swell/analysis/core/project_workflow.py`.

### OS file association
- macOS: `packaging/swell.spec` — UTI `com.swell.project`, `public.filename-extension ["sdproj"]`,
  `public.mime-type application/x-sdproj`, `CFBundleTypeIconFile sdproj_doc_icon.icns`.
- Windows: `packaging/windows/swell_installer.nsi` — registry keys for `.sdproj` (write on install, delete on uninstall).
- Helper scripts: `scripts/dev/register_sdproj_dev_app.sh`,
  `scripts/release/refresh_sdproj_association_mac.sh`, `scripts/release/generate_sdproj_icons.sh`.

### Icon assets (filenames)
- `swell/resources/assets/sdproj_doc_icon.{ico,icns,png,jpg}`.

### Docs
- `docs/file-formats.md`, `README.md`, `docs/user-guide.md`, and the CHANGELOG section header
  `### .sdproj/migration notes` — **generated** by `scripts/release/bump_version.py` and **asserted**
  by `tests/unit/test_release_governance.py` + `tests/unit/test_bump_version_script.py`.

---

## Cross-cutting

### Tests = safety net AND edit sites
Many tests hard-code the strings/identifiers being renamed — they will fail loudly (good)
and each is an edit site: `test_app_metadata.py` (`"Swell Event Marker"`),
`test_shared_menu_factory.py` (`"Save Swell Project"`), `test_packaging_metadata.py`
(`com.swell.project`), `test_project_naming.py` / `test_unified_project_service.py` (`*.sdproj`),
`test_instance_bridge.py`, `test_release_scripts.py`, `test_update_service.py`.

### External / infra (not fixable by editing source alone)
- GitHub repo `ClayDunford/Combined-tool-test` — URLs baked into `config.json` (update channels),
  `docs/citation.md`, `docs/installation.md`, `docs/troubleshooting.md`, `mkdocs.yml`, and the
  appcast generators (`scripts/release/generate_appcasts.py`). Repo rename → update all + Sparkle feeds.
- Code-signing / notarization tied to `com.swell.desktop`.
- Release artifacts/CI: `.github/workflows/release_phase*.yml`,
  `scripts/release/build_macos_app_arm64.sh`, `build_windows_app_x64.ps1`,
  `generate_appcasts.py` encode artifact names + appcast URLs that must stay aligned with `update_service.py`.

### Hardcoded local dev paths (break on any repo move, brand-independent)
- `scripts/benchmark_event_detection.py` — `DEFAULT_DATA_DIR`, `DEFAULT_RECOVERY_ROOT`,
  `DEFAULT_SWELL_ROOT = "/Users/claydunford/Development/Combined tool test"`.
- `benchmarks/sd_auto_detection*/` summary/CSV reference external dataset folders.

### Scoped out (vendored/generated noise)
`.venv`, `dist/`, `build/`, `site/`, `.git/`, `__pycache__/`, `*.egg-info/`, bundled Sparkle framework.
(The duplicate `.claude/worktrees` worktree was removed, so it no longer inflates results.)

---

## Landmines / decisions required

### A. 🚨 Duplicate persistence path
`.sdproj` / temp-file / `events/{id}/…` logic lives in **two** stores:
`swell/shared/persistence/` (unified_project_store, zip_io, serialization, schema) **and**
`swell/analysis/core/project_store.py`. Any extension/owner/format change must land in both
and be tested on both, or saves and loads diverge.

### B. 🚨 Format-internal owner identifier
`swell/shared/persistence/schema.py` — `HOST_PERSISTENCE_OWNER = "host_sdproj"` is **written into
every saved project** and **validated on load** (`unified_project_store.py` raises
`"Unsupported persistence owner"`). **Decision:** (1) keep the literal `"host_sdproj"` on disk for
compat, rename only the Python symbol; (2) accept an allow-list of old+new owners + migrate;
(3) hard-cut and break old files.

### C. Persisted event IDs as on-disk paths
Event IDs are written as zip paths (`events/{segment}/masks.npz` in
`shared/persistence/serialization.py` and `analysis/core/project_store.py`) and the default segment is
`sd_event_001`. **Mitigation already present:** `masks_ref`/`prompts_ref` are stored in the project JSON
and read back on load, so changing the ID *generator* affects only *new* projects — old files stay
loadable **as long as no code pattern-matches the `"sd_event"` prefix**. **Decision:** rename the
generator only (legacy `sd_` persists inside old projects), or add a schema-aware path migration.

### D. User-data relocation
Config dirs (`…/Swell`, `~/.config/swell`) and model-cache dirs (`…/swell`, `~/.swell/models`,
multi-GB SAM2 weights) move on rename. **Decision:** first-launch auto-migrate (copy/rename old →
new), keep reading old locations, or reset (forces re-download of checkpoints).

### E. OS associations
macOS UTI `com.swell.project` and Windows ProgId `Swell.Project` are registered with the OS.
**Decision:** whether new installers migrate/remove old associations and whether double-clicking an
existing `.sdproj` still opens the app.

---

## Suggested staging
1. **Decide names + compat policy** (the gate). Nothing mechanical until this is fixed.
2. **Brand** (Axis 1): package rename + imports + packaging + env vars + user-data migration shim.
3. **Domain term** (Axis 2): module/file renames, then UI string rephrases (human-read each).
4. **Extension** (Axis 3): both stores in lockstep, OS association, icons, docs, compat shim.
5. Update tests alongside each axis; treat green tests as the rename's definition of done.
