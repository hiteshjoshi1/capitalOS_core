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
