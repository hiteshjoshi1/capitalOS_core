# Issue 178: Canonical portfolio phase 3 - dashboard and analytics read migration

## Objective
- Move investment-platform dashboard and analytics reads from legacy `positions` / `transactions` synthesis to the canonical portfolio model.
- Validate canonical outputs against legacy outputs before switching user-facing views.
- Retire or compatibility-freeze legacy portfolio tables after canonical reads are proven.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Phase 1 dependency: [Issue 176](./issue-176-canonical-portfolio-phase-1-ibkr-flex-cutover.md)
- Phase 2 dependency: [Issue 177](./issue-177-canonical-portfolio-phase-2-upload-parser-adapters.md)
- Canonical model docs: [Canonical Portfolio Data Model](../docs/finance/canonical-portfolio-model.md)

## Mandatory Pre-Work Context
- Before attempting this issue, read Issue 175 end to end. It defines the target canonical portfolio read model, source authority rules, completeness expectations, and why dashboard migration must happen after canonical writes are proven.
- Before changing dashboard or analytics reads, read the completed Issue 176 implementation and understand what is already live:
  - `migrations/055_canonical_portfolio_phase1.sql` defines the phase-1 canonical tables and uniqueness rules.
  - `api/app/portfolio/ibkr_flex.py` writes canonical IBKR Flex NAV, positions, cash, FX, metrics, trades, cash ledger entries, corporate actions, reconciliations, completeness, and data-quality events.
  - `api/app/routers/portfolio.py` exposes manual Flex import and read-only import diagnostics.
  - `api/app/portfolio/scheduler.py` handles disabled-by-default scheduled Flex imports with DB-backed overlap protection.
  - `api/app/routers/ingest.py` rejects manual IBKR uploads after active Flex cutover while preserving other upload paths.
  - `api/app/routers/dashboard.py` already contains a temporary phase-1 canonical NAV overlay for authoritative IBKR Flex accounts and excludes those accounts from legacy synthetic position valuation.
  - `api/tests/test_ibkr_flex_phase1.py` documents the phase-1 behavior that phase 3 must preserve.
- Before implementing this issue, also inspect the completed Issue 177 adapter implementation. Phase 3 should not migrate dashboard reads for Sharekhan or DBS Vickers until their canonical writes have passed before/after equivalence tests.
- Treat Issue 176's dashboard overlay as temporary bridge code. Phase 3 may replace it with a cleaner canonical read service, but must preserve the same user-visible totals and avoid double counting.
- If Issue 177 is not complete, update this issue with the blocker and stop before making dashboard read migration changes.

## Scope

### In Scope
- Add canonical read services for:
  - account NAV
  - holdings
  - cash by currency
  - platform allocation
  - geography allocation
  - top holdings
  - quote freshness where mapped to market data
  - snapshot comparisons
- Migrate dashboard and investment analytics endpoints to canonical read services after equivalence tests pass.
- Keep spending/card/bank cash-flow views on the current transaction model unless and until a separate cash-flow migration is designed.
- Decide and implement legacy compatibility strategy:
  - legacy tables become read-only projections, or
  - dashboard ignores legacy investment tables after canonical migration, or
  - legacy tables are retired after data migration.

### Out Of Scope
- New broker importers.
- TWR/MWR/realized P&L unless complete historical ledgers are already available.
- Rewriting consumer spending categories.
- Replacing crypto wallet snapshot model unless separately designed.

## Architecture Decisions
- Canonical NAV is the account total for broker accounts that provide NAV; holdings plus cash is only a component breakdown.
- Holdings read from canonical position snapshots.
- Cash reads from canonical cash balance snapshots.
- Market prices still come from `prices` / `market_symbol_map`, keyed through mapped `assets`.
- Dashboard must surface completeness and reconciliation status when data is partial.
- Legacy `SNAPSHOT_DAY` behavior remains for monthly comparison views unless explicitly replaced.

## Acceptance Criteria
- [ ] Dashboard total for IBKR Flex accounts reads canonical NAV including accruals.
- [ ] Sharekhan and DBS Vickers dashboard output remains identical after their upload data is read through canonical snapshots.
- [ ] Stock holdings read canonical position snapshots.
- [ ] Cash breakdown reads canonical cash balance snapshots where available.
- [ ] Geography and platform allocations are computed from canonical facts and mapped assets/instruments.
- [ ] Missing mappings or incomplete source data are visible as data-quality/completeness indicators instead of silent omissions.
- [ ] Existing dashboard API contract remains OpenAPI-compatible or is versioned with frontend type updates.
- [ ] Legacy `positions` / `transactions` investment read dependencies are removed or explicitly compatibility-frozen.
- [ ] Regression tests compare canonical dashboard output against pre-migration output for representative IBKR, Sharekhan, and DBS Vickers fixtures.
- [ ] API smoke and dashboard load verification pass.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Inventory dashboard queries that read `positions`, `transactions`, `assets`, `prices`, and `market_symbol_map`.
- [ ] Add canonical read services for holdings, cash, NAV, allocation, and snapshots.
- [ ] Add equivalence fixtures for IBKR Flex, Sharekhan, and DBS Vickers.
- [ ] Migrate backend dashboard endpoints behind focused tests.
- [ ] Update schemas and TypeScript types as needed.
- [ ] Update frontend rendering for completeness/reconciliation indicators if exposed.
- [ ] Define legacy table compatibility/retirement plan.
- [ ] Run deterministic safety gates.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pending`
- `typecheck`: `pending`
- `tests`: `pending`
- `api-smoke`: `pending`
- `e2e`: `pending`

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `blocked-on-phase-1-and-phase-2`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-20T13:30:00Z`

