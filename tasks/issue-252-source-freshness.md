# Issue 252: Data Hub per-source freshness table plus an Overview summary

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/252

## Objective
- Say plainly, per data source, whether its data is as current as it should be ("can I trust this month?", #131 Data Hub review).
- Surface overdue sources on Overview in one line, hidden otherwise.

## Architecture Decisions
- D-67 (docs/decisions.md): data dates from the canonical facts (D-56), cadence defaults per source type, per-source overrides stored per user (migration 080), one lean endpoint (D-57).
- New code sits in its own files (router, schema, service, components, CSS) so the Overview change is two lines (an import and `<SourceFreshnessStrip />`) and Data Hub's is two lines.

## Acceptance Criteria
- [x] Data Hub table: one row per account / wallet / quote feed / FX feed with last data date, expected cadence, overdue and for how long.
- [x] Cadence defaults by source type, overridable per source (stored, owner-scoped), edited in the Data Hub row.
- [x] Overview line "N sources overdue: … · Open Data Hub" only when something is overdue.
- [x] One lean endpoint shared by both: `GET /dashboard/source-freshness`; `PUT` / `DELETE /dashboard/source-freshness/{source_key}`.
- [x] Backend tests per source type and cadence edges (weekends for weekday feeds, month ends, leap year, year boundary, never loaded, off, future dates); component tests; fits 375px and 340px.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_source_freshness.py tests/test_cross_user_isolation.py`
- `cd web && npx vitest run src/__tests__/SourceFreshness.test.tsx` and `npx playwright test`.
- Demo stack (`make up && make db-migrate && make db-seed-demo && make web-up`): Data Hub shows "Source freshness"; Overview shows "1 source overdue: DBS Credit Card (no data yet)" (the migration-seeded demo card has no data).
- On a test instance with a copy of the real data: the table's dates match the newest dates in the database.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `review`
- Workflow Status: `shipped`
- Provider/Model: `anthropic/claude-opus-5.5`
- Last Updated: `2026-11-06`

Notes:
- Sources: open accounts (closed ones are not sources), active wallets, quote feeds only for exchanges with a held stock/fund today (`held_position_rows`), FX only when the user has another source (rates are shared; a user with nothing gets no rows, so the cross-user isolation test's user B sees nothing change).
- Card last data date = newest of the statement balance (no 45-day limit) and the newest statement transaction (date in the user's timezone, never after today).
- Golden files: unchanged (no valuation reader changed; the new reader is additive).
- `migrations/schema.sql`: the first `make db-schema-update` couldn't create its throwaway network (Docker address pools full from other worktrees' stacks), so it was regenerated with the script's own pg_dump flags and header from this worktree's migrated database (diff: the new table, its key and FK only). A later `make db-schema-check` passed: 59 migrations, idempotent, matches schema.sql, 24 Postgres tests green.
- e2e fixture `web/tests/e2e/fixtures/demo-api.json`: only the new `/dashboard/source-freshness` response added (recorded from the demo seed); a full re-record also changed unrelated entries (FX fill, timestamps), so those were left as they were.

## Deterministic Gate Results (Codex Mutable)
- `make verify`: lint, typecheck pass; backend 991 passed, 25 skipped; frontend 62 files / 493 tests pass (after the Data Hub test mocked the new call).
- `make db-schema-check`: pass.
- Playwright: 36 passed (incl. mobile-no-overflow at 375px); /operations and /wealth checked by hand at 340px (no horizontal scroll).

## Extra Files Changed (Codex Mutable)
- `api/tests/conftest.py` — reason: clear the new table between tests.
- `api/tests/test_cross_user_isolation.py` — reason: the new GET joins the positive-control list.
- `web/src/__tests__/api.coverage.test.ts` — reason: exercise the new API wrappers.

## Human Action Summary (Codex Mutable)
- Next expected action: test on a test instance with a copy of the real data (compare the table with the newest dates per account / wallet / exchange / FX).
- Open questions:
  - Defaults (statements monthly + 10 days, Flex weekdays + 2, quotes/FX weekdays + 1, wallets daily + 1) are a first guess; each is changeable per source in the row.
