# Comment Neutrality Audit (Open-Source Release Readiness)

## Objective and Scope
This audit reviews code comments for open-source release readiness with a neutral, external-reader perspective.

Scope included:
- Production code only: `sdapp/**` Python modules.
- Comment forms: inline `#` comments, separator/block comments, and docstrings.

Scope excluded:
- `tests/**`
- `docs/**`
- Markdown prose outside code modules
- Machine/style annotations (`# noqa`, `# pragma`, type-ignore comments), except when wording quality was relevant.

## Method and Rubric
Method:
- Enumerated all Python files under `sdapp/**`.
- Scanned comment-bearing lines and docstrings.
- Manually reviewed comment tone, clarity, stability, and signal quality.

Inventory snapshot:
- Python files reviewed: **94**
- `#` comment lines matched: **89**
- Triple-quoted docstring lines matched: **34**

Rubric:
- **Neutral tone**: avoids internal/team-local phrasing and editorial language.
- **External-reader clarity**: understandable without private repo history.
- **Stability**: not stale or contradictory to current behavior.
- **Signal quality**: explains why/constraints rather than obvious what.
- **Public readiness**: avoids migration-era or temporary phrasing without context.

Severity:
- **High**: likely to mislead maintainers/users or create incorrect assumptions.
- **Medium**: non-neutral or unclear comments that degrade OSS readability.
- **Low**: style/noise/consistency issues.

## Findings

| ID | Severity | Current Text Snippet | Location | Issue Type | Suggested Replacement |
|---|---|---|---|---|---|
| CMT-001 | Medium | `# 1. Hidden backing controls (Configuration panel removed from visible UI).` | `sdapp/analysis/ui/layout.py:14` | Migration-era/internal phrasing | Replace with: `# Hidden compatibility controls retained for state synchronization.` |
| CMT-002 | Medium | `# Keep export-range spinboxes for internal state compatibility, but hide them from UI.` | `sdapp/analysis/ui/layout.py:212` | Internal-only context | Replace with: `# Retain hidden export range fields to preserve legacy state bindings.` |
| CMT-003 | Medium | `# Backward-compatible adapters while the rest of the app is migrated.` | `sdapp/analysis/core/project_session.py:480` | Roadmap/migration phrasing | Replace with: `# Compatibility adapters for legacy event-state callers.` |
| CMT-004 | Medium | `# Backward-compatible entry point for tests/callers.` | `sdapp/analysis/core/io.py:149` | Test-internal wording in production code | Replace with: `# Compatibility entry point for callers that still use the file-import path.` |
| CMT-005 | Medium | `# ========================================================================` banners around `Helpers`, `CLEANUP LOGIC`, `PREVIEW RESIZE`, etc. | `sdapp/analysis/app.py:599`, `1294`, `1312`, `1325`, `1362`, `1411`, `1429`, `1501` | Section banner noise / non-idiomatic OSS style | Delete banner blocks and keep concise function-level comments/docstrings only where behavior is non-obvious. |
| CMT-006 | Low | `# State Variables` / `# Display State` / `# Cursor State` / etc. | `sdapp/analysis/app.py:103`, `130`, `135`, `142`, `149`, `153`, `159`, `175`, `187` | Low-signal structural labels | Remove labels that mirror the code directly; keep only comments that explain non-obvious constraints. |
| CMT-007 | Low | Duplicate: `# Analysis interactions are handled in dedicated pop-up windows.` | `sdapp/analysis/app.py:1139`, `1143` | Redundant duplicate comments | Keep a single comment on the first handler, remove the duplicate from the second handler. |
| CMT-008 | Low | `# fall back to app root` | `sdapp/analysis/core/state.py:21` | Style/capitalization inconsistency | Replace with: `# Fall back to app root.` |
| CMT-009 | Low | `# Utils package` | `sdapp/analysis/utils/__init__.py:1` | Placeholder/no-value package comment | Delete comment entirely. |
| CMT-010 | Low | `# Core package` | `sdapp/analysis/core/__init__.py:1` | Placeholder/no-value package comment | Delete comment entirely. |
| CMT-011 | Low | `# UI package` | `sdapp/analysis/ui/__init__.py:1` | Placeholder/no-value package comment | Delete comment entirely. |
| CMT-012 | Medium | `# Method 1: signed-distance sampling of frame q against frame q-1 boundary.` | `sdapp/analysis/core/metrics.py:93` | Partial method context (implies alternatives not documented) | Replace with: `# Compute outward displacement by sampling frame q points against the frame q-1 boundary.` |
| CMT-013 | Medium | `"""Project lifecycle workflow helpers for SDSegmentationApp."""` | `sdapp/analysis/core/project_workflow.py:3` | Product-internal naming in module docstring | Replace with: `"""Project lifecycle workflows for the analysis window."""` |
| CMT-014 | Medium | `"""External mask import orchestration for SDSegmentationApp."""` | `sdapp/analysis/core/mask_import_workflow.py:3` | Product-internal naming in module docstring | Replace with: `"""External mask import workflow for the analysis window."""` |
| CMT-015 | Medium | `"""Owns popup lifecycle entrypoints while sd_gui keeps rendering/math helpers."""` | `sdapp/host/mark_popup_controller.py:8` | Internal module naming (`sd_gui`) and vague ownership wording | Replace with: `"""Manage mark/edit popup lifecycle while delegating rendering to the host UI layer."""` |
| CMT-016 | Low | `# Check for imagecodecs` / `# Check for SAM2` | `sdapp/analysis/app.py:47`, `54` | Minimal/no-context comments near import checks | Replace with: `# Optional dependency checks for runtime capabilities.` |
| CMT-017 | Low | `# MISC` banner | `sdapp/analysis/app.py:1501` | Non-descriptive section label | Delete banner and rely on function names, or rename to a specific behavior-oriented comment where needed. |
| CMT-018 | Low | `# Tool: Points` / `# Row 1: Point Tools` / `# Row 2: Paint Tools & Brush Slider` | `sdapp/analysis/ui/layout.py:107`, `111`, `134` | UI-construction narration (obvious from code) | Delete these comments unless retaining one high-level comment per UI subsection is required. |

