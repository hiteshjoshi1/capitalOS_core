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
- [ ] Document how to run and interpret the parity report.
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
- Workflow Status: `blocked-on-issue-180`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-25T00:00:00Z`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created to migrate existing legacy `positions` facts into canonical storage before read cutover.
