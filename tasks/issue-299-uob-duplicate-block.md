# Issue 299: UOB card export: repeated period, and "Previous Balance" overwriting amounts

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/299

## Objective
- UOB card uploads store each transaction once, with its own amount.

## What was wrong (found while tracing the S$ 817.90 "unexplained" on 2026-11-07)
1. The export prints the latest statement period twice, back to back; both copies were stored.
2. **Also found:** an undated "Previous Balance" line was merged into the transaction above it,
   replacing that row's amount (M1 14 Oct S$ 36.90 stored as S$ 271.06; Kim Able 14 Aug S$ 3.00 as
   S$ 512.21; a Hockhua copy S$ 28.00 as S$ 214.28).

## Architecture Decisions
- `_collapse_rows`: a dateless "Previous Balance" row is a period marker, not a continuation line.
- `_drop_repeated_runs`: a run of >= 3 identical rows followed immediately by an identical copy keeps
  the first copy (two identical same-day purchases, or two identical pairs, stay).
- Repair `make uob-card-repair` (dry run; `APPLY=1`): re-parses each kept UOB card upload and, per
  stored row: keep (exact), correct in place (same day/merchant/currency, wrong amount; keeps id,
  category override, transfer links; new fingerprint as a fresh upload would compute), or delete a
  duplicate (its category override moves to the kept twin). File rows not stored are only reported.
  History marked dirty from the earliest change (#138).
- Citi job 33's two repeated pairs (Air India, same day) are real separate charges: unchanged.

## Acceptance Criteria
- [x] The real file parses to 31 rows with correct amounts (was 51).
- [x] Dry run on the real DB: job 32 keep 29, correct 2, delete 20 duplicates; History from 2026-08-14.
- [x] Tests: marker no longer overwrites, repeated period kept once, the real file's shape, same-day
      identical purchases and pairs kept, repair plan keep/correct/delete, clean rows untouched.
- [ ] After deploy: `make uob-card-repair` (dry run), then `APPLY=1`.

<!-- IMMUTABLE_PLAN_END -->
