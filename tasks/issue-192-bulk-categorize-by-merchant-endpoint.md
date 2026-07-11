# Issue 192: Atomic bulk-categorize-by-merchant endpoint

## Objective
- Replace the frontend per-transaction loop used by the Cash Flow → Map Transactions "Apply to all N" action with a single atomic backend endpoint, so a merchant-group bulk categorize is one DB transaction instead of N sequential HTTP calls.

## Current State
- `POST /categories/override` (`routers/categories.py`) sets a category override for exactly one `transaction_id`.
- As part of the CapitalOS Wealth screens design-handoff implementation, the Map Transactions screen (`web/src/routes/CashFlowMapping.tsx`) groups unmapped transactions by `merchant_counterparty` client-side and implements "Apply to all N" by calling `POST /categories/override` once per transaction in the group, in a loop, awaiting each call. This works and persists real data, but:
  - it's N round-trips instead of 1,
  - it's not atomic — a failure partway through a large group leaves some transactions categorized and others not, with no rollback,
  - it doesn't scale well for merchants with a large transaction count.

## Architecture Decisions
- New endpoint, e.g. `POST /categories/override-bulk`, accepting `{ transaction_ids: number[], category: string }` (or `{ merchant_counterparty: string, month: string, category: string }` if grouping should happen server-side instead of client-side — pick whichever matches how `unmapped` transactions are already queried/filtered in `routers/categories.py`).
- Wrap all row updates in a single DB transaction; return per-id success/failure detail so the frontend can reconcile partial failures if the DB layer allows partial commits (or make it strictly all-or-nothing — decide based on existing `category_overrides` write patterns).
- Frontend `CashFlowMapping.tsx`'s "Apply to all" handler should switch from the loop to this single call once available.

