# Unified Single-Package Architecture

## Canonical Runtime

- Entry point: `python -m swell.main`
- Root window: host SD browser
- Child windows: analysis windows (`Toplevel`) managed by shared window manager

## Canonical Package Layout

```text
swell/
  main.py
  host/
  analysis/
  shared/
tests/
```

## Canonical State + Persistence

- `swell/shared/services/unified_project_service.py` is the in-memory source of truth.
- `swell/shared/persistence/unified_project_store.py` is the canonical `.sdproj` reader/writer.
- Shared contract/menu modules live under `swell/shared/contracts` and `swell/shared/menu`.
- Canonical project shape is single-stack with project-level events and per-event analysis artifacts.

## Dependency Boundaries

- `shared` may not import from `host` or `analysis`.
- `host` and `analysis` may import from `shared`.
- Cross-window runtime wiring must be done through shared service contracts and callback interfaces, not direct persistence access from UI views.

## Compatibility Layers

- Seam-contract compatibility is preserved through `swell/shared/contracts/seam_contract.py`.
- Deprecated top-level wrapper modules (`seam_contract.py`, `shared_menu.py`) are removed.
