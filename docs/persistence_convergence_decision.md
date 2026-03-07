# Persistence Convergence Decision

## Selected Path (Phase 5)

The project now locks **canonical host `.sdproj`** with multi-SD sets:

- Canonical owner: **host `.sdproj`**
- Container model: **`sd_sets[]` in one project archive**
- Analysis bridge: **set-scoped sidecar analysis payloads** keyed by `event_id` inside each `sd_set`
- Legacy `.sdsession` and legacy single-SD `.sdproj` are accepted as read-only migration inputs

## Guardrails

- Host project files persist explicit ownership metadata:
  - `persistence.owner = "host_sdproj"`
  - `analysis_bridge_mode = "set_scoped_analysis_payload_v1"`
- Host rejects unknown persistence owner values when opening canonical host `.sdproj`.
- Legacy `.sdsession` files are normalized to one default `sd_set` during import.

## Migration Note

Legacy formats are migrated in-memory and then saved as canonical multi-SD `.sdproj`.
Current sidecar storage remains opaque to keep the bridge transport-agnostic.
