# Issue 158: Data model cleanup (DB guardrails)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/158

## Objective
- Deleting an import run, raw statement or account can no longer take evidence with it or silently unlink it (#130 1.8).
- Enum-like TEXT columns only accept the values the code writes, checked before deploy by a read-only precheck (#130 1.11).
- Migration hygiene is enforced by lint (no BEGIN/COMMIT, no duplicate numbers) and documented (#130 1.11); dead tables get a usage report, not a drop (#130 1.9); the anchor copies (#130 1.10) are accounted for.

## Architecture Decisions
- Migration 079: every FK to `broker_import_runs` (12 fact tables, `raw_broker_documents`, `account_balance_snapshots.broker_import_run_id`), every FK to `raw_broker_documents` (13 tables) and every `legacy_account_id` FK to `accounts` (5 tables) becomes `ON DELETE RESTRICT` (same names; NOT VALID then VALIDATE). Left as is: `broker_account_id` CASCADEs, accounts -> transactions/import_jobs/balances CASCADE, users/crypto/market-data FKs.
- 22 CHECK constraints (authority_status x7, source kinds/types x5, fact scopes x3, completeness status, balance_type, window-change action, run status/import_scope, rollup freshness + month format), `NOT VALID` then `VALIDATE` in the same file. Values come from the code; 'DUMMY' where seed_dummy.sql writes it. Not constrained: broker_accounts/connections `status` (#207 may add a lifecycle value), open-ended reasons/codes.
- Read-only precheck generated from the pending migrations (`api/app/scripts/constraint_precheck.py`, `make db-constraint-check`): rows each pending CHECK would reject, and constraints a pending migration drops by name that aren't there. READ ONLY session (PGOPTIONS) and transaction.
- Dead tables: nothing dropped; `scripts/db-table-usage.py` / `make db-table-usage` reports code usage and row counts.
- Seeds delete dummy canonical rows explicitly (RESTRICT).
- 1.10: #143 made `app/valuation/clock.py` the one anchor rule, #202 made it per-user timezone, `test_first_of_month_dashboard_and_history_agree` is the parity test. The last copy (`runner._snapshot_as_of`, UTC, clamp 28) was dead code with its only caller; removed here.

## Acceptance Criteria
- [x] RESTRICT on facts and raw docs to runs (plus facts to raw docs and legacy accounts), app delete paths tested on Postgres.
- [x] CHECK constraints NOT VALID then VALIDATE; read-only precheck target.
- [x] Lint rejects BEGIN/COMMIT and duplicate prefixes (028 allow-listed); migrations/README.md.
- [x] Dead-table usage report (no drop).
- [x] 1.10 status documented.

## How To Test
- `make lint` (runs `scripts/check-migrations.py` and `scripts/test-check-migrations.sh`).
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_db_guardrails.py -q`.
- `make db-schema-check` (migrate-from-empty, no-op re-run, schema diff, Postgres tests).
- `make db-constraint-check` on a stack before applying 079; `make db-table-usage`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `verify`: see PR description.
- `db-schema-check`: see PR description.

## Extra Files Changed (Codex Mutable)
- `migrations/seed_dummy.sql`, `migrations/seed_dummy_cleanup.sql` — reason: they relied on CASCADE from runs / SET NULL from accounts.
- `api/app/ingestion/runner.py` — reason: dead anchor copy (1.10).
