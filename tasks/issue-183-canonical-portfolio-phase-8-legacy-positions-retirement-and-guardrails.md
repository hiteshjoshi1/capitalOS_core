# Issue 183: Canonical portfolio phase 8 - legacy positions retirement and guardrails

## Objective
- Retire legacy `positions` after canonical writes, backfill, and read cutover are complete.
- Add guardrails so no new code path can silently reintroduce authoritative `positions` writes.
- Remove obsolete tests and compatibility code only after deterministic proof that canonical reads own the portfolio surface.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Read cutover dependency: [Issue 182](./issue-182-canonical-portfolio-phase-7-canonical-only-net-worth-and-stock-read-cutover.md)

## Scope

### In Scope
- Verify zero production read dependencies on legacy `positions`.
- Verify zero authoritative write dependencies on legacy `positions`.
- Update or remove tests that seed `positions` for dashboard/stock/cash behavior.
- Add a database or application guard that blocks accidental new authoritative writes.
- Decide final table treatment:
  - leave as archived read-only historical table,
  - rename to `legacy_positions_archive`,
  - replace with a compatibility view,
  - or drop in a later explicit destructive migration.
- Update docs and task plans to mark `positions` retired from portfolio truth.

### Out Of Scope
- Historical data backfill; handled by Issue 181.
- Dashboard read migration; handled by Issue 182.
- Deleting user data without an explicit reviewed migration.

## Retirement Order
1. Prove no application reads from `positions`.
2. Prove no application writes to `positions`.
3. Prove canonical parity reports pass.
4. Add write guard or archive rename.
5. Remove obsolete compatibility helpers.
6. Only then consider table deletion in a separate reviewed destructive migration.

## Architecture Decisions
- Deletion is the last operation, not the definition of retirement.
- Retired legacy tables must be impossible to accidentally repopulate as authoritative truth.
- Compatibility views are acceptable only if they are clearly marked as projections and cannot become write targets.
- Dividends, market data, and any secondary analytics must either read canonical facts or explicitly not depend on holdings snapshots.

## Acceptance Criteria
- [ ] `rg "FROM positions|JOIN positions|INSERT INTO positions|UPDATE positions"` finds no production portfolio read/write path except approved migration/archive code.
- [ ] Dashboard, stock, cash, platform, geography, and net worth tests seed canonical facts rather than legacy positions.
- [ ] Dividends and any remaining analytics are migrated or explicitly documented as independent of holdings snapshots.
- [ ] A guard prevents new authoritative writes to `positions`.
- [ ] Legacy compatibility helpers are removed or isolated to archive/migration code.
- [ ] Table deletion is not performed unless an explicit destructive migration is separately approved.
- [ ] Full backend, frontend, smoke, and e2e gates pass.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Inventory all remaining `positions` references.
- [x] Remove production read/write references.
- [x] Rewrite active dashboard, spending, market-data, IBKR, and dividends tests to canonical fixtures; archive/backfill tests remain legacy-specific.
- [x] Add write guard/archive strategy.
- [x] Update documentation and task guidance.
- [x] Convert dummy seed data to canonical portfolio facts and verify seed/clear after guard migration.
- [x] Run deterministic safety gates.
- [ ] Prepare a separate destructive-drop proposal only if still desired after archive mode is stable.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `api-rebuild`: `pass` - API image rebuilt and container restarted.
- `semantic-scan`: `pass` - `rg "FROM positions|JOIN positions|INSERT INTO positions|UPDATE positions"` now finds only approved archive/migration code (`legacy_backfill.py`, `parity_report.py`, migration 057 dummy cleanup) and zero-write guard assertions; active dashboard/spending/market-data seed fixtures no longer write `positions`.
- `db-migrate`: `pass` - migration 057 applied; removed 37 old dummy legacy rows and installed insert/update/delete triggers on `positions`.
- `db-seed-dummy`: `pass` - dummy seed now writes canonical `account_balance_snapshots` and `portfolio_position_snapshots` under the guard.
- `db-clear-dummy`: `pass` - dummy clear completes with `ON_ERROR_STOP=1`.
- `focused-tests`: `pass` - touched dashboard/spending/market-data/IBKR/canonical-dashboard tests passed.
- `test-backend`: `pass` - 967 passed, 4 skipped.
- `api-smoke`: `pass` - `/health` returned `{"status":"ok"}` and `/dashboard/summary?month=2026-02` returned valid JSON.
- `lint`: `pass` - frontend ESLint passed; backend ruff skipped because ruff is not installed in the API image.
- `typecheck`: `pass` - TypeScript build passed; backend mypy skipped because mypy is not installed in the API image.
- `contract-frontend`: `pass` - 6 passed.
- `test-frontend`: `pass` - 191 passed after isolated rerun; an earlier parallel run with e2e had transient AuthContext failures.
- `e2e`: `pass` - 17 passed.
- `orch-test`: `pass` - 191 passed.

