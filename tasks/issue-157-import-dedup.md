# Issue 157: Import dedup: occurrence counts and broker IDs, not value tuples

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/157

## Objective
- A bank/card upload stores every genuine transaction (two identical same-day purchases are two rows) and never stores one twice (re-upload, overlapping file, a category changed since).
- IBKR cash-ledger lines and trades are replaced by their IBKR id when they have one, so a re-issued line with edited text doesn't double-count a dividend (D-20 reads dividends from the ledger).

## Architecture Decisions
- Uploads dedup by **occurrence count per natural key** (account, ts, type, amount, currency, counterparty; no category): a file with the key n times against m stored rows inserts n - m.
- New rows get `transactions.source_fingerprint` = sha256(natural key + occurrence index), unique per account (partial index, NULL for older rows). The dedup decision is the count, not the fingerprint; the unique index is a backstop. A taken index moves to the next free one, so it can never reject an upload.
- A per-account `pg_advisory_xact_lock` around the count+insert (released by the commit that commits the rows); no-op on SQLite.
- IBKR ledger: a line with a transaction id replaces every stored line with that id (as a group, so one id with lines in two currencies keeps both); exact repeats of an id line within one report are stored once. Id-less lines: per key, the stored lines are replaced by the report's lines (count = the report's count).
- IBKR trades: id-bearing replaced by execution id (unchanged); id-less replaced per key as a group (two identical fills both kept). An empty `ibExecID` is stored as NULL.
- Migration 073: `source_fingerprint` + unique partial index; the value-tuple unique index `uq_portfolio_cash_ledger_activity` is replaced by one restricted to id-bearing lines.

## Acceptance Criteria
- [x] Two identical same-day purchases in one file both stored
- [x] Re-uploading the same file inserts nothing
- [x] Overlapping file (A,B then A,B,C) inserts only C
- [x] A reclassified category doesn't double-insert
- [x] IBKR re-issued ledger line with edited description isn't doubled
- [x] Two id-less identical ledger lines both kept (and trades likewise)

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_import_dedup.py tests/test_ibkr_dividends_ledger.py -q`
- `make verify`
- `make db-migrate` on an isolated stack applies 073.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `tests`: pass — tests/test_import_dedup.py (14) + tests/test_ibkr_dividends_ledger.py (4)
- `make verify`: backend 593 passed, lint/typecheck clean; frontend 1 failure in authColdLoad.test.tsx (untouched file; passes 3/3 alone, full `npm test -- --run` rerun 296/296)
- Postgres (isolated stack): `make db-migrate` applied 073; upload of a synthetic file with two identical rows inserted 3, re-upload inserted 0 / skipped 3 (advisory lock + NUMERIC match exercised)

## Effect on existing data
- Old `transactions` rows have `source_fingerprint` NULL; they still count as stored occurrences of their key. No backfill.
- The old upload dedup matched on category too, so a category changed since import made a re-upload insert a second copy. Those historical copies stay; from now on a re-upload counts them as stored occurrences.
- A file that earlier lost a genuine repeat (old dedup dropped the second identical row) gets that row on its next re-upload.
- The `fp:` in `notes` now holds the new fingerprint (nothing reads it).
- Old ledger/trade rows already carry their IBKR ids; the next import replaces them by id. The migration's new index is a subset of the old one, so existing rows satisfy it.