## Cross-Cutting Patterns
1. **Migration-era phrasing**
- Comments mentioning migration/compatibility are present but often worded as temporary internal notes.
- Recommended direction: keep compatibility comments, but reframe as stable interface constraints.

2. **Section banner overuse in `analysis/app.py`**
- Repetitive separator blocks reduce readability and increase maintenance noise.
- Recommended direction: remove banner blocks and keep targeted comments only for non-obvious behavior.

3. **Placeholder package comments**
- `__init__.py` comments like `# Core package` and `# UI package` add no explanatory value.
- Recommended direction: remove or replace with meaningful module docstrings only if needed.

4. **Docstrings with internal product naming**
- Several docstrings use internal naming patterns that are less clear to new OSS contributors.
- Recommended direction: normalize to role-based descriptions (host window, analysis window, shared services).

## Quick-Win Fixes (High Value, Low Risk)
1. Remove section banners in `sdapp/analysis/app.py` and keep only behavior-level comments.
2. Rewrite compatibility comments in `project_session.py` and `io.py` to neutral, stable wording.
3. Remove placeholder `__init__.py` comments in `analysis/core`, `analysis/ui`, and `analysis/utils`.
4. Replace migration-era phrasing in `analysis/ui/layout.py` with neutral compatibility language.
5. Consolidate duplicated comments in `analysis/app.py` right-canvas handlers.

## Deferred / Optional Cleanup
- Standardize module docstring style across `sdapp/**` (short role-first sentence).
- Introduce a lightweight comment style guide (when to comment, tone, and examples).
- Add a periodic lint/check script for comment anti-patterns (e.g., placeholder comments, banner blocks).

## Prioritized Remediation Sequence
1. **High-severity items**: none identified in this pass.
2. **Medium-severity items**: CMT-001, CMT-002, CMT-003, CMT-004, CMT-005, CMT-012, CMT-013, CMT-014, CMT-015.
3. **Low-severity cleanup**: CMT-006, CMT-007, CMT-008, CMT-009, CMT-010, CMT-011, CMT-016, CMT-017, CMT-018.

## Tracked Remediation Checklist
- [ ] Reword migration/compatibility comments to neutral wording (CMT-001/002/003/004).
- [ ] Remove or replace section banners in `analysis/app.py` (CMT-005/017).
- [ ] Clean low-signal structural comments (CMT-006/018).
- [ ] Remove placeholder `__init__.py` comments (CMT-009/010/011).
- [ ] Normalize targeted module docstrings (CMT-013/014/015).
- [ ] Re-run a focused comment scan and confirm all Medium findings are resolved.

## Release-Readiness Pass Criteria
Comments are considered open-source ready when:
1. All **Medium** findings are resolved with neutral and externally understandable wording.
2. No comments reference internal migration state without explaining present-day behavior.
3. Placeholder and banner-only comments are removed or replaced with informative alternatives.
4. Spot-check review confirms comments explain constraints/intent, not obvious syntax.
