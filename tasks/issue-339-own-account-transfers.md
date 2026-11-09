# Issue 339: Own-account transfers aren't paired

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/339

## Objective
- Standing instructions between the holder's own accounts (bank A "SI TO :<holder> REF:SALARY" →
  bank B "GIRO SI SALARY … <holder>") are transfers: not income on the receiving side, not left in
  Unexplained. The employer's salary stays income.

## Architecture Decisions (D-85)
- Read-time classification in `_cash_flow_rows` (Cash Flow, the bridge and everything reading them):
  `valuation/own_transfers.py` marks `own_transfer` = "name" | "pair".
  - Name: every word of the user's display name (>= 2 words) in the counterparty text / notes.
  - Pair: same amount, opposite sign, same currency, two of the user's accounts, within 3 days, one
    side already transfer-like; never a salary-category row; equally near candidates → no pair.
  - Rows are fetched 3 days either side of the window so pairs across the edge are found.
- `_is_explicit_source_transfer` treats `own_transfer` rows as transfers (bucket None).
- Bridge `_uncounted_rows`: a pair with both sides in the period is left out of Other's items; a
  one-sided own transfer is named ("other account's side isn't uploaded" / "other side dated …").
- No repair: nothing stored changes, so no History/Cash Flow invalidation is needed (flows are read
  at request time; History rollups hold balances, not flows).

## Acceptance Criteria
- [x] Real data (read-only): the receiving bank's credits (Oct, Nov) no longer count as income; the
      card-payment credit on Citi (Sep) neither; the employer salary unchanged.
- [x] Nov 2026 Unexplained → Other loses the paired transfers.
- [x] Tests: name rule, one-sided by name, cross-type pair, same-amount pair, too far, ambiguous,
      employer salary, same account, DB read across the month edge, bridge invariant with a pair.

<!-- IMMUTABLE_PLAN_END -->
