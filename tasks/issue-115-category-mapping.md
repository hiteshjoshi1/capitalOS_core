# Issue 115: Cash Flow Category Mapping + Overrides

## Objective

Implement backend-only category mapping so cash flow is no longer blocked by missing final categorization logic.

Backend-only human goals:
- Every cash-flow-relevant transaction can resolve to a final canonical category.
- Automatic mapping is rule-driven and deterministic.
- Manual override is supported at backend level and takes precedence over auto-mapping.
- Re-ingestion does not erase manual overrides.
- Unmapped transactions are explicitly discoverable via backend APIs.
- Category decision provenance is visible (rule-based vs manual vs parser).

Scope intent (backend only):
- Introduce canonical category taxonomy in backend.
- Add rule-based category mapping engine.
- Add persisted manual override capability and precedence logic.
- Add support to list unresolved/unmapped transactions.
- Add safe backfill path for existing transactions.
- Keep all existing API contracts backward compatible (additive changes only).

Backend-only human-verifiable checks:
- API can return unmapped transactions for a month/account set.
- API can apply a manual override to a transaction.
- After override, API returns the updated resolved category and source metadata.
- After re-ingesting the same source file, overridden transactions still return the same final category.
- API can show rule list and rule hit behavior.
- Existing spending/dashboard endpoints still return valid responses and do not regress.

Output requirement for implementation:
- At the end, provide exact `curl` commands (with sample IDs/placeholders) for:
  - listing unmapped transactions
  - creating/updating a mapping rule
  - applying a manual override
  - fetching transaction/category resolution state
  - proving override persistence after re-ingestion
- Include expected response snippets for each command so a human can verify quickly.

Safety constraints:
- No UI/frontend code changes in this issue.
- No fixture-specific hardcoding.
- No personal data committed.
- No unrelated file changes outside this issue scope.
- Keep diffs minimal and modular.

---

## Architecture Decisions

### Decision 1: Separate `category_overrides` table — not inline columns on `transactions`

The existing `transactions.category` column stores the raw parser-assigned category (e.g., `"Bank::Transaction"`, `"CreditCard::Purchase"`). This value is part of the duplicate-detection fingerprint in `runner.py` (lines 260–283) and must never be modified after ingestion.

Resolved categories live in a new `category_overrides` table with `UNIQUE(transaction_id)`. This guarantees:
- `transactions.category` remains immutable parser truth.
- Re-ingestion fingerprint is unchanged; overrides survive re-ingestion.
- Audit trail: each override records `source` (`'rule'` or `'manual'`) and optional `rule_id`.
- One canonical resolved category per transaction (UNIQUE constraint).

Resolution order: **manual override > rule override > parser category > `'Uncategorized'`**.

When both a manual and a rule override could apply, manual always wins. The override table stores whichever is active; applying a manual override replaces any prior rule-based entry.

### Decision 2: Category taxonomy as a reference table with hierarchy support

New `category_taxonomy` table with `parent_id` self-reference for two-level hierarchy. Seeded with sensible personal-finance defaults (Income, Housing, Food & Dining, Transportation, Shopping, Health, Entertainment, Financial, Taxes, Transfer, Uncategorized) plus common subcategories.

Rationale:
- Enforces valid category targets (FK from overrides and rules).
- Supports future UI autocomplete and budget features.
- `code` column provides stable programmatic keys; `name` column provides display labels.
- Hierarchy is optional — queries use `ct.name` for display regardless of depth.

### Decision 3: Compound-condition rules with AND semantics

`category_rules` table supports multiple optional match fields. All non-NULL conditions must match (AND logic). Fields:
- `merchant_pattern` — ILIKE on `transactions.merchant_counterparty`
- `description_pattern` — ILIKE on `transactions.notes`
- `source_category_pattern` — ILIKE on `transactions.category` (parser category)
- `txn_type` — exact match on `transactions.type`
- `min_amount` / `max_amount` — numeric range on `transactions.amount`

Priority field (lower number = higher priority) resolves conflicts when multiple rules match.

Rationale:
- Covers all practical matching needs without regex complexity.
- All matching executes as standard SQL (no Python-side evaluation needed).
- Deterministic: given the same data and rules, the same category is always assigned.

