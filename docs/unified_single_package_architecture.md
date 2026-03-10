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
- `sdapp/shared/persistence/unified_project_store.py` is the canonical multi-SD `.sdproj` reader/writer.
- Legacy readers are preserved for `.sdsession` and legacy single-SD `.sdproj`.

## Compatibility Layers

- `seam_contract.py` and `shared_menu.py` are lightweight wrappers over `sdapp/shared/...`.
- Legacy project formats are read through migration loaders in `sdapp/shared/persistence`.