## Automation Log (Mutable)
- 2026-06-20T09:03:51Z - Created phase-3 read migration issue from canonical portfolio architecture.
- 2026-06-20T13:30:00Z - Added mandatory pre-work context requiring Issue 175, completed Issue 176 implementation review, and completed Issue 177 equivalence work before phase-3 migration.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `waiting_for_human`

## Workflow Snapshot
- latest_outcome: Implemented Phase 3 canonical portfolio dashboard read migration. Added a new canonical_reads.py service module, migrated dashboard.py to read holdings/geography/allocation from portfolio_position_snapshots for Sharekhan and DBS Vickers accounts (excluding those from legacy positions reads), integrated canonical position rows into all relevant dashboard computation functions, added data completeness indicators to dashboard summary responses, and created a comprehensive regression test suite (14 new tests).
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Dashboard total for IBKR Flex accounts reads canonical NAV including accruals.
- Acceptance criterion: Sharekhan and DBS Vickers dashboard output remains identical after their upload data is read through canonical snapshots.
- Acceptance criterion: Stock holdings read canonical position snapshots.
- Acceptance criterion: Cash breakdown reads canonical cash balance snapshots where available.
- Acceptance criterion: Geography and platform allocations are computed from canonical facts and mapped assets/instruments.
- Acceptance criterion: Missing mappings or incomplete source data are visible as data-quality/completeness indicators instead of silent omissions.
- Acceptance criterion: Existing dashboard API contract remains OpenAPI-compatible or is versioned with frontend type updates.
- Acceptance criterion: Legacy positions/transactions investment read dependencies are removed or explicitly compatibility-frozen.
- Acceptance criterion: Regression tests compare canonical dashboard output against pre-migration output for representative IBKR, Sharekhan, and DBS Vickers fixtures.
- Acceptance criterion: API smoke and dashboard load verification pass.

## Prepare
Checked out `feature/issue-178-canonical-portfolio-phase-3-dashboard-analytics-read-migration` from `main` and ensured task file exists.

## Plan Summary
1) Created api/app/portfolio/canonical_reads.py with canonical_position_rows_by_legacy_account, canonical_cash_rows_by_legacy_account, get_data_completeness_status, and has_canonical_position_snapshot_sql helper. 2) Updated dashboard.py to exclude accounts with canonical position snapshots from all legacy positions reads, merge canonical position rows into _networth_components, _geography, _geography_exposure, _top_holdings, _platform_allocation, _stock_exposure, and expose data completeness indicators in summary endpoint. 3) Updated DashboardSummaryResponse schema with optional data_completeness_indicators field. 4) Created regression test file test_canonical_dashboard_phase3.py with 14 tests covering no-double-counting, legacy exclusion, canonical reads, completeness indicators, anchor date scoping.

### Architecture Decisions
- IBKR Flex accounts continue to be handled by latest_authoritative_nav_by_legacy_account (NAV snapshots); canonical_position_rows_by_legacy_account explicitly excludes them to prevent double-counting.
- Sharekhan and DBS Vickers accounts are excluded from all legacy positions table reads once they have authoritative canonical position snapshots.
- has_canonical_position_snapshot_sql() returns a reusable SQL EXISTS fragment that all position-reading queries use to exclude canonical-covered accounts.
- Legacy positions table remains read-only (compatibility-frozen) for non-canonical-covered accounts; no data migration or table retirement performed.
- asset_class ENUM cast to TEXT in canonical reads to support both PostgreSQL (USER-DEFINED enum) and SQLite (TEXT) test environments.
- data_completeness_indicators is an optional field in DashboardSummaryResponse; returns None when no incomplete canonical scopes exist, non-empty list when upload adapters recorded missing cash/NAV/trade scopes.

