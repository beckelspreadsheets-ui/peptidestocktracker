Read `AGENTS.md`, `PRD.md`, and every file in `docs/` before coding.

Implement Milestone 1 only.

Goal: Bootstrap the Peptide Stock Tracker repo into a working Python project.

Tasks:
1. Create/validate a Python 3.12 package under `src/peptide_watch`.
2. Validate `pyproject.toml`.
3. Implement YAML config loading for `config/peptides.yaml`, `config/companies.yaml`, `config/sources.yaml`, `config/queries.yaml`, and `config/alert_rules.yaml`.
4. Implement SQLite database initialization from `schema/schema.sql`.
5. Add a Typer CLI command: `peptide-watch init-db --db data/watch.db`.
6. Add tests for config loading and database initialization.
7. Do not implement external source adapters yet.
8. Do not add trading recommendations.
9. Do not use private/non-public data.
10. Preserve all external research claims as `needs_verification` until confirmed by primary sources.

Definition of done:
- `pytest` passes.
- `peptide-watch init-db --db data/watch.db` creates a working SQLite database.
- README has local setup/run instructions.
- Provide a summary of files changed and next milestone.
