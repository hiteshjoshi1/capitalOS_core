# Issue 329: Bridge Catch-up line for stale starting figures

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/329

## Objective
- Months of activity behind a stale starting figure no longer read as this month's Unexplained.

## Architecture Decisions (D-81)
- Stale = the account's starting figure is > CATCH_UP_STALE_DAYS (7) older than the period start,
  and a newer figure exists at the end.
- Cash (balance kind; not IBKR NAV or ledger-covered accounts): catch-up = change over the period −
  the account's own transactions in the period (all types, in base at their own dates' rates).
- Holdings (accounts with no cash record): quantity changes between the old and the newer statement.
- A new "catch_up" line (after cash_kept), one part per account with its dates. The start is unchanged.

## Results (real data, Nov 2026, read-only)
- Before: Unexplained +S$ 23,905 (Other +12,109, Sharekhan untracked trades +4,795).
- After: Catch-up +S$ 20,294 (DBS 2 Oct → 3 Nov, OCBC 29 Aug → 7 Nov, UOB 4 Jul → 7 Nov, Sharekhan
  29 Aug → 7 Nov statements); Unexplained +S$ 3,611; untracked trades 0. The remaining Other (−S$ 3,390)
  is one-sided transfers in the period, named by #332.

## Tests
- tests/test_bridge_catch_up.py (7): the cash formula, not-stale cases (recent, no newer balance, NAV),
  ledger accounts skipped, stale holdings detection, the household's March catch-up (HSBC only) and totals.
- test_month_bridge.py: optional lines allowed after the fixed five.

<!-- IMMUTABLE_PLAN_END -->
