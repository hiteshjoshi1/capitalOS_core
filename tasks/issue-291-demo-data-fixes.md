# Issue 291: Demo data fixes

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/291

## Objective
- `make db-seed-demo` gives data a tester can trust: History months observed (not carried), past
  months including the USD and HKD holdings, the HKD values right, and no empty card.

## Architecture Decisions
- Snapshot dates (`seed_snapshots`): the 1st of each of the 12 months (the month-end anchor with
  SNAPSHOT_DAY=1) plus today. They replace day 6, which IBKR and crypto (daily cadence: fresh within
  3 days) read as "carried" at every anchor. Transactions keep the month scaffold.
- Exchange rates: USD-based SGD and HKD rows for every day from ten days before the first snapshot
  to today, `source = 'DUMMY'`, `ON CONFLICT DO NOTHING`, so a provider rate already stored wins.
  `seed_dummy_cleanup.sql` deletes them and marks every user's History dirty from the earliest one,
  as it does for DUMMY prices (#221: both tables are shared).
- Holdings: the seed's value column is the holding's own currency (`market_value_local`). `*_base` is
  in the account's currency (`position_base_currency`), so IBKR's HKD holdings are converted to USD
  at 1/7.80. Before, they were counted as USD 1:1, which overstated the demo by about S$ 5M.
- The empty "DBS Credit Card" that migration 059 gives the demo user is deleted by the seed while
  nothing points at it. It rendered an empty card and an overdue "no data yet" source.
  Applied migrations aren't edited.

## Acceptance Criteria
- [x] History: all 11 months `fresh`, smooth growth (S$ 7.2M → 10.3M); live S$ 11.1M.
- [x] Past months: `fx_incomplete false`, no missing currencies (checked for 2026-03).
- [x] Source freshness: 0 overdue; the demo user has no non-DUMMY account.
- [x] `make db-clear-dummy`: 0 DUMMY fx/prices/transactions/accounts/balances/runs/wallets/positions.
- [x] Postgres tests: seed shape (anchor-day snapshots, a rate for every day, HKD base, no empty
      card) and cleanup (fx rows gone, the dirty mark from the earliest DUMMY price or rate).

## How To Test
- Worktree: `make up db-migrate db-seed-demo`, Generate history, open History, Overview and Data Hub.
- `make db-clear-dummy`, then count DUMMY rows; `make db-schema-check` runs the Postgres tests.

<!-- IMMUTABLE_PLAN_END -->
