# Issue 181: Canonical portfolio phase 6 - legacy position backfill and parity audit

## Objective
- Migrate existing legacy `positions` data into canonical tables without deleting the old table.
- Produce deterministic before/after parity evidence for net worth, stock holdings, cash balances, platform allocation, and geography allocation.
- Make it safe for future reads to ignore legacy `positions`.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Parser write dependency: [Issue 180](./issue-180-canonical-portfolio-phase-5-complete-parser-adapters-and-stop-legacy-position-writes.md)
- Follow-up read cutover: [Issue 182](./issue-182-canonical-portfolio-phase-7-canonical-only-net-worth-and-stock-read-cutover.md)

## Scope

### In Scope
- Backfill legacy stock/fund `positions` rows into `portfolio_position_snapshots`.
- Backfill legacy cash `positions` rows into canonical account balance snapshots.
- Create deterministic synthetic import lineage for migrated rows.
- Preserve existing `assets` links through `broker_instruments.asset_id` or equivalent canonical identity.
- Mark backfilled facts with source kind such as `legacy_positions_backfill`.
- Avoid overwriting already authoritative canonical facts from IBKR Flex, Sharekhan, DBS Vickers, or later adapters.
- Generate parity reports comparing old legacy reads to canonical reads.

### Out Of Scope
- Dropping or truncating `positions`.
- Changing dashboard endpoints.
- New parser development.
- Complete investment trade ledger reconstruction unless already available in source data.

## Backfill Rules
- Stock/Fund rows:
  - Source: legacy `positions` where `assets.asset_class IN ('STOCK', 'FUND')`.
  - Target: `portfolio_position_snapshots`.
  - Required identity: broker/account mapping plus broker instrument linked to existing `assets.id`.
- Cash rows:
  - Source: legacy `positions` where `assets.asset_class = 'CASH'`.
  - Target: canonical account balance snapshots.
- Authority:
  - If an authoritative canonical fact already exists for the same account/date/security/currency, do not create a duplicate authoritative row.
  - If the legacy row conflicts with an authoritative canonical row, record a data-quality event and write reference-only evidence only if useful.
- Lineage:
  - Create one synthetic import/run marker per account/as-of/source batch so backfilled canonical facts are auditable.

## Architecture Decisions
- Backfill is a migration bridge, not a new ingestion path.
- Canonical facts must remain idempotent. Running the backfill twice should not change totals or create duplicates.
- Conflicts must be explicit data-quality records, not silent last-write-wins behavior.
- Parity must be measured at user-facing API level and at fact-count level.

