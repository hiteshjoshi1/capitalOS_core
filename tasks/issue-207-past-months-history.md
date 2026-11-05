# Issue 207: Past months change silently: dated card liability snapshots, account close date instead of carry-forward forever

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/207 (findings 1.5 and 1.6 of the #130 review)

## Objective
- A past month's credit-card liability must not change when a newer statement is uploaded.
- A closed account must stop counting after its close date instead of carrying its last snapshot forward forever.
- Values a month carries forward from before it are visible (add-only API field, small UI hint).

## Architecture Decisions
- Card balances are dated `account_balance_snapshots` rows (`balance_type='credit_balance'`, negative while owed, the account's currency), one per statement date (upsert; undo restores what it replaced). DBS: available − limit as at the export date. UOB: −statement balance on the statement date. Citi: states none (transaction method).
- A card's liability at an anchor = its newest statement balance on or before the anchor's date if at most 45 days older (`CARD_STATEMENT_MAX_AGE_DAYS`), else its net transactions in the anchor's card window (unchanged method). Spend after the statement date is not added. Proposed D-n in the PR.
- `credit_card_accounts.available_limit*` stay and are still written (Spending page); they no longer feed valuation, so updating them marks nothing.
- `accounts.closed_on` (migration 078): every as-of reader adds `closed_on IS NULL OR closed_on >= anchor_date` (`app/portfolio/account_open.py`). Wallets are not accounts and are unaffected.
- Card statement balances are not cash coverage (`canonical_snapshot_coverage_as_of` excludes them).
- Backfill: migration 078 turns each card's current limits into one dated snapshot (no number moves within 45 days of it); `make card-balance-backfill` re-parses stored card statements for the older dates (dry run unless APPLY=1, idempotent).
- Carried-forward flag: `GET /accounts` adds `closed_on`, `data_month`, `last_data_as_of`, `carried_forward_from` (default month: the latest completed one; `?month=YYYY-MM`).

## Acceptance Criteria
- [x] Upload card statement for month M, then M+1: month M's liability unchanged (`test_next_months_statement_leaves_last_months_card_liability_unchanged`).
- [x] An account closed on D contributes 0 at every anchor after D (cash, holdings, NAV, cards); earlier months unchanged; History follows (`test_closed_accounts_contribute_nothing_after_the_close_date`).
- [x] Backfill idempotent, dry run writes nothing (`test_backfill_writes_each_stored_statement_once`, Postgres `test_migration_078_backfills_the_current_limits_once`).
- [x] Dirty marks from the earliest affected date on every write (statement upload, close/reopen, backfill, migration).
- [x] Golden + invariant tests pass with no golden change.

## How To Test
- `make verify`; `make db-schema-check`.
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_past_months_history.py -q`.
- After deploy (coordinator): `make card-balance-backfill` (dry run), then `make card-balance-backfill APPLY=1`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `make verify`: see PR body.
- `make db-schema-check`: pass (57 migrations, idempotent, matches schema.sql, 11 Postgres tests).

## Extra Files Changed (Codex Mutable)
- `api/tests/conftest.py` — `accounts.closed_on` in the SQLite DDL (one line).
- `api/tests/valuation_household.py` — user B's card gets the snapshot migration 078 would backfill from its limits, so the household keeps its numbers.
- `api/tests/test_wealth_rollup_invalidation.py` — the limits-row dirty test now tests the statement balance's mark (limits are no valuation input).
- `Makefile` — `card-balance-backfill` target.
