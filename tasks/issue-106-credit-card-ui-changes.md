# Issue 106: Credit Card UI Changes

## Objective
Replace the credit-card placeholder card on the dashboard with a live summary showing consolidated "money out" across all credit cards for the selected month. Add a new `/credit-cards` detail page showing per-card breakdown, top purchases, and recurring payments. Design all new UI to accommodate future category mapping and unified money-in/money-out views.

## Architecture Decisions

- **AD-1: Dashboard card replaces PlaceholderCard, not a new section.**
  The existing `PlaceholderCard` titled "Expenses — Credit Cards" in `row2` of `App.tsx` (line 160–168) is replaced with a live `CreditCardCard` component. It shows consolidated `total_spend`, card count, and a "View details →" link to `/credit-cards`. No new dashboard rows are added.

- **AD-2: New detail route at `/credit-cards` follows the CashOverview pattern.**
  A new route component `web/src/routes/CreditCards.tsx` is created following the same structure as `CashOverview.tsx`: header with nav pills + month/currency selectors, state machine (`idle→loading→ready→error`), direct API calls via `api.creditCardSummary()` and a new `api.creditCardTransactions()` method.

- **AD-3: New backend endpoint `GET /spending/credit-cards/{account_id}/transactions` for detail data.**
  Returns transactions for a specific credit card account in a given month, with fields: `ts`, `description`, `amount`, `type`, `category`, `merchant_counterparty`, `notes`. The spending router already owns credit-card logic; this extends it. Also add a consolidated `GET /spending/credit-card-transactions?month=YYYY-MM` returning all CC transactions grouped by account for the overview page.

- **AD-4: Top purchases = highest absolute EXPENSE transactions for the month (top 5).**
  Sorted by `ABS(amount)` descending, limited to `type = 'EXPENSE'`. Computed in the backend so the frontend stays thin. Returned as part of a new response schema `CreditCardDetailOut`.

- **AD-5: Recurring payments detected via merchant_counterparty frequency heuristic.**
  A transaction's `merchant_counterparty` that appears in ≥2 of the last 3 months (including selected month) is flagged as recurring. This is a backend computation joining against prior months' transactions for the same credit-card account(s). Returned as a `recurring_payments` list in `CreditCardDetailOut`.

- **AD-6: New Pydantic schemas extend `spending.py`, new TS types extend `api.ts`.**
  Backend: `CreditCardTransactionItem`, `CreditCardDetailOut` in `api/app/schemas/spending.py`.
  Frontend: `CreditCardDetail`, `CreditCardTransaction` types in `web/src/lib/api.ts`.
  No existing schemas are modified.

- **AD-7: Dashboard "money out" uses existing `cash_flow.expenses` field.**
  The dashboard summary already computes `cash_flow.expenses` from all EXPENSE/FEE/TAX/INTEREST transactions (including credit cards). The new credit-card card shows the CC-specific subset via `creditCardSummary.total_spend`. No changes to the dashboard summary endpoint.

- **AD-8: Category mapping is out of scope but the detail page renders `category` field.**
  Transactions already store a `category` column (e.g., `"CreditCard::Purchase"` from the Citi parser). The detail page renders it as-is. Future work will add proper category assignment; the UI is ready for it.

- **AD-9: No new database migrations.**
  All required tables (`transactions`, `credit_card_accounts`, `accounts`) and columns (`category`, `merchant_counterparty`) already exist. The new endpoint queries existing data.

- **AD-10: Frontend-only for dashboard card; backend+frontend for detail page.**
  The dashboard card change is purely frontend (data already fetched via `api.creditCardSummary()`). The detail page requires a new backend endpoint for per-card transactions and recurring detection.

## Risks

- **R-1**: If no credit card data has been ingested (no Issue 105 parser run), the card and detail page show empty state. Mitigated by graceful "No credit card transactions for this month" messaging.
- **R-2**: Recurring payment detection across 3 months requires transactions in prior months. If data is sparse, the recurring list may be empty. This is acceptable — it's a best-effort heuristic.
- **R-3**: The `merchant_counterparty` field may not be populated for all parsers. The Citi parser stores the full description there. The UI must handle `null` merchants gracefully.