## Execution Journal (Codex Mutable)
- Current Stage: `implemented`
- Workflow Status: `ready-for-review`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-30T15:45:00Z`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created to retire legacy `positions` only after canonical writes, backfill, parity, and read cutover are complete.
- 2026-06-30T00:00:00Z - Removed the remaining production legacy positions write fallback, migrated dividend holdings reads to canonical snapshots, added migration 057 read-only trigger guard, and documented archive-in-place retirement.
- 2026-06-30T00:00:00Z - Verification completed except `make contract-backend`, which failed before running pytest due Docker socket permission resolving `pgvector/pgvector:pg16`; full `make test-backend` still passed and includes `tests/test_contracts.py`.
- 2026-06-30T15:45:00Z - Converted remaining active dashboard/spending/market-data/IBKR tests and dummy seed data off legacy positions; verified migration 057, dummy seed/clear, backend suite, frontend tests, lint, typecheck, api-smoke, and e2e.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-183-canonical-portfolio-phase-8-legacy-positions-retirement-and-guardrails`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: No production portfolio read/write path should query or write positions except approved migration/archive code.
- Acceptance criterion: Dashboard, stock, cash, platform, geography, and net worth tests should use canonical facts rather than legacy positions.
- Acceptance criterion: Dividends and remaining analytics should use canonical facts or be documented as independent of holdings snapshots.
- Acceptance criterion: A guard must prevent new authoritative writes to positions.
- Acceptance criterion: Legacy compatibility helpers should be removed or isolated to archive/migration code.
- Acceptance criterion: Table deletion must not be performed without a separate destructive migration.
- Acceptance criterion: Full backend, frontend, smoke, e2e, and orchestration gates should pass.

## Prepare
Checked out `feature/issue-183-canonical-portfolio-phase-8-legacy-positions-retirement-and-guardrails` from `main` and ensured task file exists.

## Plan Summary
Inventory positions references, remove production read/write paths, migrate remaining dividend analytics to canonical reads, add a database write guard, update focused tests/docs/task evidence, then run the required verification suite.

### Architecture Decisions
- Keep positions as an archived read-only historical table instead of dropping or renaming it in this task.
- Use migration 057 to block INSERT, UPDATE, and DELETE on positions via Postgres triggers.
- Allow legacy_backfill.py and parity_report.py to remain the only approved positions readers because they are migration/audit tooling.
- Use canonical_position_rows_by_legacy_account for dividend expected-holdings and yield calculations.

### Acceptance Criteria
- No production portfolio read/write path should query or write positions except approved migration/archive code.
- Dashboard, stock, cash, platform, geography, and net worth tests should use canonical facts rather than legacy positions.
- Dividends and remaining analytics should use canonical facts or be documented as independent of holdings snapshots.
- A guard must prevent new authoritative writes to positions.
- Legacy compatibility helpers should be removed or isolated to archive/migration code.
- Table deletion must not be performed without a separate destructive migration.
- Full backend, frontend, smoke, e2e, and orchestration gates should pass.

