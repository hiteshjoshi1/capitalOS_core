# Issue 194: Loan Account Integration (Balances, Rate, Term, Next Payment)

## Objective
- The redesigned Liabilities page (`/liabilities` — now the single merged page covering credit cards, loans, spend-by-category, and transactions; the former separate `/credit-cards` and `/loans` pages were folded into it and now redirect here) has a "State B" layout — a full Loans section (lender, loan type, balance, interest rate, term remaining, next payment amount + date) plus a merged revolving/installment hero — that activates once a user has one or more linked loan accounts.
- Today, `accounts.account_type` already supports a `LOAN` value (see `api/app/models/account.py`), and a user can create a bare `LOAN` account via the existing Add Account flow, but there is no loan-specific data model or endpoint — an `Account` row alone has no balance, rate, term, lender, or next-payment fields.
- This issue adds the backend data model + endpoint needed to power the real Loans section, so the frontend's already-derived `hasLoans` check (`accounts.some(a => a.account_type === "LOAN")`) has real per-loan detail to render instead of "Not synced" placeholders.

## Architecture Decisions
- Decision 1: Add a `loan_accounts` table (mirroring the existing `credit_card_accounts` metadata-table pattern used for cards) keyed by `account_id`, with columns: `lender` (text), `loan_type` (enum: HOME | AUTO | PERSONAL | OTHER), `original_principal`, `current_balance`, `interest_rate_pct`, `term_months`, `term_remaining_months`, `next_payment_amount`, `next_payment_date`.
- Decision 2: New endpoint `GET /spending/loans?month=YYYY-MM&base_currency=SGD` returning a `LoanSummary` schema (`{ month, base_currency, total_balance, loans: LoanItem[] }`), following the same shape/conventions as `GET /spending/credit-cards`.
- Decision 3: Frontend `LiabilitiesOverview.tsx` (the single merged Liabilities page) swaps its current placeholder Loans rows (`"Not synced"` balance/rate/term) for real fields from this endpoint once available; `hasLoans` derivation logic doesn't change since it's already based on linked account existence.
- Decision 4: No fabricated/seeded loan data ships in this issue's scope beyond what's needed for tests — this is a data-model + endpoint issue, not a loan-linking/statement-ingestion issue (that ingestion path, e.g. a loan statement parser, is a separate future issue if/when a lender integration is prioritized).

## Acceptance Criteria
- [ ] `loan_accounts` table + migration added, keyed by `account_id` (FK to `accounts`), with fields listed in Decision 1
- [ ] `GET /spending/loans` endpoint returns per-loan balance, rate, term, and next-payment fields for all `LOAN`-type accounts, with graceful defaults when metadata is missing (mirroring the `credit_card_accounts` fallback pattern in `api/app/routers/spending.py`)
- [ ] New Pydantic schemas added to `api/app/schemas/spending.py`; no existing schemas modified
- [ ] New TypeScript types (`LoanSummary`, `LoanItem`) + `api.loanSummary()` added to `web/src/lib/api.ts`
- [ ] `web/src/routes/LiabilitiesOverview.tsx` Loans section renders real balance/rate/term/next-payment from `api.loanSummary()` instead of the current "Not synced" placeholders, with due-status-pill fallback preserved for loans lacking a `next_payment_date`
- [ ] The single Liabilities page's Upcoming payments list merges loan next-payment dates using the existing shared due-status helper (`web/src/lib/dueStatus.ts`)
- [ ] Backend tests cover: loan with full metadata, loan account with no `loan_accounts` row (fallback), multiple loans aggregation
- [ ] Frontend tests updated to assert real loan fields render (replacing the current "Not synced" assertions in `LiabilitiesOverview.test.tsx`)
- [ ] `make verify` passes (lint + typecheck + test-backend + test-frontend)

## How To Test
- Run `make test-backend` and confirm new loan endpoint tests pass.
- Run `make test-frontend` and confirm `LiabilitiesOverview.test.tsx` passes with real loan data assertions.
- `curl "http://localhost:8000/spending/loans?month=2026-07"` returns valid JSON with `loans[]` populated for any seeded `LOAN` account.
- Manually create a `LOAN` account via `/accounts/new`, seed a `loan_accounts` row, and confirm `/liabilities` renders State B with real balance/rate/term instead of "Not synced".

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
- Last Updated: `2026-07-08`

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
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: Prioritize and schedule this issue; no lender/loan-statement ingestion integration exists yet, so `loan_accounts` will need to be populated manually (or via a future ingestion issue) until then.
- Open questions:
  - Should loan balances/rates be user-entered (manual form, like a simplified Add Account flow) or wait for statement-parser ingestion like credit cards? This determines whether Decision 1's table is populated via a new UI form or a future parser.
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