## Open Questions

- **OQ-1**: Should the credit card detail page allow filtering by individual card, or show all cards consolidated? **Decision: Show consolidated with per-card subtotals. Each card section is collapsible.**
- **OQ-2**: Should recurring payment threshold be configurable? **Decision: Hardcode ≥2 of last 3 months for now. Can parameterize later.**

## Acceptance Criteria

- [ ] Dashboard "Expenses — Credit Cards" placeholder is replaced with a live card showing `total_spend` for the selected month and the number of configured cards
- [ ] Credit card dashboard card links to `/credit-cards` detail page
- [ ] Detail page shows per-card breakdown with card name, issuer, spend, utilization bar
- [ ] Detail page shows top 5 purchases for the month (sorted by amount descending)
- [ ] Detail page shows recurring payments detected across last 3 months
- [ ] Detail page shows all transactions in a scrollable table with date, description, amount, type, category
- [ ] Empty states render gracefully when no data exists
- [ ] New backend endpoint `GET /spending/credit-card-transactions` returns transaction-level data
- [ ] New Pydantic schemas added to `api/app/schemas/spending.py`; no existing schemas broken
- [ ] New TypeScript types added to `web/src/lib/api.ts`; no existing types broken
- [ ] Route `/credit-cards` registered in `web/src/main.tsx`
- [ ] `make verify` passes (lint + typecheck + test-backend + test-frontend)
- [ ] `make api-smoke` passes
- [ ] `curl /spending/credit-card-transactions?month=2026-03` returns valid JSON
- [ ] Dashboard loads without errors at `http://localhost:5173`

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend
- [ ] Add `CreditCardTransactionItem` schema to `api/app/schemas/spending.py`
- [ ] Add `CreditCardDetailOut` schema to `api/app/schemas/spending.py` (includes `transactions`, `top_purchases`, `recurring_payments`, per-card subtotals)
- [ ] Add `GET /spending/credit-card-transactions` endpoint to `api/app/routers/spending.py`
- [ ] Implement top-purchases query (top 5 EXPENSE by absolute amount for month)
- [ ] Implement recurring-payments detection (merchant_counterparty in ≥2 of last 3 months)
- [ ] Add backend test for new endpoint in `api/tests/`

### Frontend
- [ ] Create `web/src/routes/CreditCards.tsx` detail page component
- [ ] Add `CreditCardDetail` and `CreditCardTransaction` types to `web/src/lib/api.ts`
- [ ] Add `api.creditCardTransactions(month, baseCurrency)` method to `web/src/lib/api.ts`
- [ ] Replace `PlaceholderCard` for credit cards in `web/src/App.tsx` with live `CreditCardCard` component
- [ ] Create `web/src/components/dashboard/CreditCardCard.tsx` dashboard card component
- [ ] Register `/credit-cards` route in `web/src/main.tsx`
- [ ] Add frontend test for `CreditCards.tsx` in `web/src/__tests__/`

### Verification
- [ ] `make api-rebuild`
- [ ] `make verify` (lint + typecheck + test-backend + test-frontend)
- [ ] `make api-smoke`
- [ ] `curl http://localhost:8000/spending/credit-card-transactions?month=2026-03` returns valid JSON
- [ ] Dashboard loads at `http://localhost:5173` with live credit card card
- [ ] `/credit-cards` detail page loads and renders

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-106-credit-card-ui-changes.md
make task-build TASK=tasks/issue-106-credit-card-ui-changes.md
make task-review TASK=tasks/issue-106-credit-card-ui-changes.md
make task-rework TASK=tasks/issue-106-credit-card-ui-changes.md
make task-ship TASK=tasks/issue-106-credit-card-ui-changes.md
```
