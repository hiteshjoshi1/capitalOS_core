# Issue 472: Cards: payment status only for the live month, one Update balances sheet

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/472

From UX review #432 (V18, V19). Okayed by Hitesh 2026-11-24 (sprint S2).

## Objective
- V18: viewing a past month on Cards must not show today's payment status ("Overdue · 15 Oct" for every
  card). Payment status shows for the current month only, and a card with no due date from a statement or an
  entry says "Due date unknown" (#352), never a date built from a configured due day.
- V19: the per-card "Enter balance" forms stacked on the phone become one "Update balances" sheet listing
  every card.

## Architecture Decisions
- Frontend only; no API change. The existing calls stay: `POST /spending/credit-card-balances/{id}` per card
  (the sheet saves each filled card in turn), `POST /spending/credit-card-dues/{id}` for "Add due date".
- "Live month" = the analytics reply's `month` equals the browser's current month (`currentMonthYYYYMM`), so a
  month switch in flight never shows the old month's sections under the new month's label.
- Another month: "Card balances" (owed now, statement checks, due lines) and "Upcoming payments" are both
  today's data, so neither shows. One "Balances and payments" note says they show on the current month only,
  with a "Show <current month>" button. The month's spend, charges, trend and transactions still show.
- Upcoming payments takes a due date only when `due_source` is `statement` or `manual`. The analytics
  `configured` fallback (credit_card_accounts.due_day placed in the selected month; the demo seed and
  migration 059 set it, no UI does) gives no paid/unpaid state, so it reads "Due date unknown". The backend
  value is left as is (other readers; API contract).
- Update balances: a disclosure (button with `aria-expanded`/`aria-controls`) opening an inline form at the top
  of Card balances rather than a modal: no focus trap needed, works the same on a phone. One `<fieldset>` per
  card (legend = card name, its current statement as a hint), fields: statement date, amount owed, optional
  due date, minimum (when a due date is given). Empty cards are skipped; a half-filled card is named and
  nothing is saved; a card the API refuses stays on the sheet with its reason, saved ones are cleared.
- A card with no statement balance now says so in one line pointing at Update balances (no form under it).

## Acceptance Criteria
- [x] Past month: no "Upcoming payments", no "Card balances", no due status; a note + "Show <month>" button.
- [x] Current month: configured due day reads "Due date unknown"; a statement/typed-in due shows its status.
- [x] One "Update balances" sheet lists every card; saves only filled cards with the existing API.
- [x] No per-card statement balance form.

## How To Test
- `cd web && npx vitest run src/__tests__/CardBalances.test.tsx src/__tests__/LiabilitiesOverview.test.tsx`
- `make verify`
- `make e2e-smoke`: `phone-cards.png` / `desktop-cards.png` show the four demo cards without forms, the
  Update balances button, and "Due date unknown" pills (the demo cards have only configured due days).

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `running`
- Provider/Model: `anthropic/claude-opus-5-5`
- Last Updated: `2026-11-24`

## Deterministic Gate Results (Codex Mutable)
- `lint`: see `make verify`
- `typecheck`: see `make verify`
- `tests`: see `make verify`
- `e2e`: `make e2e-smoke-update`, cards screenshots updated and reviewed
- `api-smoke`: `skip` — no API change
- `policy-checks`: `pass`

## Extra Files Changed (Codex Mutable)
- none

## Human Action Summary (Codex Mutable)
- Next expected action: test instance with the batch, then merge.
- Open questions:
  - Should the analytics/summary `configured` due-date fallback be dropped in the API too (D-94 kept it for
    configured cards)? Cards no longer uses it.
