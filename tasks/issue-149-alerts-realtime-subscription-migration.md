# Issue 149: Alerts realtime subscription migration

## Objective
- Move the Alerts experience onto the shared realtime notification service rather than standalone request/response loading.
- Make alert badges and the Alerts page reflect backend-driven updates without polling.
- Reuse the same durable event model and websocket transport introduced for realtime ingestion events.

## Architecture Decisions
- Decision 1: Alerts should consume the shared realtime service introduced for issue 148, not build a second transport mechanism.
- Decision 2: Alerts remain backend-authored and user-scoped; the frontend should render server-derived state and server-emitted changes.
- Decision 3: No polling loops should be introduced for alert counts or alert-page refresh behavior.
- Decision 4: The sidebar badge and Alerts page should both hydrate from durable backend state on first load and then stay fresh through websocket events.

## Acceptance Criteria
- [ ] The Alerts page hydrates from backend state and then stays updated through the shared websocket service.
- [ ] The sidebar alert badge uses the shared realtime service rather than one-off fetch-only logic for freshness.
- [ ] Alert-related websocket events are user-scoped and durable enough that a returning user can still see the latest alert state after reconnecting.
- [ ] No polling is introduced for alert count refresh or alert-page updates.
- [ ] The existing Alerts API contract remains compatible for initial load/backfill use.
- [ ] Tests cover alert badge updates, Alerts page updates, reconnect/reload behavior, and absence of polling timers.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not_started`
- Workflow Status: `running`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-22`

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
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