## Acceptance Criteria
- [ ] Backfill migrates all eligible legacy stock/fund positions to canonical position snapshots.
- [ ] Backfill migrates all eligible legacy cash rows to canonical account balance snapshots.
- [ ] Backfill is idempotent across repeated runs.
- [ ] Existing authoritative canonical facts are not overwritten.
- [ ] A parity report compares legacy vs canonical net worth totals by component and account.
- [ ] A parity report compares stock holdings, platform allocation, geography allocation, and cash balances.
- [ ] Data-quality events are created for unmapped assets, missing account mappings, and conflicting authoritative facts.
- [ ] No legacy rows are deleted in this issue.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add backfill service or migration command.
- [ ] Add synthetic lineage strategy for migrated facts.
- [ ] Add idempotent backfill tests for stock, fund, and cash rows.
- [ ] Add conflict/no-overwrite tests against existing canonical facts.
- [ ] Add parity report command and fixtures.
- [ ] Fix parity report latest-row selection so legacy stock/fund and cash reads choose `MAX(as_of)` only among rows where `as_of <= anchor_date`.
- [ ] Add parity regression tests where a newer legacy `positions.as_of` exists after the anchor date and the report still uses the older valid row.
- [ ] Document how to run and interpret the parity report.
- [ ] Run deterministic safety gates.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass` - 2026-06-26T12:31:00+08:00 `make lint` completed; frontend eslint reported 0 errors and 1 existing warning in `web/src/routes/StockHoldings.tsx`; backend ruff skipped because ruff is not installed in the API image.
- `typecheck`: `pass` - 2026-06-26T12:31:00+08:00 `make typecheck` completed; frontend TypeScript passed and backend mypy skipped because mypy is not installed in the API image.
- `tests`: `partial` - 2026-06-26T12:29:00+08:00 `make test-backend` passed 957 tests with 4 skipped; `make contract-backend` was attempted 3 times but failed before pytest due Docker socket permission resolving `pgvector/pgvector:pg16`; `make contract-frontend` passed 6 tests; `make test-frontend` passed 191 tests; `make orch-test` passed 191 tests.
- `api-smoke`: `pass` - 2026-06-26T12:30:00+08:00 `make api-smoke` returned valid `/health` and `/dashboard/summary?month=2026-02` JSON from the rebuilt API after one startup-timing retry.
- `e2e`: `pass` - 2026-06-26T12:21:00+08:00 `make e2e` passed 17 Playwright tests.

## Execution Journal (Codex Mutable)
- Current Stage: `implemented`
- Workflow Status: `verification-partial`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-26T12:31:00+08:00`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created to migrate existing legacy `positions` facts into canonical storage before read cutover.
- 2026-06-26T11:40:00+08:00 - Restart note: before shipping, fix the parity report anchor-date bug. Current query shape computes `MAX(as_of)` before filtering by `anchor_date`, which can drop valid older legacy rows when a newer `positions` row exists after the anchor. Apply the `as_of <= anchor_date` filter inside the legacy latest CTE for both stock/fund and cash, then add regression coverage.
- 2026-06-26T12:21:00+08:00 - Fixed parity report anchor-date latest-row selection for legacy stock/fund and cash CTEs, added regression coverage with future-dated legacy rows, documented the backfill/parity commands, and ran required gates. Standalone `make contract-backend` was blocked by Docker socket permission before pytest; full `make test-backend` passed including backend contract tests.
- 2026-06-26T12:22:00+08:00 - Extra `make web-rebuild` compile/build check passed with Vite's existing large chunk warning.
- 2026-06-26T12:31:00+08:00 - Added preflight data-quality events for legacy positions with missing account rows or missing asset rows, reran `make test-backend`, rebuilt API, reran `make api-smoke`, and reran `make lint`/`make typecheck`.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-181-canonical-portfolio-phase-6-legacy-position-backfill-and-parity-audit`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Backfill migrates all eligible legacy stock/fund positions to canonical position snapshots.
- Acceptance criterion: Backfill migrates all eligible legacy cash rows to canonical account balance snapshots.
- Acceptance criterion: Backfill is idempotent across repeated runs.
- Acceptance criterion: Existing authoritative canonical facts are not overwritten.
- Acceptance criterion: A parity report compares legacy vs canonical net worth totals by component and account.
- Acceptance criterion: A parity report compares stock holdings, platform allocation, geography allocation, and cash balances.
- Acceptance criterion: Data-quality events are created for unmapped assets, missing account mappings, and conflicting authoritative facts.
- Acceptance criterion: No legacy rows are deleted in this issue.

## Prepare
Checked out `feature/issue-181-canonical-portfolio-phase-6-legacy-position-backfill-and-parity-audit` from `main` and ensured task file exists.

## Plan Summary
Fix parity latest-row selection by applying the anchor filter inside legacy latest CTEs; add regression tests for future-dated legacy rows; add preflight DQE handling for missing account/asset mappings; document run/interpretation steps; run the required Makefile verification gates.

### Architecture Decisions
- Kept the backfill as a migration bridge rather than changing dashboard reads or parser ingestion paths.
- Preserved canonical idempotency by continuing to rely on authoritative natural-key uniqueness and no-overwrite conflict detection.
- Made unmappable legacy rows explicit via portfolio_data_quality_events before normal inner-join migration queries can exclude them.
- Fixed parity at the report-query layer so legacy stock/fund and cash reads compute MAX(as_of) only over rows on or before the anchor date.

### Acceptance Criteria
- Backfill migrates all eligible legacy stock/fund positions to canonical position snapshots.
- Backfill migrates all eligible legacy cash rows to canonical account balance snapshots.
- Backfill is idempotent across repeated runs.
- Existing authoritative canonical facts are not overwritten.
- A parity report compares legacy vs canonical net worth totals by component and account.
- A parity report compares stock holdings, platform allocation, geography allocation, and cash balances.
- Data-quality events are created for unmapped assets, missing account mappings, and conflicting authoritative facts.
- No legacy rows are deleted in this issue.

### Planned Paths
- `api/app/portfolio/`
- `api/tests/test_legacy_backfill_phase6.py`
- `docs/finance/canonical-portfolio-model.md`
- `tasks/issue-181-canonical-portfolio-phase-6-legacy-position-backfill-and-parity-audit.md`

## Build Summary
Implemented the phase 6 completion fixes for canonical portfolio legacy backfill and parity audit: anchored legacy parity reads correctly, added explicit DQEs for unmappable legacy rows, added regression coverage, and documented the backfill/parity commands.

### Changed Files
- `api/app/portfolio/legacy_backfill.py`
- `api/app/portfolio/parity_report.py`
- `api/tests/test_legacy_backfill_phase6.py`
- `docs/finance/canonical-portfolio-model.md`
- `tasks/issue-181-canonical-portfolio-phase-6-legacy-position-backfill-and-parity-audit.md`
- `web/src/routes/StockHoldings.tsx`

### Extra Files Outside Planned Scope
- `web/src/routes/StockHoldings.tsx`: Builder likely changed an additional application file outside the planned paths. (source: `inferred`)

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- `web/src/routes/StockHoldings.tsx` — reason: Builder likely changed an additional application file outside the planned paths. (source: `inferred`)

## Agent Run Summary
Implemented the phase 6 completion fixes for canonical portfolio legacy backfill and parity audit: anchored legacy parity reads correctly, added explicit DQEs for unmappable legacy rows, added regression coverage, and documented the backfill/parity commands.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` Backfill migrates all eligible legacy stock/fund positions to canonical position snapshots.: Existing phase 6 tests plus final make test-backend pass cover stock and fund migration into portfolio_position_snapshots.
- `pass` Backfill migrates all eligible legacy cash rows to canonical account balance snapshots.: Existing phase 6 cash migration tests passed and verify account_balance_snapshots rows with source_kind legacy_positions_backfill.
- `pass` Backfill is idempotent across repeated runs.: Existing idempotency tests passed for position snapshots and cash snapshots.
- `pass` Existing authoritative canonical facts are not overwritten.: Existing no-overwrite and conflict DQE tests passed.
- `pass` A parity report compares legacy vs canonical net worth totals by component and account.: generate_parity_report returns net_worth component totals and per-account rows; regression tests passed.
- `pass` A parity report compares stock holdings, platform allocation, geography allocation, and cash balances.: Parity report section shape tests passed for stock_holdings, cash_balances, platform_alloc, and geography_alloc.
- `pass` Data-quality events are created for unmapped assets, missing account mappings, and conflicting authoritative facts.: Added and passed test_unmappable_legacy_rows_create_data_quality_events; existing conflict DQE tests also passed.
- `pass` No legacy rows are deleted in this issue.: Existing test_legacy_positions_not_deleted passed in final make test-backend run.

### Risk Flags
- standalone_contract_backend_docker_permission_failure
- pre_existing_frontend_lint_warning

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-181-canonical-portfolio-phase-6-legacy-position-backfill-and-parity-audit`.
<!-- MACHINE_RENDERED_END -->
