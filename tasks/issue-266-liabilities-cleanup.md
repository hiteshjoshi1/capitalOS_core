# Issue 266: Liabilities cleanup

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/266

## Objective
- Liabilities reads cleanly: consistent rounding, a "Recurring" that means real repeats, one transaction
  list instead of three long sections, no "Available credit: not provided" filler.

## Architecture Decisions (D-72)
- **Real repeat** (`api/app/routers/spending.py: detect_recurring_cadence`, pure): a card + merchant is
  recurring when it is
  - charged in the selected month,
  - in at least 3 distinct months of the trailing 6 (`RECURRING_LOOKBACK_MONTHS`),
  - at most once a month (several charges in a month = shopping),
  - in consecutive months, with at most one missed month,
  - with every charge within max(2, 10%) of the median (base currency).
  Cadence is "monthly"; quarterly/yearly can't show 3 times in 6 months. The API adds `cadence` and
  `typical_amount` to each recurring payment (fields only added).
- **One list** (`web/src/lib/liabilities.ts`): filters All / Notable (purchase > S$ 50, biggest first) /
  Recurring (card + merchant matches a recurring payment, purchases only) / Fees & charges (non-EXPENSE),
  with counts; CSV exports the filtered rows. The charge alert has "Show charges". Recurring rows carry a
  "Monthly · N months" tag. On a phone the table becomes stacked rows.
- **Rounding** (D-46 formatter): totals and summaries whole units, single transactions to the cent.
- **Available credit**: shown only with a value and an as-of date.

## Acceptance Criteria
- [x] Recurring excludes shopping and travel (demo: 17 subscriptions/utilities/memberships, no shops).
- [x] One filtered list; Notable, Recurring, Fees and Transactions sections gone.
- [x] No "Not provided by issuer"; no 1-decimal amounts.
- [x] 375px: no horizontal overflow.

## How To Test
- `pytest tests/test_recurring_cadence.py tests/test_spending.py` (api-dev container).
- `cd web && npx vitest run src/__tests__/liabilities.test.ts src/__tests__/LiabilitiesOverview.test.tsx`
- Worktree stack + `make db-seed-demo` + `make web-up`: /liabilities at 375px and 1280px, each filter.

<!-- IMMUTABLE_PLAN_END -->