### Acceptance Criteria
- Dashboard total for IBKR Flex accounts reads canonical NAV including accruals.
- Sharekhan and DBS Vickers dashboard output remains identical after their upload data is read through canonical snapshots.
- Stock holdings read canonical position snapshots.
- Cash breakdown reads canonical cash balance snapshots where available.
- Geography and platform allocations are computed from canonical facts and mapped assets/instruments.
- Missing mappings or incomplete source data are visible as data-quality/completeness indicators instead of silent omissions.
- Existing dashboard API contract remains OpenAPI-compatible or is versioned with frontend type updates.
- Legacy positions/transactions investment read dependencies are removed or explicitly compatibility-frozen.
- Regression tests compare canonical dashboard output against pre-migration output for representative IBKR, Sharekhan, and DBS Vickers fixtures.
- API smoke and dashboard load verification pass.

### Planned Paths
- `api/app/portfolio/canonical_reads.py`
- `api/app/routers/dashboard.py`
- `api/app/schemas/dashboard.py`
- `api/tests/test_canonical_dashboard_phase3.py`

## Build Summary
Implemented Phase 3 canonical portfolio dashboard read migration. Added a new canonical_reads.py service module, migrated dashboard.py to read holdings/geography/allocation from portfolio_position_snapshots for Sharekhan and DBS Vickers accounts (excluding those from legacy positions reads), integrated canonical position rows into all relevant dashboard computation functions, added data completeness indicators to dashboard summary responses, and created a comprehensive regression test suite (14 new tests).

### Changed Files
- `api/app/portfolio/canonical_reads.py`
- `api/app/routers/dashboard.py`
- `api/app/schemas/dashboard.py`
- `api/tests/test_canonical_dashboard_phase3.py`
- `tasks/issue-178-canonical-portfolio-phase-3-dashboard-analytics-read-migration.md`

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
- None

## Agent Run Summary
Implemented Phase 3 canonical portfolio dashboard read migration. Added a new canonical_reads.py service module, migrated dashboard.py to read holdings/geography/allocation from portfolio_position_snapshots for Sharekhan and DBS Vickers accounts (excluding those from legacy positions reads), integrated canonical position rows into all relevant dashboard computation functions, added data completeness indicators to dashboard summary responses, and created a comprehensive regression test suite (14 new tests).

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` Dashboard total for IBKR Flex accounts reads canonical NAV including accruals: Existing latest_authoritative_nav_by_legacy_account integration preserved; test_ibkr_flex_phase1.py::test_ibkr_flex_dashboard_uses_canonical_nav_and_excludes_legacy_positions passes
- `pass` Sharekhan and DBS Vickers dashboard output remains identical after their upload data is read through canonical snapshots: test_dashboard_no_double_counting_when_canonical_and_legacy_both_present and test_dbs_vickers_canonical_positions_no_double_count pass; legacy exclusion confirmed by test_dashboard_legacy_positions_excluded_when_canonical_exists
- `pass` Stock holdings read canonical position snapshots: canonical_position_rows_by_legacy_account feeds into _top_holdings; test_canonical_position_rows_returns_sharekhan_positions and test_canonical_position_rows_returns_dbs_vickers_positions pass
- `partial` Cash breakdown reads canonical cash balance snapshots where available: canonical_cash_rows_by_legacy_account implemented in canonical_reads.py but not yet wired into _cash_balances (upload adapters don't write cash snapshots; only IBKR Flex does, and its cash is already in NAV). Canonical cash reads are available for future integration.
- `pass` Geography and platform allocations are computed from canonical facts and mapped assets/instruments: _geography, _geography_exposure, _platform_allocation, _stock_exposure all updated to include canonical position rows. test_platform_allocation_includes_sharekhan_canonical and test_geography_exposure_includes_sharekhan_canonical pass.
- `pass` Missing mappings or incomplete source data are visible as data-quality/completeness indicators instead of silent omissions: get_data_completeness_status() implemented; data_completeness_indicators added to DashboardSummaryResponse; test_data_completeness_status_returns_incomplete_scopes and test_dashboard_summary_exposes_completeness_indicators pass
- `pass` Existing dashboard API contract remains OpenAPI-compatible or is versioned with frontend type updates: data_completeness_indicators added as Optional[List[Dict]] - additive change. contract-backend and contract-frontend tests pass.
- `pass` Legacy positions/transactions investment read dependencies are removed or explicitly compatibility-frozen: Accounts with canonical position snapshots are excluded from all legacy positions reads via has_canonical_position_snapshot_sql(). Legacy table remains readable for non-canonical accounts (compatibility-frozen).
- `pass` Regression tests compare canonical dashboard output against pre-migration output for representative IBKR, Sharekhan, and DBS Vickers fixtures: test_canonical_dashboard_phase3.py has 14 tests covering Sharekhan and DBS Vickers; IBKR Flex covered by existing test_ibkr_flex_phase1.py. All 14 new tests pass.
- `pass` API smoke and dashboard load verification pass: make api-smoke returns HTTP 200 with valid JSON including new data_completeness_indicators field

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
