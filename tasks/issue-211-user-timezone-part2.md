# Issue 211: Per-user timezone, part 2: spending/cash-flow month windows and crypto snapshot dates

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/211

## Objective
- Spending (`/spending/*`) and the dashboard cash-flow card count a month from midnight to midnight in the user's home timezone (D-49), not 00:00 UTC.
- Crypto wallet snapshots are dated by a stated rule instead of a fixed Asia/Singapore date.

## Architecture Decisions
- One rule, reused: `app.valuation.clock._transaction_in_month_window` is `_card_transaction_in_window` (#202) with a date anchor; `_transaction_month_key` buckets rows by the same calendar (date-only 00:00 UTC rows by their date, timed rows by their local date). SQL takes a day of slack either side (`_transaction_query_bounds`) and the helper decides each row, as the card liability query does.
- Spending's `_month_key` now delegates to `_transaction_month_key`, so the selected month, prior month, trends, recurring detection and card analytics all bucket the same way.
- Crypto snapshot date (proposed D-51): today in the **wallet owner's** home timezone (app `TZ` for a user without one), whoever runs the refresh (owner, admin request, scheduler). Rejected: UTC like market data (D-44 covers shared market data; a wallet balance is the owner's own holding like a statement balance, and UTC would move every Singapore refresh between 00:00 and 08:00 to the previous day, after that user's month had already closed); the refreshing request's timezone (an admin or the scheduler would date another user's wallet in their own calendar); keeping fixed Asia/Singapore (wrong for every other user).
- Unchanged (out of scope): FX rate dates per row (D-44, UTC date), the cash-flow reconciliation bridge's snapshot-to-snapshot comparison, card liability (`_credit_card_liability_component`, #207 is changing it), job schedules.

## Acceptance Criteria
- [x] A New York user's February spending includes a transaction at 23:00 local on 28 Feb (a real timestamp) and a date-only row on 1 Feb; 22:00 local on 31 Jan is January's.
- [x] A Singapore user's numbers are unchanged (same rows as the old UTC window).
- [x] Dashboard cash flow follows the same window.
- [x] The crypto snapshot date rule is written down (proposed D-51) and tested.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_user_timezone_spending.py` (16 tests).
- `make verify` (lint, typecheck, backend + frontend tests, goldens and invariants unchanged).

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `make verify`: see PR description.

## Extra Files Changed (Codex Mutable)
- `api/tests/test_crypto.py` — reason: three tests patched `app.crypto.valuation._as_of_date`, which is no longer imported there; they now patch `app.crypto.ingest._as_of_date` (the same function).