### Decision 4: Rule application via explicit backfill endpoint only (v1)

Rules are applied via `POST /categories/backfill` (idempotent). This endpoint:
1. Finds all transactions without a `source='manual'` override.
2. For each, evaluates all active rules in priority order.
3. Upserts into `category_overrides` with `source='rule'`.
4. Returns a count of created/updated overrides.

Ingestion (`runner.py`) is **not** modified in this issue. After ingesting new data, the user runs backfill to apply rules. This keeps the ingestion pipeline untouched and reduces risk.

Rationale:
- Minimal diff to existing ingestion code.
- Idempotent and safe to run repeatedly.
- Future enhancement: hook backfill into post-ingestion step.

### Decision 5: Spending queries updated to resolve via LEFT JOIN

The spending summary query (`/spending/summary`) and credit-card transaction query (`/spending/credit-card-transactions`) gain LEFT JOINs to `category_overrides` → `category_taxonomy`. The `COALESCE(ct.name, t.category, 'Uncategorized')` expression replaces the current `COALESCE(category, 'Uncategorized')`.

This is backward compatible:
- Schema unchanged (`CategoryAmount.category` is still `str`).
- With no overrides, behavior is identical (COALESCE falls through to parser category).
- With overrides, resolved category names appear automatically.

The `CreditCardTransactionItem` schema gains two **additive** optional fields: `resolved_category: str | None` and `category_source: str | None`.

### Decision 6: No modification to ingestion runner duplicate detection

The fingerprint in `runner.py` includes `COALESCE(category, '')`. Since `transactions.category` is never modified by this feature (overrides live in a separate table), re-ingestion of the same file produces the same fingerprint, skips duplicates, and all overrides (keyed by `transaction_id`) remain intact.

### Decision 7: Seed bridge rules for existing parser categories

The migration seeds initial rules mapping existing parser category patterns to canonical taxonomy entries:
- `Brokerage::Dividend` → Income > Dividends
- `Brokerage::Interest` → Income > Interest
- `Brokerage::Fee` → Financial > Investment Fees
- `Brokerage::Tax` → Taxes > Withholding Tax
- `Bank::Transfer` → Transfer > Internal Transfer
- `CreditCard::Payment` → Transfer > Credit Card Payment
- `Brokerage::Transfer` → Transfer > Brokerage Transfer

These use `source_category_pattern` exact match and serve as documentation of the mapping intent. Users can modify or add rules via the API.

---

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| 1 | LEFT JOINs on spending queries add latency for large transaction sets | Low | Medium | Index `category_overrides(transaction_id)` — single-column PK-like index makes JOIN near-free |
| 2 | Backfill on large transaction set is slow | Low | Low | Backfill is batched, runs as explicit POST, not on every request. Acceptable for personal-finance scale (<100K txns) |
| 3 | Rule priority conflicts produce unexpected categories | Medium | Medium | Deterministic priority ordering documented; API returns matched `rule_id` so user can debug. Rules endpoint shows all rules sorted by priority |
| 4 | Migration fails on existing database with data | Low | High | All DDL uses `IF NOT EXISTS` / `DO $$ ... EXCEPTION WHEN ...`. Seed data uses `INSERT ... ON CONFLICT DO NOTHING`. Migration is safe to re-run |
| 5 | Parser version change creates new transactions, old overrides orphaned | Low | Low | Override FK has `ON DELETE CASCADE` — if old transaction is somehow removed, override is cleaned up. Documented as known edge case |

---

## Open Questions

1. **Q: Should backfill auto-run after ingestion in a future issue?**
   Recommendation: Yes, add a post-ingestion hook in a follow-up issue. Not in scope here.

2. **Q: Should the taxonomy support more than two levels?**
   Recommendation: The `parent_id` schema supports arbitrary depth. Seed data uses two levels. No code limits depth.

3. **Q: Should rule deletion cascade to remove overrides that were created by that rule?**
   Recommendation: No. If a rule is deleted, existing overrides with that `rule_id` remain (they represent past decisions). The `rule_id` column is nullable and SET NULL on rule delete. User can re-run backfill to recompute.

---

## Acceptance Criteria

