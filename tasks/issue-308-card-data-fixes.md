# Issue 308: Card data fixes: DBS payments from the bank side, conversion fees as fees

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/308

## Objective
- DBS card statement checks (#300) close: the payments the DBS card file doesn't list come from the
  paying bank account.
- Currency conversion fees count in the card's fees-and-interest total.

## What the real data showed (read-only, aggregates only)
- The DBS card export lists only its last statement's transactions, while the limit-derived balance is
  live on the download day. A September payment to the card is on the DBS bank account only.
- The bank pays cards with lines that carry the card number; they were stored as EXPENSE and counted as
  spending in Cash Flow on top of the card's own charges.
- On 30 Aug the balance read that day didn't include that day's payment yet (posted the next day).

## Architecture Decisions (D-77)
- `valuation/card_payments.py`: a bank outflow whose text holds a card number (Luhn 15–16 digits, or
  masked with the last 4) matching a card's last 4 (from the card's notes) pays that card.
- Cash flow: such a row is a transfer (not spending), via `own_card_payment` on `_cash_flow_rows`.
- Card ledger / running balance (`facts`) / bridge card activity: a bank-side payment counts only when the
  card's file has no payment of the same amount within 5 days (nearest pairs first).
- Statement check: closing-day transactions move to the next period when that makes a flagged period add
  up; a positive gap after the last card transaction (3+ days) gets a note that charges aren't uploaded.
  New API fields per period: `bank_payments`, `note`.
- `card_fees.py`: conversion / foreign-transaction fee lines are FEE in the Citi, UOB and DBS card parsers.
  `make card-fee-repair` (dry run; APPLY=1) re-types stored rows with a fresh-upload fingerprint.

## Acceptance Criteria
- [x] Real data (read-only probe): DBS 9 Aug→30 Aug reconciles to 0.00; 30 Aug→2 Oct is left with
      +242.44 = charges after the card file's last transaction (13 Sep), named in its note.
- [x] Real data: fee repair dry run finds 5 Citi rows, all fingerprints reproducible.
- [x] Tests: card numbers on bank lines, dedup (exact, days apart, same-amount pairs, other card), ledger
      bank payments / same-day move / missing-tail notes, cash-flow bucket, parsers, fee repair (DB).
- [ ] After deploy: `make card-fee-repair`, then `APPLY=1`.

<!-- IMMUTABLE_PLAN_END -->