### Planned Paths
- `api/app/ingestion/runner.py`
- `api/app/routers/dividends.py`
- `api/tests`
- `migrations`
- `docs/finance/canonical-portfolio-model.md`
- `tasks/issue-183-canonical-portfolio-phase-8-legacy-positions-retirement-and-guardrails.md`

## Build Summary
Implemented legacy positions retirement guardrails: removed the production ingestion fallback that wrote to positions, migrated dividend holding analytics to canonical position snapshots, added a non-destructive read-only trigger migration for positions, updated dividend tests to seed canonical facts, and documented the archive-in-place strategy.

### Changed Files
- `Makefile`
- `api/app/ingestion/runner.py`
- `api/app/routers/dividends.py`
- `api/tests/canonical_test_helpers.py`
- `api/tests/conftest.py`
- `api/tests/test_canonical_dashboard_phase3.py`
- `api/tests/test_dashboard.py`
- `api/tests/test_dividends.py`
- `api/tests/test_ibkr_flex_phase1.py`
- `api/tests/test_market_data.py`
- `api/tests/test_spending.py`
- `docs/finance/canonical-portfolio-model.md`
- `migrations/057_retire_legacy_positions_guard.sql`
- `migrations/seed_dummy.sql`
- `tasks/issue-183-canonical-portfolio-phase-8-legacy-positions-retirement-and-guardrails.md`

### Extra Files Outside Planned Scope
- `Makefile`: Ensure dummy DB seed and clear targets fail fast with ON_ERROR_STOP so SQL errors are not masked during verification. (source: `builder`)

## Latest Verification
- api-rebuild: PASS (exit 0)
- db-migrate: PASS (exit 0)
- db-clear-dummy: PASS (exit 0)
- db-seed-dummy: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)
- diff-check: PASS (exit 0)

## Extra Files Changed
- `Makefile` — reason: Ensure dummy DB seed and clear targets fail fast with ON_ERROR_STOP so SQL errors are not masked during verification. (source: `builder`)

## Agent Run Summary
Implemented legacy positions retirement guardrails: removed the production ingestion fallback that wrote to positions, migrated dividend holding analytics to canonical position snapshots, added a non-destructive read-only trigger migration for positions, updated dividend tests to seed canonical facts, and documented the archive-in-place strategy.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` rg "FROM positions|JOIN positions|INSERT INTO positions|UPDATE positions" finds no production portfolio read/write path except approved migration/archive code.: Production scan only returns api/app/portfolio/legacy_backfill.py and api/app/portfolio/parity_report.py; ingestion runner and dividends no longer match.
- `pass` Dashboard, stock, cash, platform, geography, and net worth tests seed canonical facts rather than legacy positions.: Dashboard, spending, canonical dashboard, market-data, and IBKR tests were converted off legacy positions fixtures and now seed canonical facts.
- `pass` Dividends and any remaining analytics are migrated or explicitly documented as independent of holdings snapshots.: Dividend expected holdings and asset market values now use canonical_position_rows_by_legacy_account; dividend history remains transaction-based.
- `pass` A guard prevents new authoritative writes to positions.: migrations/057_retire_legacy_positions_guard.sql adds insert/update/delete triggers that raise an exception.
- `pass` Legacy compatibility helpers are removed or isolated to archive/migration code.: Production ingestion fallback writes were removed; remaining positions SQL is isolated to legacy_backfill.py and parity_report.py.
- `pass` Table deletion is not performed unless an explicit destructive migration is separately approved.: No drop/rename was added; positions remains as a read-only archive.
- `pass` Full backend, frontend, smoke, and e2e gates pass.: api-rebuild, db-migrate, db-seed-dummy, db-clear-dummy, test-backend, api-smoke, lint, typecheck, contract-frontend, test-frontend, e2e, and orch-test passed; frontend/e2e also passed standalone after a transient long-run workflow timeout.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-183-canonical-portfolio-phase-8-legacy-positions-retirement-and-guardrails`.
<!-- MACHINE_RENDERED_END -->