- [ ] AC-1: Migration `027_category_mapping.sql` creates `category_taxonomy`, `category_rules`, and `category_overrides` tables with correct constraints, indexes, and seed data.
- [ ] AC-2: `GET /categories` returns the full taxonomy list (flat, with parent_id for hierarchy).
- [ ] AC-3: `GET /categories/rules` returns all rules sorted by priority.
- [ ] AC-4: `POST /categories/rules` creates a new rule; returns the created rule with ID.
- [ ] AC-5: `PUT /categories/rules/{id}` updates an existing rule.
- [ ] AC-6: `DELETE /categories/rules/{id}` soft-deactivates a rule (sets `active=false`).
- [ ] AC-7: `GET /categories/unmapped?month=YYYY-MM` returns transactions that have no override and no parser category (or parser category = `'Uncategorized'`).
- [ ] AC-8: `POST /categories/override` applies a manual override to a specific transaction; returns the updated resolution state.
- [ ] AC-9: `GET /categories/resolve/{transaction_id}` returns the full resolution state: raw parser category, override category, source, rule_id.
- [ ] AC-10: `POST /categories/backfill` runs all active rules against transactions without manual overrides; returns counts of created/updated overrides.
- [ ] AC-11: `GET /spending/summary` uses resolved categories (override > parser > Uncategorized) without schema changes.
- [ ] AC-12: `GET /spending/credit-card-transactions` adds `resolved_category` and `category_source` fields (additive, nullable) to each transaction item.
- [ ] AC-13: Re-ingestion of same file does not erase manual overrides (verified by curl sequence).
- [ ] AC-14: `make api-rebuild` succeeds with zero import errors.
- [ ] AC-15: `curl http://localhost:8000/health` returns 200.
- [ ] AC-16: `curl http://localhost:8000/spending/summary?month=2026-02` returns valid JSON with no regression.
- [ ] AC-17: `curl http://localhost:8000/dashboard/summary?month=2026-02` returns valid JSON with no regression.

---

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Phase 1: Database Schema (Migration)
- [ ] Create `migrations/027_category_mapping.sql` with:
  - `category_taxonomy` table (id, code, name, parent_id, display_order, created_at)
  - `category_rules` table (id, name, priority, merchant_pattern, description_pattern, source_category_pattern, txn_type, min_amount, max_amount, target_category_id FK, active, created_at, updated_at)
  - `category_overrides` table (id, transaction_id UNIQUE FK CASCADE, category_id FK, source CHECK('rule','manual'), rule_id FK SET NULL, created_at, updated_at)
  - Index on `category_overrides(transaction_id)`
  - Seed taxonomy with two-level personal-finance categories
  - Seed bridge rules for existing parser categories
- [ ] Verify migration runs cleanly: `make db-migrate`

### Phase 2: SQLAlchemy Models
- [ ] Create `api/app/models/category.py` with:
  - `CategoryTaxonomy` model
  - `CategoryRule` model
  - `CategoryOverride` model
- [ ] Update `api/app/models/__init__.py` to import and export new models

### Phase 3: Pydantic Schemas
- [ ] Create `api/app/schemas/category.py` with:
  - `CategoryTaxonomyOut` — read schema
  - `CategoryRuleCreate` — write schema for rule creation
  - `CategoryRuleUpdate` — write schema for rule update
  - `CategoryRuleOut` — read schema
  - `CategoryOverrideCreate` — write schema (transaction_id, category_id)
  - `CategoryOverrideOut` — read schema
  - `CategoryResolutionOut` — full resolution state (transaction_id, raw_category, resolved_category, source, rule_id, rule_name)
  - `UnmappedTransactionOut` — transaction summary for unmapped list
  - `BackfillResultOut` — counts of created/updated

### Phase 4: Category Engine (Pure Functions)
- [ ] Create `api/app/category_engine.py` with:
  - `apply_rules(db, transaction_ids: list[int] | None) -> BackfillResult` — runs all active rules against specified transactions (or all non-manually-overridden), upserts overrides with `source='rule'`
  - `resolve_category(db, transaction_id: int) -> CategoryResolution` — returns full resolution state for a single transaction
  - Uses SQL-based matching (CROSS JOIN + WHERE conditions) for efficiency

