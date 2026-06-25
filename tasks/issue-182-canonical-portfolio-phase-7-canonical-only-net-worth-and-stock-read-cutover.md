# Issue 182: Canonical portfolio phase 7 - canonical-only net worth and stock read cutover

## Objective
- Cut net worth, stock holdings, platform allocation, geography allocation, and cash views over to canonical-only read services.
- Remove legacy `positions` fallback logic from user-facing dashboard and stock endpoints.
- Preserve current API response shapes unless an additive field is needed for canonical freshness/completeness.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Backfill dependency: [Issue 181](./issue-181-canonical-portfolio-phase-6-legacy-position-backfill-and-parity-audit.md)
- Follow-up retirement: [Issue 183](./issue-183-canonical-portfolio-phase-8-legacy-positions-retirement-and-guardrails.md)

## Current Problem
Phase 3 introduced canonical reads but still merges legacy and canonical facts:

- `_networth_components()` still starts with legacy synthetic position rows.
- `_top_holdings()` still builds a legacy positions CTE.
- `_stock_exposure()` still reads legacy `positions`.
- Cash endpoints still use `positions(asset_class='CASH')`.
- Freshness fields still derive from legacy position snapshot timestamps.

That bridge is correct during migration. It should not be the long-term read architecture.

## Scope

### In Scope
- Introduce focused canonical read services for:
  - net worth components
  - current and snapshot stock exposure
  - top holdings
  - platform allocation
  - geography allocation
  - cash balances and cash deposits
  - snapshot/freshness coverage
- Rewrite dashboard endpoints to use canonical services only.
- Remove dashboard dependency on `_synthetic_position_rows()` and legacy `positions` CTEs.
- Preserve frontend contracts for:
  - Wealth/net worth summary
  - Stock holdings page
  - Cash overview page
  - Platform/geography allocation endpoints
- Update freshness fields to report canonical snapshot coverage, not legacy position coverage.

### Out Of Scope
- Dropping `positions`.
- Rebuilding dividends/performance on canonical ledgers unless required to remove dashboard dependencies.
- New visual redesign.

## Architecture Decisions
- The dashboard should consume a small canonical read API, not hand-written SQL against each fact table in every endpoint.
- NAV-backed accounts use NAV for account totals and position snapshots only for drilldown/allocation detail.
- Non-NAV accounts use position snapshots for holdings valuation.
- Cash reads use canonical account balance snapshots and broker cash snapshots promoted through the canonical cash read abstraction.
- Completeness indicators should stay visible when source data lacks NAV, cash, trades, or cost basis.
- API compatibility is preferred; add fields rather than removing existing fields.

## Acceptance Criteria
- [ ] `/dashboard/summary` and `/dashboard/fast-summary` do not read legacy `positions`.
- [ ] `/dashboard/stock-holdings` does not read legacy `positions`.
- [ ] `/dashboard/stock-exposure`, `/dashboard/platform-allocation`, and `/dashboard/geography-exposure` do not read legacy `positions`.
- [ ] `/dashboard/cash-deposits` does not read legacy `positions(asset_class='CASH')`.
- [ ] Net worth totals match the Issue 181 parity report within defined tolerances.
- [ ] Stock page top holdings, geography, platform breakdowns, and trend match canonical facts.
- [ ] Freshness fields reflect canonical report/snapshot dates.
- [ ] Frontend typecheck and route tests pass without API contract regressions.
- [ ] Legacy read helpers are deleted or made test-only where possible.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add canonical read service functions with clear return shapes.
- [ ] Replace net worth component reads.
- [ ] Replace stock holdings and stock exposure reads.
- [ ] Replace cash balance/deposit reads.
- [ ] Replace freshness/as-of logic.
- [ ] Update backend tests from legacy fixtures to canonical fixtures.
- [ ] Update frontend types/tests only if additive response fields are exposed.
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
- Workflow Status: `blocked-on-issue-181`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-25T00:00:00Z`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created to finish the user-facing canonical-only read cutover for net worth, stock, allocation, and cash pages.
