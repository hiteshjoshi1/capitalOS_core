# Issue 278: Data Hub freshness: an upload source's row opens Upload prefilled

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/278

## Objective
- From an overdue (or any) statement source in Data Hub's freshness table, one click lands on Upload with
  the account, the due statement's date and what's expected already filled in.

## Architecture Decisions
- Frontend only; the API's freshness row already has `source_key` (`account:<id>`), `kind`, `cadence`,
  `last_data_date`. No API change.
- `lib/sourceFreshness.ts`: `expectedStatementDate` = one cadence period after the last data (the API's
  due date without grace, D-67), month-ends kept as month-ends (30 Sep → 31 Oct), clamped to today; no data →
  today; `off` → no date. `sourceLink`: upload kinds → `/ingest?account_id&as_of&last_data&cadence`,
  `market_data` → `/market-data`, Flex/wallets/FX → no link. `uploadExpectationLine` for Upload.
- Table: the name is a real link (keyboard), the row is clickable too, except clicks on its own controls.
- Strip: exactly one overdue upload source → an extra "Upload it →" link next to "Open Data Hub →".
- Ingest: `as_of` prefills the statement date only when a real date not after today; the line shows only
  while the requested account is selected.

## Acceptance Criteria
- [x] Upload rows link to prefilled Upload; market data → Market data; others no link.
- [x] As-of rule per cadence, month-end handling, clamp to today, never-loaded, off (tests).
- [x] Ingest prefill + expectation line; malformed/future as_of ignored (tests).
- [x] 375px: Data Hub and Upload have no horizontal overflow (Playwright, demo data).

## How To Test
- `cd web && npx vitest run src/__tests__/SourceFreshnessUploadLink.test.tsx src/__tests__/Ingest.test.tsx`
- Worktree stack + `make db-seed-demo`, Data Hub → click "DBS Credit Card" → Upload shows the account,
  today's date and "DBS Credit Card: no data yet. Upload its newest statement."

<!-- IMMUTABLE_PLAN_END -->
