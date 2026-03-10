# Integration Next Steps (Single Execution Checklist)

## Goal
Integrate **SD id tool** (host/browser) with **portable_app** (event-scoped analysis workspace) using the shared seam contract, while keeping both apps stable during transition.

Reference contract:
- [`host_analysis_seam_contract_v1.md`](./host_analysis_seam_contract_v1.md)

## Phase 1: Lock Contract + Validators (Both Repos)

### 1.1 Freeze v1 contract
- Treat `contract_version: 1` as implementation target.
- Do not add/remove required fields without explicit version bump.

### 1.2 Add payload validators
- In **SD tool**: validate outgoing handoff payload before dispatch.
- In **portable_app**: validate incoming handoff payload before opening workspace.
- In **SD tool**: validate incoming sync payload before applying state.

### 1.3 Add contract fixture tests
- Add shared JSON fixtures for:
  - valid handoff
  - valid sync
  - common invalid payloads (`VERSION_MISMATCH`, `STACK_MISMATCH`, etc.)

Acceptance criteria:
- Both apps reject malformed payloads with structured error codes.

## Phase 2: Finish Host Ownership in SD Tool

### 2.1 Complete UI -> service delegation
- Ensure event create/edit/delete/select flows in `sd_gui.py` only call `BrowserController` / services.
- Remove direct event state mutation from GUI methods.

### 2.2 Stabilize host session semantics
- Keep session state in `ProjectSessionService` as source of truth.
- Ensure active event, dirty flag, and stack identity are updated only through service APIs.

### 2.3 Improve frame-source capability reporting
- `SDStackFrameSource` must expose capability flags explicitly in handoff.
- Keep raw frame access mandatory.
- If subtracted/visual are unavailable, report false and rely on analysis fallback.

Acceptance criteria:
- Event table and overlays reflect service state only.
- Handoff payload generated deterministically from selected event + active stack.

## Phase 3: Add Host-Driven Open Path in portable_app

### 3.1 Add host-handoff entrypoint
- New API in `portable_app` for opening workspace from validated handoff payload.
- Must bypass standalone import assumptions where possible.

### 3.2 Bind host-provided frame source + event context
- Open analysis workspace with host `event_id`, `start_idx`, `end_idx`.
- Preserve event identity exactly.

### 3.3 Add sync emitter
- On save/autosave/close, emit v1 sync payload back to host adapter.
- Include IDs: `contract_version`, `session_id`, `stack_id`, `event_id`.

Acceptance criteria:
- `portable_app` can run in host-driven mode without requiring local folder import.
- Sync payload conforms to v1 contract.

## Phase 4: Cross-App Vertical Slice

### 4.1 Implement one end-to-end loop
- SD tool: select event in table.
- Host sends handoff payload.
- portable_app opens that event workspace.
- User edits masks.
- portable_app sends sync payload.
- SD tool applies sync and marks session dirty.

### 4.2 Add smoke/integration harness
- Scripted or manual harness that exercises the full loop and verifies same `event_id` is used end-to-end.

Acceptance criteria:
- Event analysis state roundtrips once with no ID drift and no stack mismatch.

## Phase 5: Persistence Convergence Decision

### 5.1 Short-term decision
Locked path:
- Canonical host ownership of `.sdproj` with multi-SD `sd_sets[]`.
- Set-scoped sidecar analysis payload bridge keyed by `event_id`.

### 5.2 Implement migration guardrails
- Keep compatibility readers for existing `.sdsession` and legacy single-SD `.sdproj`.
- Always save canonical host multi-SD `.sdproj`.

Acceptance criteria:
- One canonical persistence owner is documented and tested.

## Required Tests Before UI Merge

### SD tool
- event catalog CRUD + active event stability
- handoff payload validation and generation
- sync payload apply/reject paths

### portable_app
- open-from-handoff payload
- capability fallback when subtracted/visual unavailable
- sync payload generation correctness

### Cross-app
- selected event -> open analysis -> edit -> sync -> host state updated
- mismatch scenarios rejected with explicit error code

## Operational Notes
- Keep both standalone workflows functioning until host-driven flow is production-ready.
- Do not couple UI merge to persistence migration; finish vertical slice first.
- Keep all new seams versioned and test-backed.

## Immediate Next Task (Recommended)
Implement Phase 1 validators in both apps first. This gives fast failure behavior and prevents debugging invalid payloads during cross-app wiring.
