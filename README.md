# SDApp Unified Workspace

Unified multi-window SD identification and analysis application.

## Run

```bash
python -m sdapp.main
```

Or on macOS:

```bash
./run_mac.command
```

## Repository Layout

- `sdapp/`: canonical application package (host, analysis, shared services/contracts/persistence).
- `tests/`: unified host/analysis/shared/integration/migration tests.
- `docs/`: current architecture and decision docs.
- `seam_contract_fixtures/`: shared v1 seam contract fixtures used by validators/tests.
- `archive/legacy-integration/`: historical refactor notes and pre-cutover integration docs.

## Dependencies

- `pyproject.toml` is the single source of truth for dependencies.
