# Issue 300: Cards: a running balance per card, checked against each statement

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/300

## Objective
- Know what each card owes and what was paid, and see when a statement doesn't add up (an overcharge,
  a missing upload, a duplicated transaction).
- The Overview bridge's "Card balances not matched by card transactions" goes to ~0 for cards with a balance.

## Architecture Decisions (D-76)
- Anchors are the existing `credit_balance` snapshots; no migration. Owed at an anchor = newest snapshot
  on/before it (no age limit) + card transactions after its date (`_credit_card_liability_details`,
  method `running`, not clamped). No snapshot: the month's net transactions (method `transactions`, clamped).
- UOB parser: a "Previous Balance" row is a period boundary (it used to overwrite the amount of the row
  above it); each becomes a dated balance (`parser_meta.statement_balances`): the day before its period's
  first transaction. Header "Statement Balance": on a single "Statement Date", else (history export, date
  range) the day before the newest period. `card_statement_balances` returns them all; the upload writes
  each; `make card-balance-backfill` re-parses stored files and writes them (dry run unless APPLY=1).
- `valuation/card_ledger.py`: per card, periods between consecutive balances with charges / fees /
  interest / payments / credits, expected vs printed, flagged above S$ 1; owed now, paid since, paid in
  full, fees + interest this year.
- API: `GET /spending/credit-card-balances`, `POST /spending/credit-card-balances/{account_id}`
  (a typed-in statement balance, for Citi whose CSV states none). Fields only added.
- Web: `components/CardBalances.tsx` on Liabilities (before Upcoming payments).

## Checked on a copy of the real data (worktree DB, 2026-11-07 backup)
- Backfill dry run: 5 new dated UOB balances (12 Apr, 9 Jul, 13 Aug, 12 Sep, 13 Oct); 12 May unchanged.
- With the parser fix and the export's repeated block removed (#299), every UOB statement reconciles to
  S$ 0.00 and UOB owes S$ 674.98 (524.21 paid in full on 2 Nov). May–Jul is flagged: no upload covers it.
- On today's stored rows (duplicates + overwritten amounts) the check flags exactly those periods:
  −509.21 (KIM ABLE 3.00 stored as 512.21), −439.43 (duplicates + two overwritten rows).

## After deploy
1. #299's repair (duplicates) and a re-import or repair of job 32's overwritten amounts.
2. `make card-balance-backfill` (dry run), then `make card-balance-backfill APPLY=1`.
3. Citi: Liabilities → Card balances → enter the last statement's balance.

<!-- IMMUTABLE_PLAN_END -->
