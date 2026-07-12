# Issue 198: Credit-card spend analytics, charge visibility, and per-card history

## Objective
- Redesign the Credit Cards experience around historically reliable transaction data: selected-month spend, per-card filtering, fee/interest/tax visibility, category composition, and 12-month spend trends.
- Let users inspect all transactions for a month across all cards or one selected card, while prominently calling out annual fees, finance charges, interest, and tax.
- Show issuer-reported available credit only when supplied, and remove misleading utilization, inferred outstanding/current-due presentation, credit-limit progress, upcoming-payment estimates derived from those values, and balance-delta comparisons.

## Architecture Decisions
- Decision 1: The high-fidelity UX contract is `design_handoff_capitalos_wealth/credit-card-analytics/screens/credit-card-analytics.html`. Read the adjacent `README.md` and `IMPLEMENTATION_PROMPT.md` before changing code. Recreate it in the existing React/TypeScript and `App.css` system; do not paste prototype markup or introduce a second styling system.
- Decision 2: Define **spend** consistently as the absolute base-currency value of `EXPENSE`, `FEE`, `TAX`, and `INTEREST` transactions. Exclude `TRANSFER`/card payments, credits, income, and refunds. Purchase spend is `EXPENSE` only. Every hero, comparison, per-card total, category total, trend point, and transaction count must use an explicitly documented compatible scope.
- Decision 3: Add an authenticated, additive analytics contract, recommended as `GET /spending/credit-card-analytics?month=YYYY-MM&base_currency=SGD&months=12&account_id=<optional>`. It must return selected-month aggregate/per-card spend, prior-month like-for-like spend, a monthly aggregate/per-card trend, charges, categories, transactions (or stable linkage to the existing detail response), and optional available-credit metadata. Keep business logic out of the router and make calculations testable as pure/service helpers.
- Decision 4: Card selection is a single shared scope. Choosing All cards or one `account_id` updates the selected-month spend, prior-month comparison, charge summary/list, category totals, trend series, and transaction ledger together. Never hardcode account IDs, issuer names, or card counts.
- Decision 5: Available credit is issuer-provided metadata from `credit_card_accounts.available_limit` with `available_limit_as_of`. Display it only when both exist. Do not infer it, do not turn missing values into zero, and do not compare it with transaction-derived history. When absent, show “Not provided by issuer” only in card metadata or omit the block.
- Decision 6: Remove the UI’s utilization percentage, `0% of S$0 limit`, credit-limit progress bars, inferred `current_due`/outstanding balance as a headline, upcoming-payment estimates derived from those values, and the balance “vs last month” chip. Do not remove existing API fields in this issue; preserve compatibility while stopping the new UI from presenting unreliable values.
- Decision 7: Use transaction-derived history rather than a new credit-card balance snapshot table. Trend aggregation must be one bounded query/helper over the requested window, not N sequential endpoint calls.
- Decision 8: Charge attention includes `FEE`, `INTEREST`, and `TAX`. Render charge rows and the charge total prominently using the existing negative/bad color. Annual/finance-fee descriptions are ordinary rows of those types; do not rely exclusively on merchant keyword matching.
- Decision 9: Maintain strict user isolation with `account_scope_sql`/authenticated ownership on analytics, filters, trend queries, and ledger rows. Validate that a requested `account_id` is an owned `CREDIT_CARD` account; return 404 for inaccessible/nonexistent cards without disclosing ownership.
- Decision 10: Mobile is a first-class acceptance target. At narrow widths, filters remain horizontally scrollable, summary panels stack, transaction rows become readable touch-friendly cards or an equivalently accessible responsive table, no information is hover-only, and existing bottom navigation behavior remains intact.