### Phase 5: Router
- [ ] Create `api/app/routers/categories.py` with endpoints:
  - `GET /categories` — list taxonomy
  - `GET /categories/rules` — list rules
  - `POST /categories/rules` — create rule
  - `PUT /categories/rules/{id}` — update rule
  - `DELETE /categories/rules/{id}` — deactivate rule
  - `GET /categories/unmapped` — list unmapped transactions (query params: month, account_id optional)
  - `POST /categories/override` — apply manual override
  - `GET /categories/resolve/{transaction_id}` — get resolution state
  - `POST /categories/backfill` — run rule engine
- [ ] Register router in `api/app/main.py`

### Phase 6: Spending Router Updates (Additive)
- [ ] Update `api/app/routers/spending.py`:
  - `spending_summary` query: LEFT JOIN `category_overrides` + `category_taxonomy`, use `COALESCE(ct.name, t.category, 'Uncategorized')` for grouping
  - `credit_card_transactions` query: add same LEFT JOINs, populate `resolved_category` and `category_source` in response
- [ ] Update `api/app/schemas/spending.py`:
  - Add `resolved_category: str | None = None` and `category_source: str | None = None` to `CreditCardTransactionItem` (additive, optional)

### Phase 7: Verification
- [ ] `make api-rebuild` — container starts with no import errors
- [ ] `curl http://localhost:8000/health` — 200
- [ ] `curl http://localhost:8000/categories` — returns seeded taxonomy
- [ ] `curl http://localhost:8000/categories/rules` — returns seeded bridge rules
- [ ] `curl http://localhost:8000/spending/summary?month=2026-02` — valid JSON, no regression
- [ ] `curl http://localhost:8000/dashboard/summary?month=2026-02` — valid JSON, no regression
- [ ] Execute full verification curl sequence (see below)

### Phase 8: Verification Curl Commands
Provide tested curl commands for:
1. List all categories: `curl http://localhost:8000/categories`
2. List all rules: `curl http://localhost:8000/categories/rules`
3. Create a rule: `curl -X POST http://localhost:8000/categories/rules -H 'Content-Type: application/json' -d '{"name":"Grab rides","priority":50,"merchant_pattern":"%GRAB%","target_category_id":<TRANSPORT_SUBCATEGORY_ID>}'`
4. List unmapped transactions: `curl 'http://localhost:8000/categories/unmapped?month=2026-02'`
5. Run backfill: `curl -X POST http://localhost:8000/categories/backfill`
6. Apply manual override: `curl -X POST http://localhost:8000/categories/override -H 'Content-Type: application/json' -d '{"transaction_id":<TXN_ID>,"category_id":<CATEGORY_ID>}'`
7. Get resolution state: `curl http://localhost:8000/categories/resolve/<TXN_ID>`
8. Verify spending summary resolves: `curl 'http://localhost:8000/spending/summary?month=2026-02'`
9. Verify dashboard no regression: `curl 'http://localhost:8000/dashboard/summary?month=2026-02'`

---

## File Inventory

### New Files (5)
| File | Purpose |
|------|---------|
| `migrations/027_category_mapping.sql` | DDL + seed data for taxonomy, rules, overrides tables |
| `api/app/models/category.py` | SQLAlchemy models: CategoryTaxonomy, CategoryRule, CategoryOverride |
| `api/app/schemas/category.py` | Pydantic request/response schemas for category endpoints |
| `api/app/category_engine.py` | Pure-function rule engine: apply_rules, resolve_category |
| `api/app/routers/categories.py` | FastAPI router with all /categories/* endpoints |

### Modified Files (4)
| File | Change |
|------|--------|
| `api/app/models/__init__.py` | Add imports for CategoryTaxonomy, CategoryRule, CategoryOverride |
| `api/app/main.py` | Register categories_router |
| `api/app/routers/spending.py` | LEFT JOIN overrides in summary + cc-transactions queries |
| `api/app/schemas/spending.py` | Add resolved_category, category_source to CreditCardTransactionItem |

**Total: 9 files touched (5 new, 4 modified)**

---

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-115-category-mapping.md
make task-build TASK=tasks/issue-115-category-mapping.md
make task-review TASK=tasks/issue-115-category-mapping.md
make task-rework TASK=tasks/issue-115-category-mapping.md
make task-ship TASK=tasks/issue-115-category-mapping.md
```
