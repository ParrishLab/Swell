# Log Message Consistency Audit

This audit focuses on **written log messages** (host + analysis) and highlights wording/format inconsistencies with suggested fixes.

No log strings were changed in this pass.

## Suggested Logging Baseline

- Use one spelling variant globally: `canceled` (US) or `cancelled` (UK), not both.
- Use a consistent lifecycle grammar:
  - `<Action> started`
  - `<Action> completed`
  - `<Action> failed: <reason>`
  - `<Action> canceled: <reason>`
- Keep context in the log context field (`[Project]`, `[Import]`, etc.), and avoid repeating context words in message bodies unless needed.
- Avoid low-signal click telemetry in normal user logs (`"X clicked."`) unless debug mode only.

## Inconsistencies and Suggested Fixes

| ID | Current Message(s) | Location(s) | Inconsistency | Suggested Fix |
|---|---|---|---|---|
| 1 | `canceled` in user logs vs `cancelled` / `save_cancelled` reason codes | `swell/host/event_gui.py:303`, `swell/host/controllers/project_lifecycle_controller.py:295`, `:304`, `swell/analysis/controllers/window_controller.py:207` | Mixed US/UK spelling across related flows. | Standardize on one spelling everywhere (recommended: `canceled`). |
| 2 | `Input browse clicked.`, `Output browse clicked.`, `Export Selected clicked.`, `Export All clicked.` | `swell/host/event_gui.py:297`, `:306`, `:1776`, `:1790` | Click-level logs are verbose/noisy compared with outcome-oriented logs. | Replace with outcome logs only (started/completed/canceled/failed), or move click logs to debug level. |
| 3 | `Load Stack clicked.` + `Started loading stack from: ...` + `Load complete: ...` | `swell/host/controllers/project_lifecycle_controller.py:314`, `:325`, `:363` | Mixed event styles for same operation. | Normalize to lifecycle template: `Stack load started: ...`, `Stack load completed: ...`, `Stack load failed: ...`. |
| 4 | `Analyze SD canceled from options dialog.` | `swell/host/controllers/analysis_launch_controller.py:161` | Uses `Analyze SD` wording while nearby UI/actions also use `Open Analysis`. | Match canonical UI verb, e.g. `Open Analysis canceled from options dialog.` |
| 5 | `Direct host metrics update failed: ...` vs `Direct host update failed: ...` | `swell/analysis/controllers/window_controller.py:107`, `swell/analysis/controllers/host_mode_controller.py:43` | Same failure concept worded two different ways. | Pick one phrase, e.g. `Direct host update failed: ...`; use metrics-specific variant only when strictly needed. |
| 6 | `Save Current Masks canceled by user (overwrite declined).` | `swell/analysis/controllers/window_controller.py:207` | Action label casing in log body (`Save Current Masks`) differs from sentence-style logs elsewhere. | Use sentence-case body: `Save current masks canceled by user (overwrite declined).` |
| 7 | `Undo: <type>`, `Redo: <type>` under `[Undo]` context | `swell/analysis/core/undo.py:25`, `:36` | Body repeats context semantics redundantly. | Use concise action-only body: `Applied action: <type>` / `Reapplied action: <type>`, or keep `Undo`/`Redo` in context and body without prefix. |
| 8 | `Propagation complete` (log) vs `Propagation Complete` (runtime status text checks) | `swell/analysis/core/propagation_progress.py:98`, `swell/analysis/app.py:665`, `swell/analysis/core/inference_manager.py:542` | Capitalization differs between related status channels. | Standardize status phrases across logs and status UI (recommended sentence case in logs, explicit enum mapping for UI labels). |
| 9 | Mixed punctuation style in host logs (many end with `.`, some colon chains, some none) | Examples: `swell/host/event_gui.py:1854`, `swell/host/controllers/project_lifecycle_controller.py:325`, `swell/host/event_gui.py:1786` | Formatting feels inconsistent in the log feed. | Adopt one convention for message body punctuation (recommended: no trailing period for single-line status logs, keep colon only before structured detail). |
| 10 | `Export canceled from options dialog.` logged in both selected/all export flows | `swell/host/event_gui.py:1784`, `:1798` | Same message is ambiguous about scope (`selected` vs `all`). | Include scope for clarity: `Export (selected) canceled from options dialog.` / `Export (all) canceled from options dialog.` |
| 11 | `Load warmup skipped: ...` and similar `skipped` logs used for both expected and exceptional paths | `swell/host/controllers/project_lifecycle_controller.py:386`, plus similar patterns in analysis manager logs | `skipped` may hide severity differences. | Reserve `skipped` for expected branch decisions; use `failed` when operation attempted and errored. |
| 12 | Raw exception-only project errors (`log_error("Project", str(exc))`) | `swell/analysis/controllers/window_controller.py:194`, `:212` | Missing operation context makes triage harder. | Include operation name: `Save current masks failed: <exc>` and keep context tag as `[Project]`. |

## Recommended Next Pass (No Code Yet)

1. Define one shared log style guide in docs (spelling, lifecycle verbs, punctuation, severity mapping).
2. Normalize high-visibility flows first: stack load, export, project save/open, host sync, propagation.
3. Re-run a string scan to catch remaining drift after first cleanup.

