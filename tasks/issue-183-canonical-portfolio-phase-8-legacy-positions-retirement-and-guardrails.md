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
- [ ] Inventory all remaining `positions` references.
- [ ] Remove production read/write references.
- [ ] Rewrite tests to canonical fixtures.
- [ ] Add write guard/archive strategy.
- [ ] Update documentation and AGENTS/task guidance if needed.
- [ ] Run deterministic safety gates.
- [ ] Prepare a separate destructive-drop proposal only if still desired after archive mode is stable.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pending`
- `typecheck`: `pending`
- `tests`: `pending`
- `api-smoke`: `pending`
- `e2e`: `pending`

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `blocked-on-issue-182`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-25T00:00:00Z`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created to retire legacy `positions` only after canonical writes, backfill, parity, and read cutover are complete.
