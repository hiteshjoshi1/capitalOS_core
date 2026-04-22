# Issue 148: Realtime notification service and author ingestion events

## Objective
- Replace page-local polling for long-running author ingestion jobs with durable backend-recorded events plus push-based frontend updates.
- Build a reusable websocket-based realtime notification service that feature areas can publish to and subscribe to.
- Make Author Ingestion operationally robust even when the user leaves the page and returns later.

## Architecture Decisions
- Decision 1: Realtime delivery must be built as a reusable backend service, not embedded directly inside the Author Ingestion route or component.
- Decision 2: WebSocket transport is the live-update mechanism; polling must be removed from Author Ingestion.
- Decision 3: Realtime delivery is not enough by itself. Backend job/source lifecycle transitions must also be durably recorded so users can reconnect later and still see what happened.
- Decision 4: Author Ingestion should consume the shared realtime service rather than owning custom refresh logic.
- Decision 5: The backend remains the system of record for ingestion lifecycle. The frontend should render backend state and backend-emitted events, not infer status from local timers.

## Acceptance Criteria
- [ ] A reusable websocket service exists in the backend for authenticated user-scoped realtime events.
- [ ] The websocket service supports at minimum connect, disconnect, user-scoped subscription, heartbeat/keepalive as needed, and clean disconnect handling.
- [ ] The websocket service can publish backend-generated events for long-running workflows without coupling transport logic to a specific feature router.
- [ ] Author ingestion job lifecycle transitions publish durable events such as batch submitted, source queued, source running, source ingested, source failed, and batch completed.
- [ ] Event payloads are user-scoped and include enough metadata for the UI to render author, source, job, status, timestamps, and failure reason where applicable.
- [ ] Author Ingestion no longer uses `setInterval`, page polling, or other timer-based refresh logic.
- [ ] Author Ingestion subscribes to the websocket service and updates its visible job/source state from backend events.
- [ ] If the user reloads the page or returns later, the page can recover the latest durable backend state for recent ingestion work without depending on localStorage.
- [ ] The backend exposes a durable event/history read model or equivalent server-backed snapshot that the UI can load on first render before websocket events arrive.
- [ ] The UI clearly shows job/source status transitions driven by backend state and backend events, not speculative client-side assumptions.
- [ ] A user can submit ingestion for one author, leave the page, return later, and still see completed/failed state from backend state/history.
- [ ] A user can submit ingestion for multiple authors over time, and backend event delivery remains user-scoped rather than tied to one selected author in memory.
- [ ] Retry actions for failed sources continue to work and publish the same lifecycle events through the shared realtime service.
- [ ] Backend logs make websocket connections, publishes, and delivery failures observable.
- [ ] No live inference or unrelated network dependencies are introduced into tests for this feature.
- [ ] Tests cover websocket connection/auth behavior, author-ingestion event publishing, reconnect/reload recovery from durable state, and the removal of polling from Author Ingestion.
- [ ] The feature is verifiable with Makefile commands and curl/websocket-verifiable backend behavior.

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
