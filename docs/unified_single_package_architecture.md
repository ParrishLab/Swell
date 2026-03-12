# Unified Single-Package Architecture

## Canonical Runtime

- Entry point: `python -m sdapp.main`
- Root window: host SD browser
- Child windows: analysis windows (`Toplevel`) managed by shared window manager

## Canonical Package Layout

```text
sdapp/
  host/
  analysis/
  shared/
tests/
```

## Canonical State + Persistence

- `sdapp/shared/services/unified_project_service.py` is the in-memory source of truth.
- `sdapp/shared/persistence/unified_project_store.py` is the canonical `.sdproj` reader/writer.
- Shared contract/menu modules live under `sdapp/shared/contracts` and `sdapp/shared/menu`.

## Compatibility Layers

- Seam-contract compatibility is preserved through `sdapp/shared/contracts/seam_contract.py`.
- Deprecated top-level wrapper modules (`seam_contract.py`, `shared_menu.py`) are removed.
- Deprecated adapter aliases under `sdapp/host` and `sdapp/analysis` are removed.
