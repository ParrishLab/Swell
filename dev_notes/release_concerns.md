# Pre-release concerns

Issues identified before open-source release alongside the manuscript. Ordered by priority.

---

## Release-blockers

### 1. Silent metric export failures
**File:** `swell/host/exporter.py:835-847, 870-882`

Mask generation and analysis image export are wrapped in bare `except Exception:` blocks with no logging or user notification. If SAM-2 output is corrupted or a mask resolves to `None`, the CSV export still completes with invalid or empty values. A user reproducing the manuscript methods could publish wrong numbers without knowing.

**Fix:** surface failures as user-facing error dialogs and log the exception; do not allow export to silently succeed with degraded data.

---

### 2. Silent inference failures
**File:** `swell/analysis/core/inference_manager.py:115, 150`

Multiple critical paths return `0` or `None` on any `Exception` — including GPU OOM, model initialization failure, and corrupted frame data — without logging context. Propagation appears to succeed from the user's perspective but may have produced nothing.

**Fix:** log exceptions with context, surface a dialog when propagation fails, and distinguish "no mask found" from "inference error."

---

### 3. No metrics preview in the analysis window
**Files:** `swell/analysis/ui/layout.py`, `swell/analysis/core/metrics.py`

Metrics (velocity, area, ROI values) are computed and written to CSV during host export, but there is no way to view or validate them inside the analysis window before committing. Users must export and open a spreadsheet externally to verify correctness. For a methods paper this will be a reviewer question.

**Fix:** add a read-only metrics summary panel or status display in the analysis window showing computed values for the active event.

---

## Major gaps

### 4. `NotImplementedError` in frame source
**File:** `swell/analysis/core/frame_source.py:101-106`

Subtracted frames and visualization frames raise `NotImplementedError` at runtime with the message "Subtracted frame source is not wired in host seam prep." If any UI path reaches these code paths, the app crashes.

**Fix:** either implement the feature or guard the entry points with a clear not-yet-available message so the crash cannot be reached from the UI.

---

### 5. No project file validation on load
**File:** `swell/shared/persistence/unified_project_store.py` (`_coerce_stack_ref`, `_coerce_events`)

Corrupt or version-mismatched `.sdproj` files are silently coerced: invalid stack references become `None`, bad event indices become empty lists. The load succeeds with degraded state and no warning dialog.

**Fix:** validate on load and show a recoverable warning dialog when the project file is malformed or partially unreadable.

---

### 6. Silent RGB → grayscale conversion
**File:** `swell/host/stack_reader.py`

Multi-channel (RGB/RGBA) images are mean-averaged to grayscale with no warning or user control. If a user loads RGB microscopy with intentional channel information, that data is lost silently.

**Fix:** detect multi-channel input and prompt the user to choose a channel or confirm the averaging behavior.

---

## Test gaps

These don't block release but affect reproducibility credibility:

- No round-trip integration test: mark event → run propagation → export CSV → reload and verify metric values.
- Exporter error paths (mask generation failure, I/O error, NaN handling) are untested.
- `inference_manager.py` propagation logic and cache coherency are minimally covered.
- `metrics.py` has no tests for edge cases (zero-area ROI, single-frame event, missing scale).