## Acceptance Criteria
- [ ] The production Credit Cards page follows the supplied desktop and mobile handoff in information hierarchy, spacing, theme behavior, filters, charge emphasis, chart, category section, available-credit treatment, and ledger.
- [ ] Selecting a month displays total spend for that month and a prior-month comparison calculated from the identical transaction types, account scope, base currency, and FX convention.
- [ ] The page supports All cards and individual-card filters sourced from the authenticated user’s real credit-card accounts; the hero, comparison, charges, categories, trend, and ledger all update consistently.
- [ ] The selected-month transaction ledger shows date, merchant/description, card, resolved category, transaction type, and signed/display amount, and it can be filtered by card without refetching unrelated users’ data.
- [ ] `FEE`, `INTEREST`, and `TAX` rows are surfaced in a prominent red attention section with an accurate total; a month/scope with none shows “No card charges this month” rather than hiding the section ambiguously.
- [ ] The 12-month spend chart supports aggregate and per-card views and reconciles exactly to backend transaction aggregation for every point. Transfers/payments and refunds do not inflate the series.
- [ ] Per-card selected-month spend reconciles to the all-card total, subject only to deterministic base-currency rounding; category totals plus explicitly represented uncategorized spend reconcile to selected-scope purchase spend.
- [ ] Issuer-reported available credit and its as-of date appear only for cards with both values. Missing data never renders as `0`, `0%`, or `S$0 limit`.
- [ ] Utilization, total-limit progress, inferred outstanding/current-due headline, unreliable upcoming-payment estimates, and balance “vs last month” delta are absent from the redesigned page.
- [ ] Existing response fields are not removed. OpenAPI schemas and strict TypeScript API types remain aligned for all additive fields/endpoints.
- [ ] Loading, error with retry, no-card, no-transaction, no-charge, and missing-available-credit states are implemented using established CapitalOS patterns.
- [ ] Desktop and mobile accessibility includes labeled card filters with pressed state, keyboard-operable controls, non-color-only charge semantics, accessible chart summary/labels, and transaction content available outside hover tooltips.
- [ ] Backend tests cover month boundaries, `account_id` filtering, aggregate/per-card reconciliation, 12-month ordering across year boundaries, transaction-type inclusion/exclusion, charge extraction, categories, FX conversion, missing metadata, invalid/unowned account IDs, and multi-user isolation.
- [ ] Frontend tests cover month/card interaction, filtered ledger rows, red charges, no-charge state, aggregate/per-card trend changes, available-credit conditional rendering, removal of zero-limit/utilization copy, responsive semantics, and loading/error/empty states.
- [ ] Playwright covers the primary flow at desktop and mobile widths: open Credit Cards, change month, select a card, observe updated spend/trend/ledger, and verify a fee/interest/tax warning.
- [ ] Backend, frontend, contract, smoke, lint, typecheck, and E2E Makefile gates required by `AGENTS.md` all pass.

## How To Test
- Run `make api-rebuild`, `make contract-backend`, `make test-backend`, and `make api-smoke`; confirm the additive analytics contract is valid, isolated by user, and its aggregate/per-card/monthly totals reconcile.
- Run `make web-rebuild`, `make lint`, `make typecheck`, `make contract-frontend`, and `make test-frontend`; confirm strict types compile and the Credit Cards component tests cover filters, charges, trends, optional metadata, removed utilization copy, and all required states.
- Run `make e2e`; confirm the desktop and mobile Credit Cards flows pass with card filtering and visible charge attention.
- Focused API check: authenticate, call `/spending/credit-card-analytics` for a known month with and without `account_id`, and confirm filtered spend/trend/charges/transactions reconcile to SQL over owned `CREDIT_CARD` transactions.
- Manual visual check: open the production page beside `design_handoff_capitalos_wealth/credit-card-analytics/screens/credit-card-analytics.html` at approximately 1440px and 390px in both themes; confirm hierarchy, responsive stacking, touch targets, ledger readability, and absence of `0% of S$0 limit`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not started`
- Workflow Status: `blocked`
- Provider/Model: `<provider>/<model>`
- Last Updated: `2026-07-12`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `Not started — design and implementation issue prepared for review.`
- Attempted mitigations:
  - `Existing Credit Cards page remains available until this issue is implemented.`
- Suggested human action: `Open the design prototype, review the UX and metric definitions, then approve issue 198 for implementation.`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Open design_handoff_capitalos_wealth/credit-card-analytics/screens/credit-card-analytics.html and review desktop/mobile behavior before running issue 198.`
- Open questions:
  - `Should CSV export ship in issue 198 or remain a visual placeholder for a follow-up? The implementation must not render a nonfunctional button.`
- If PR raised but intent partial:
  - unmet criteria: `n/a — not started`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
