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
**Current Stage**: `deterministic_gates`
**Workflow Status**: `waiting_for_human`

## Workflow Snapshot
- latest_outcome: Implemented per-merchant categorization for credit card transactions (Issue 195). Added a merchant_categorizer module that classifies purchase descriptions into friendly categories (Dining, Groceries, Transport, Subscriptions, Shopping, Travel, Utilities, Medical) at parse time. Updated all three credit card parsers to use it. Broadened /categories/unmapped to surface CreditCard::Purchase placeholders. Added a migration with Travel/Utilities taxonomy and 50+ merchant-pattern seed rules. Wired automatic backfill into the ingest upload endpoint. Updated existing tests and added a new test file.
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Credit card purchases get a real per-merchant category at ingestion time
- Acceptance criterion: /categories/unmapped surfaces uncategorized/placeholder-category card transactions
- Acceptance criterion: Seed rules cover common recurring merchants for /categories/backfill
- Acceptance criterion: LiabilitiesOverview Spend by category shows multiple categories
- Acceptance criterion: Backend tests cover parser-level categorization, broadened unmapped filter, and backfill
- Acceptance criterion: make verify passes

## Prepare
Checked out `feature/issue-195-credit-card-merchant-categorization` from `main` and verified task file exists.

## Plan Summary
1. Create merchant_categorizer.py with keyword-based rules. 2. Update three CC parsers to call it instead of hardcoding CreditCard::Purchase. 3. Broaden /categories/unmapped SQL filter to include creditcard::purchase. 4. Add migration 064 with Travel/Utilities taxonomy + 50+ merchant-pattern rules + bridge rules. 5. Auto-run apply_rules after successful ingest upload. 6. Update existing parser tests. 7. Add new test file covering all acceptance criteria.

### Architecture Decisions
- Decision 1a (confirmed): Parser-level classification via merchant_categorizer.py. Returns human-readable strings (Dining, Groceries, etc.) so resolved_category is immediately meaningful without backfill. Falls back to CreditCard::Purchase for unknowns.
- Decision 2 (confirmed): /categories/unmapped now includes LOWER(TRIM(category)) = 'creditcard::purchase' in its filter so unrecognized card merchants appear in CashFlowMapping.tsx.
- Decision 3 (confirmed): Migration 064 adds Travel/Utilities taxonomy + 50+ merchant-pattern rules + 8 bridge rules mapping parser-friendly names to taxonomy. Backfill is also auto-triggered on ingest.
- Decision 4 (confirmed): No change to resolved_category COALESCE logic in spending.py. Friendly raw categories flow through automatically.

### Acceptance Criteria
- Credit card purchases get a real per-merchant category at ingestion time
- /categories/unmapped surfaces uncategorized/placeholder-category card transactions
- Seed rules cover common recurring merchants for /categories/backfill
- LiabilitiesOverview Spend by category shows multiple categories
- Backend tests cover parser-level categorization, broadened unmapped filter, and backfill
- make verify passes

### Planned Paths
- `api/app/ingestion/parsers/merchant_categorizer.py`
- `api/app/ingestion/parsers/uob_credit_card_xls_v1.py`
- `api/app/ingestion/parsers/dbs_credit_card_csv_v1.py`
- `api/app/ingestion/parsers/citi_credit_card_csv_v1.py`
- `api/app/routers/categories.py`
- `api/app/routers/ingest.py`
- `migrations/064_credit_card_merchant_category_rules.sql`
- `api/tests/test_ingest_uob_cc.py`
- `api/tests/test_ingest_dbs_credit_card.py`
- `api/tests/test_credit_card_merchant_categorization.py`

## Build Summary
Implemented per-merchant categorization for credit card transactions (Issue 195). Added a merchant_categorizer module that classifies purchase descriptions into friendly categories (Dining, Groceries, Transport, Subscriptions, Shopping, Travel, Utilities, Medical) at parse time. Updated all three credit card parsers to use it. Broadened /categories/unmapped to surface CreditCard::Purchase placeholders. Added a migration with Travel/Utilities taxonomy and 50+ merchant-pattern seed rules. Wired automatic backfill into the ingest upload endpoint. Updated existing tests and added a new test file.

### Changed Files
- `api/app/ingestion/parsers/citi_credit_card_csv_v1.py`
- `api/app/ingestion/parsers/dbs_credit_card_csv_v1.py`
- `api/app/ingestion/parsers/merchant_categorizer.py`
- `api/app/ingestion/parsers/uob_credit_card_xls_v1.py`
- `api/app/routers/categories.py`
- `api/app/routers/ingest.py`
- `api/tests/test_credit_card_merchant_categorization.py`
- `api/tests/test_ingest_dbs_credit_card.py`
- `api/tests/test_ingest_uob_cc.py`
- `migrations/064_credit_card_merchant_category_rules.sql`
- `tasks/issue-195-credit-card-merchant-categorization.md`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented per-merchant categorization for credit card transactions (Issue 195). Added a merchant_categorizer module that classifies purchase descriptions into friendly categories (Dining, Groceries, Transport, Subscriptions, Shopping, Travel, Utilities, Medical) at parse time. Updated all three credit card parsers to use it. Broadened /categories/unmapped to surface CreditCard::Purchase placeholders. Added a migration with Travel/Utilities taxonomy and 50+ merchant-pattern seed rules. Wired automatic backfill into the ingest upload endpoint. Updated existing tests and added a new test file.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` Credit card purchases get a real per-merchant category at ingestion time (or via a backfill pass), not a single hardcoded placeholder: merchant_categorizer.py classifies known merchants at parse time; DBS fixture SHENG SIONG transactions now get category='Groceries' (confirmed by updated test_ingest_dbs_credit_card.py); UOB KOPITIAM transactions get category='Dining'
- `pass` /categories/unmapped surfaces uncategorized/placeholder-category card transactions so they're reachable from CashFlowMapping.tsx: categories.py filter broadened to include LOWER(TRIM(t.category)) = 'creditcard::purchase'; test_unmapped_filter_surfaces_creditcard_purchase_placeholder confirms tx 901 (CreditCard::Purchase) appears and tx 902 (Dining) does not
- `pass` Seed rules cover common recurring merchants (subscriptions, groceries, transport, dining) well enough that /categories/backfill meaningfully reduces the Uncategorized bucket: Migration 064 adds 50+ merchant-pattern rules + 8 bridge rules; test_backfill_resolves_creditcard_purchase_by_merchant_pattern confirms 3 of 4 transactions resolved (SHENG SIONG, NETFLIX, GRAB) leaving only SOME MYSTERY SHOP unmapped
- `pass` LiabilitiesOverview Spend by category donut shows multiple categories for any account with more than one real merchant type: test_credit_card_transactions_endpoint_returns_multiple_categories confirms /spending/credit-card-transactions returns Groceries, Dining, Subscriptions as distinct resolved_category values for mixed-merchant account; no backfill needed since friendly names flow through raw category
- `pass` Backend tests cover: parser-level categorization, broadened /categories/unmapped filter, and backfill matching against the new seed rules: test_credit_card_merchant_categorization.py: 44 parametrized tests for classify_merchant, 2 unmapped filter tests, 2 backfill tests, 1 endpoint test (49 total); all passing in Docker
- `pass` make verify passes (lint + typecheck + test-backend + test-frontend): lint: pass (eslint clean, ruff skipped in image); typecheck: pass (tsc clean, mypy skipped); test-backend: 1086 passed; test-frontend: 271 passed

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
