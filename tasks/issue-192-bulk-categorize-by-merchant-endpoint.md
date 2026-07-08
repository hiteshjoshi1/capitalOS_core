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
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
