# Host <-> Analysis Seam Contract (v1)

## Purpose
Define the canonical handoff and sync contract between:
- **Host app** (SD browser, event catalog owner)
- **Analysis app** (`portable_app`, event editor)

This contract is versioned and transport-agnostic. It can be passed in-memory, via IPC, or serialized JSON.

## Versioning
- `contract_version` is required.
- Initial version: `1`.
- Breaking field/behavior changes require version bump.

## Design Rules
- Host owns event identity and event bounds.
- Analysis app never regenerates `event_id`.
- Frame indices are always absolute in host stack coordinates.
- Raw frames are required; subtracted/visual are optional capabilities.

## 1) Handoff Payload (Host -> Analysis)

### 1.1 Required shape
```json
{
  "contract_version": 1,
  "session": {
    "session_id": "string",
    "project_path": "string|null",
    "active_event_id": "string",
    "dirty": true,
    "metadata": {}
  },
  "stack": {
    "stack_id": "string",
    "frame_count": 0,
    "frame_shape": [0, 0],
    "frame_names": [],
    "source_paths": [],
    "capabilities": {
      "raw": true,
      "subtracted": false,
      "visual": false
    }
  },
  "event": {
    "event_id": "string",
    "label": "string",
    "start_idx": 0,
    "end_idx": 0,
    "flags": {}
  },
  "analysis_state_ref": {
    "storage": "host_session",
    "ref_id": "string"
  }
}
```

### 1.2 Field requirements
- `session.session_id`: stable session identity within host runtime.
- `stack.stack_id`: stable identity for currently loaded stack.
- `stack.frame_shape`: `[height, width]`.
- `event.start_idx`, `event.end_idx`: inclusive absolute frame bounds, normalized so `start_idx <= end_idx`.
- `analysis_state_ref`: opaque handle analysis uses when syncing state back.

### 1.3 Capability semantics
- `capabilities.raw`: must be `true`.
- If `subtracted=false`, analysis must derive fallback view from raw or disable related UI features.
- If `visual=false`, analysis must derive display normalization locally.

## 2) Sync Payload (Analysis -> Host)

### 2.1 Required shape
```json
{
  "contract_version": 1,
  "session_id": "string",
  "stack_id": "string",
  "event_id": "string",
  "analysis_state_ref": {
    "storage": "host_session",
    "ref_id": "string"
  },
  "analysis": {
    "masks_committed": {
      "encoding": "npz_uint8_3d",
      "frame_count": 0,
      "shape": [0, 0],
      "blob_ref": "string"
    },
    "masks_draft": null,
    "prompts": {
      "encoding": "portable_prompts_json",
      "blob_ref": "string"
    },
    "propagation_completed": true,
    "analysis_output_dir": null
  },
  "ui_hints": {
    "last_frame": 0,
    "active_tool": "select"
  }
}
```

### 2.2 Sync validation rules
Host must reject sync if any of these fail:
- `contract_version` mismatch.
- `session_id` mismatch with active session.
- `stack_id` mismatch with active stack.
- `event_id` not found in host event catalog.
- mask shape does not match host `frame_shape`.

### 2.3 Conflict policy
- Host event metadata (`label`, `start_idx`, `end_idx`) is canonical from host side.
- Analysis sync updates only analysis payload fields by default.
- If analysis wants to propose bound updates, it must do so via an explicit `event_update_proposal` extension field (not part of v1 required schema).

## 3) Lifetime / Workflow
1. Host selects event and sends handoff payload.
2. Analysis opens event workspace bound to `analysis_state_ref`.
3. Analysis edits and periodically syncs (manual save, autosave, close).
4. Host applies valid sync and marks session dirty.

## 4) Error Contract
When host rejects sync, return structured error:
```json
{
  "ok": false,
  "code": "STACK_MISMATCH",
  "message": "stack_id does not match active host stack"
}
```

Reserved codes:
- `VERSION_MISMATCH`
- `SESSION_MISMATCH`
- `STACK_MISMATCH`
- `EVENT_NOT_FOUND`
- `MASK_SHAPE_MISMATCH`
- `PAYLOAD_INVALID`

## 5) Minimal Compatibility Matrix
- Host provides raw-only frames: supported.
- Host provides raw+visual: supported.
- Host provides raw+subtracted+visual: supported.
- Host switches stack while analysis session is open: analysis syncs must be rejected with `STACK_MISMATCH`.

## 6) Implementation Mapping

### SD tool (host)
- `event_id/start_idx/end_idx/label` from `EventCatalogService`.
- `stack` fields from `SDStackFrameSource` + `StackReader`.
- `session` fields from `ProjectSessionService`.
- `analysis_state_ref` generated and managed by host session layer.

### portable_app (analysis)
- open via payload instead of standalone import path.
- bind frame source adapter provided by host payload.
- use `event_id` as immutable event key for sync.
- send sync payload on save/autosave/close.

## 7) Contract Tests (Both Repos)

### Host tests
- valid handoff payload generation for selected event.
- sync rejection on `session_id/stack_id/event_id` mismatch.
- sync acceptance on valid payload and dirty-state update.

### Analysis tests
- open workspace from handoff payload with raw-only capabilities.
- fallback behavior when `subtracted/visual` are unavailable.
- sync payload includes required IDs and shape metadata.

### Cross-app smoke test
- Create event in host -> open analysis -> edit mask -> sync -> host sees updated analysis state under same `event_id`.

## 8) Defaults for v1
- `analysis_state_ref.storage = "host_session"`
- `ui_hints` optional for host; analysis includes when available.
- `prompts.encoding = "portable_prompts_json"`
- `masks_committed.encoding = "npz_uint8_3d"`