## Acceptance Criteria
- [ ] New bulk endpoint implemented, tested, documented (OpenAPI via `make openapi` if applicable).
- [ ] Applying a category to a 20+ transaction merchant group is a single request.
- [ ] Frontend updated to use the new endpoint instead of the loop.
- [ ] Existing single-transaction `POST /categories/override` behavior is unchanged (still used by inline per-row overrides elsewhere, e.g. `CashFlowDetail.tsx`'s transaction tables).

## How To Test
- Run `make test-backend` and confirm new bulk-endpoint tests pass (happy path, partial-failure path if applicable, empty list).
- Run `make test-frontend` and confirm `CashFlowMapping.test.tsx`'s bulk-apply test passes against the new endpoint.
- Manual: `curl` the new endpoint with a batch of transaction ids and confirm all rows update in one request.

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
- Last Updated: `<timestamp>`

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
- Stop reason: `Not started — filed from design-handoff implementation pass (2026-07-08) as a follow-up efficiency/atomicity improvement, not a functional blocker (working interim already shipped).`
- Attempted mitigations:
  - `Frontend interim: bulk-apply implemented as a client-side loop over the existing single-transaction override endpoint — functionally complete, just not atomic/efficient at scale.`
- Suggested human action: `Prioritize based on real merchant-group sizes seen in production; low urgency if groups stay small (<20 transactions).`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Schedule for implementation when convenient; not blocking.`
- Open questions:
  - `Should this group server-side by merchant_counterparty+month, or just accept an explicit transaction_id list from the frontend?`
- If PR raised but intent partial:
  - unmet criteria: `n/a — not started`
  - follow-up issue: `n/a`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-192-bulk-categorize-by-merchant-endpoint`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: New bulk endpoint implemented, tested, documented (OpenAPI via FastAPI auto-docs).
- Acceptance criterion: Applying a category to a merchant group is a single request.
- Acceptance criterion: Frontend updated to use the new endpoint instead of the loop.
- Acceptance criterion: Existing single-transaction POST /categories/override behavior is unchanged.

## Prepare
Checked out `feature/issue-192-bulk-categorize-by-merchant-endpoint` from `main` and verified task file exists.

## Plan Summary
1. Add CategoryOverrideBulkCreate/Out schemas. 2. Add POST /categories/override-bulk endpoint using IN-clause validation + single-commit loop upsert (SQLite+PG compatible). 3. Add CategoryOverrideBulkPayload/Result types in api.ts + categoryOverrideBulk method. 4. Replace handleApplyAll loop in CashFlowMapping.tsx with single bulk call. 5. Add 6 backend tests + update frontend test. 6. Run full verification suite.

### Architecture Decisions
- Endpoint accepts { transaction_ids: number[], category_id: int } (explicit IDs from frontend, not server-side merchant grouping) — matches existing client-side grouping already in place.
- All-or-nothing atomic semantics: loop upserts inside a single SQLAlchemy transaction, single db.commit() at the end.
- ON CONFLICT (transaction_id) DO UPDATE used for upsert — compatible with both PostgreSQL (production) and SQLite (test).
- Batch ownership validation via dynamic IN-clause (compatible with SQLite and PostgreSQL) before any writes.
- Existing POST /categories/override endpoint is unchanged — still used by CashFlowDetail inline per-row overrides.

### Acceptance Criteria
- New bulk endpoint implemented, tested, documented (OpenAPI via FastAPI auto-docs).
- Applying a category to a merchant group is a single request.
- Frontend updated to use the new endpoint instead of the loop.
- Existing single-transaction POST /categories/override behavior is unchanged.

### Planned Paths
- `api/app/routers/categories.py`
- `api/app/schemas/category.py`
- `api/tests/test_categories.py`
- `web/src/lib/api.ts`
- `web/src/routes/CashFlowMapping.tsx`
- `web/src/__tests__/CashFlowMapping.test.tsx`

## Build Summary
Implemented atomic bulk-categorize-by-merchant endpoint (POST /categories/override-bulk). Backend: new Pydantic schemas + endpoint wrapping all upserts in one DB commit. Frontend: new API types + method, CashFlowMapping handler replaced loop with single bulk call. Tests: 6 new backend tests (happy path, empty list, invalid IDs, invalid category, idempotency, single-endpoint regression) + frontend test updated to verify single bulk call instead of loop.

### Changed Files
- `api/app/routers/categories.py`
- `api/app/schemas/category.py`
- `api/tests/test_categories.py`
- `tasks/issue-192-bulk-categorize-by-merchant-endpoint.md`
- `web/src/__tests__/CashFlowMapping.test.tsx`
- `web/src/lib/api.ts`
- `web/src/routes/CashFlowMapping.tsx`

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
Implemented atomic bulk-categorize-by-merchant endpoint (POST /categories/override-bulk). Backend: new Pydantic schemas + endpoint wrapping all upserts in one DB commit. Frontend: new API types + method, CashFlowMapping handler replaced loop with single bulk call. Tests: 6 new backend tests (happy path, empty list, invalid IDs, invalid category, idempotency, single-endpoint regression) + frontend test updated to verify single bulk call instead of loop.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` New bulk endpoint implemented, tested, documented (OpenAPI via make openapi if applicable).: POST /categories/override-bulk added to categories.py with full Pydantic schema; auto-documented via FastAPI OpenAPI at /docs. 6 new backend tests all pass.
- `pass` Applying a category to a 20+ transaction merchant group is a single request.: handleApplyAll in CashFlowMapping.tsx now calls api.categoryOverrideBulk({transaction_ids, category_id}) — one HTTP call regardless of group size. Backend wraps all upserts in one db.commit().
- `pass` Frontend updated to use the new endpoint instead of the loop.: Loop over api.categoryOverride removed; replaced with single api.categoryOverrideBulk call. Frontend test verifies categoryOverrideBulk called once with all IDs and categoryOverride not called.
- `pass` Existing single-transaction POST /categories/override behavior is unchanged (still used by inline per-row overrides).: POST /categories/override endpoint code unmodified. test_bulk_override_does_not_affect_single_override_endpoint passes. CashFlowDetail.tsx unchanged.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-192-bulk-categorize-by-merchant-endpoint`.
<!-- MACHINE_RENDERED_END -->
