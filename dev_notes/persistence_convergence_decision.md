# Persistence Convergence Decision

## Selected Path

The project now locks **canonical host `.sdproj`** with a single-stack runtime model:

- Canonical owner: **host `.sdproj`**
- Container model: **one stack + many SD events**
- Analysis bridge: per-event sidecar analysis payloads keyed by `event_id`
- Save path always emits canonical host `.sdproj`

## Guardrails

- Host project files persist explicit ownership metadata:
  - `persistence.owner = "host_sdproj"`
  - `analysis_bridge_mode = "single_stack_analysis_payload_v1"`
- Host rejects unknown persistence owner values when opening canonical host `.sdproj`.

## Canonical Layout

- `manifest.json`
- `stack.json`
- `events.json`
- `analysis_sidecar.json`
- `events/<event_path_segment>/prompts.json`
- `events/<event_path_segment>/masks.npz`
- `events/<event_path_segment>/masks_draft.npz` (optional)
- `events/<event_path_segment>/roi_mask.npz` (optional)
- `global/roi_mask.npz` (optional project-global metrics default ROI)

## Event Id Path Policy

- Logical `event_id` values remain unchanged in app state, UI, and manifest payloads.
- On-disk event directories under `events/` use a deterministic sanitized segment (`event_path_segment`) for cross-platform safety:
  - invalid Windows filename characters are replaced,
  - trailing spaces/dots are removed,
  - reserved DOS basenames are prefixed,
  - collisions are disambiguated deterministically.
