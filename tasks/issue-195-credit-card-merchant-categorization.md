# Issue 195: Credit Card Transaction Merchant Categorization

## Objective
- The Liabilities page's "Spend by category" widget (`GET /spending/credit-card-transactions`, rendered in `web/src/routes/LiabilitiesOverview.tsx`) shows only a single category for every user today. This is not a display bug — every credit card purchase in the database genuinely has the same raw `category` value, so there is nothing meaningful to group by yet.
- This issue adds real per-merchant categorization for credit card transactions, and makes the existing category-mapping pipeline actually reachable for them, so "Spend by category" (and the "Notable charges" / "All transactions" category tags on the same page) show real categories (Dining, Travel, Groceries, Subscriptions, etc.) instead of one bucket.

## Root Cause
- Every credit card statement parser hardcodes the same literal raw category for every non-fee/interest/payment expense line, with no merchant/description-based classification at parse time:
  - `api/app/ingestion/parsers/uob_credit_card_xls_v1.py` (~line 188) → `"CreditCard::Purchase"`
  - `api/app/ingestion/parsers/dbs_credit_card_csv_v1.py` (~line 148) → `"CreditCard::Purchase"`
  - `api/app/ingestion/parsers/citi_credit_card_csv_v1.py` (~line 40) → `"CreditCard::Purchase"`
- The backend does compute a `resolved_category` per transaction (`api/app/routers/spending.py`, `credit_card_transactions`), coalescing `category_overrides` → raw `category` → `"Uncategorized"` — but there are no overrides to coalesce from, because the existing manual-mapping pipeline can't see these rows at all:
  - `GET /categories/unmapped` (`api/app/routers/categories.py`, ~lines 270-300) only surfaces transactions where `category IS NULL OR TRIM(category) = '' OR LOWER(TRIM(category)) = 'uncategorized'`. `"CreditCard::Purchase"` is none of those, so card purchases never appear in the `CashFlowMapping.tsx` UI for a user to categorize by hand.
  - The seeded rule set (`migrations/027_category_mapping.sql`, ~lines 88-116) has rules for `Brokerage::*`, `Bank::Transfer`, `CreditCard::Payment`, etc., but nothing matches `CreditCard::Purchase`, so rule-based backfill (`POST /categories/backfill`, `api/app/routers/categories.py` ~lines 397-414) wouldn't help either — and that endpoint is never called from the frontend today regardless.
- Frontend note (already fixed as part of the Liabilities/Credit Cards page merge): `LiabilitiesOverview.tsx` now groups by `resolved_category` instead of the raw `category` field, and the `CreditCardTransaction` TS type (`web/src/lib/api.ts`) now declares `resolved_category`/`category_source`. This was a real but secondary bug — fixing it alone does nothing until the backend issue below is resolved, since `resolved_category` currently just echoes the same raw placeholder.

## Architecture Decisions (proposed — to be confirmed at implementation time)
- Decision 1: Add merchant/description-based classification for credit card purchases, either (a) rule-based keyword matching against `merchant_counterparty`/`description` at parse time (mirroring how `category_engine.py`'s `apply_rules` already works for other transaction types), or (b) a dedicated card-purchase categorization pass that runs post-ingestion. Prefer (a) for consistency with the existing rule-engine pattern unless merchant data proves too sparse/inconsistent per issuer.
- Decision 2: Broaden the `/categories/unmapped` filter (`api/app/routers/categories.py`) to also surface transactions whose raw category is a generic parser placeholder (e.g. `CreditCard::Purchase`, and the equivalent for bank statements if applicable) rather than only NULL/empty/"uncategorized" — this lets users manually categorize card merchants through the existing `CashFlowMapping.tsx` UI even before/without automatic classification.
- Decision 3: Add seed rules to `migrations/027_category_mapping.sql` (or a new migration) for common merchant patterns so `/categories/backfill` can resolve a meaningful share of card purchases automatically, and wire `/categories/backfill` into the ingest flow or an explicit UI action (currently unused from the frontend).
- Decision 4: No change needed to `resolved_category`'s coalesce logic in `spending.py` — once Decisions 1-3 land, real categories will flow through the same column already read by the frontend.

## Acceptance Criteria
- [ ] Credit card purchases get a real per-merchant category at ingestion time (or via a backfill pass), not a single hardcoded placeholder
- [ ] `/categories/unmapped` surfaces uncategorized/placeholder-category card transactions so they're reachable from `CashFlowMapping.tsx`
- [ ] Seed rules cover common recurring merchants (subscriptions, groceries, transport, dining) well enough that `/categories/backfill` meaningfully reduces the "Uncategorized" bucket
- [ ] `LiabilitiesOverview.tsx`'s "Spend by category" donut shows multiple categories for any account with more than one real merchant type in its statement
- [ ] Backend tests cover: parser-level categorization (if Decision 1a), broadened `/categories/unmapped` filter, and backfill matching against the new seed rules
- [ ] `make verify` passes (lint + typecheck + test-backend + test-frontend)

## How To Test
- Import a credit card statement with varied merchants (dining, groceries, subscriptions, travel) and confirm `/spending/credit-card-transactions` returns more than one distinct `resolved_category`.
- Confirm previously "stuck" `CreditCard::Purchase` transactions now appear in `GET /categories/unmapped` (or are already resolved) so `CashFlowMapping.tsx` can act on them.
- Load `/liabilities` and confirm "Spend by category" renders a multi-segment donut with more than one legend row for a month with mixed spend.

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
- Next expected action: Prioritize and scope Decision 1 (parser-level vs. post-ingestion classification) before implementation — this determines whether the fix lives in the three existing parsers or as a shared categorization pass.
- Open questions:
  - Should merchant classification be rule/keyword-based (fast to ship, needs upkeep) or use an external categorization service/LLM call (more accurate, adds a dependency and cost)? This determines Decision 1's implementation shape.
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
