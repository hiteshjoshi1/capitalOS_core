# Issue 352: Card payment due dates: read them from statements, remind in the Inbox before they're due

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/352

## Objective
- Never miss a card payment again (the Citi S$100 late fee and S$104.13 finance charges, Sep 2026).
- Only due dates a statement actually prints; "due date unknown" otherwise. Never guessed.

## Findings (real files, read-only, 2026-11-10)
- UOB card XLS (`uob_credit_card_xls_v1`): "Statement Date" and "Statement Balance" only; no due date, no minimum.
- DBS card CSV (`dbs_credit_card_csv_v1`): "Transactions as at", credit and available limit; no due date.
- Citi card CSV (`citi_credit_card_csv_v1`): transactions only, no header.
- So no supported card file yields a due date; the PDF statements do, and are not parsed.

## Architecture Decisions
- `card_statement_dues` (migration 084): one row per card statement (statement date, due date, amount due, minimum, source statement|manual, import job). D-91.
- Typed in from the statement on Liabilities → Card balances ("Add due date", or with a typed-in balance). A parser that reads one sets `parser_meta["payment_due"]` (hook in the import runner; removed with its upload).
- Current due = newest statement up to today; paid = card payments + credits after the statement date, bank-side included (#308).
- Inbox: `card_due_soon` (≤5 days, medium) and `card_overdue` (high) until paid; "Card payments up to date" in all-good.
- `due_date` in credit-card analytics/summary is null instead of day 1 when nothing is configured.

## Acceptance Criteria
- [x] A due typed in from a statement shows on Card balances, Liabilities' upcoming list and the Inbox.
- [x] A matched payment clears it; the minimum alone keeps it overdue with a note.
- [x] No card shows a guessed due date.
- [ ] Parser tests per supported format yielding a due date: not possible, none print one (see Findings).

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_card_dues.py`
- `cd web && npx vitest run src/__tests__/CardBalances.test.tsx src/__tests__/dueStatus.test.ts`
- Test instance: Liabilities → Card balances → a card → "Add due date"; Data Hub Inbox shows it within 5 days of the date.

<!-- IMMUTABLE_PLAN_END -->

## Execution Journal
- Workflow Status: `shipped` (PR open)
- No post-deploy backfill: the already-imported card files print no due dates.
