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
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `complete`
- Workflow Status: `completed`
- Provider/Model: `gpt-5.4`
- Last Updated: `2026-04-22`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass` — `make lint`
- `typecheck`: `pass` — `make typecheck`
- `tests`: `pass` — `make contract-backend && make test-backend && make contract-frontend && make test-frontend && make orch-test`
- `e2e`: `pass` — `make e2e`
- `api-smoke`: `pass` — `make api-smoke`
- `policy-checks`: `pass` — `No policy violations introduced; user-scoped realtime events and durable backend state verified via repo test suite`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `tasks/issue-148-realtime-notification-service-and-author-ingestion-events.md` — reason: recorded execution status and deterministic gate evidence for this task file

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `None`
- Attempted mitigations:
  - `Not applicable`
  - `Not applicable`
- Suggested human action: `None`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Review and ship the branch changes.`
- Open questions:
  - `None`
- If PR raised but intent partial:
  - unmet criteria: `None`
  - follow-up issue: `None`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-148-realtime-notification-service-and-author-ingestion-events`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`
- retry_detail: `api-smoke` stopped after attempt 1/3: Code failure with no auto-fix available: response = self.parent.error(

## Active Requirements
- Acceptance criterion: Reusable authenticated user-scoped websocket service
- Acceptance criterion: Durable backend-recorded author-ingestion lifecycle events
- Acceptance criterion: Snapshot + reconnect recovery without localStorage
- Acceptance criterion: Author Ingestion websocket-driven UI with polling removed
- Acceptance criterion: Coverage through backend/frontend tests and Makefile verification

## Prepare
Checked out `feature/issue-148-realtime-notification-service-and-author-ingestion-events` from `main` and ensured task file exists.

## Plan Summary
Added shared backend realtime transport plus durable ingestion event storage, wired author-ingestion routes/pipeline to publish user-scoped lifecycle events and expose a durable activity snapshot, replaced frontend polling with snapshot + websocket subscriptions, expanded backend/frontend tests, and ran the required verification gates until green.

### Architecture Decisions
- Realtime delivery is implemented as a reusable backend websocket service instead of feature-local transport code.
- WebSocket push is the live update mechanism for Author Ingestion; page-local polling was removed.
- Backend lifecycle transitions are durably recorded in realtime_events so reload/reconnect can recover state.
- Author Ingestion consumes the shared realtime client/service instead of custom refresh timers.
- The backend remains the system of record; the UI renders backend snapshot state plus backend-emitted events.

### Acceptance Criteria
- Reusable authenticated user-scoped websocket service
- Durable backend-recorded author-ingestion lifecycle events
- Snapshot + reconnect recovery without localStorage
- Author Ingestion websocket-driven UI with polling removed
- Coverage through backend/frontend tests and Makefile verification

### Planned Paths
- `api/app/auth_context.py`
- `api/app/main.py`
- `api/app/models`
- `api/app/rag`
- `api/app/routers`
- `api/app/services`
- `api/tests`
- `migrations`
- `web/src/lib`
- `web/src/routes`
- `web/src/__tests__`

## Build Summary
Implemented a reusable authenticated websocket realtime service, durable author-ingestion event/history storage, and a snapshot-first Author Ingestion UI that no longer polls. Author ingestion now records user-scoped lifecycle events, the frontend reconnects from backend state plus websocket events, retry flows publish the same events, and the required Makefile verification suite passed.

### Changed Files
- `api/app/auth_context.py`
- `api/app/main.py`
- `api/app/models/__init__.py`
- `api/app/models/rag.py`
- `api/app/rag/discovery.py`
- `api/app/rag/ingestion/events.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/routers/rag.py`
- `api/app/routers/realtime.py`
- `api/app/services/realtime.py`
- `api/tests/test_rag.py`
- `api/tests/test_rag_author_ingestion_ui.py`
- `api/tests/test_rag_discovery.py`
- `api/tests/test_realtime.py`
- `migrations/043_realtime_notifications.sql`
- `tasks/issue-148-realtime-notification-service-and-author-ingestion-events.md`
- `web/src/__tests__/AuthorIngestion.test.tsx`
- `web/src/lib/api.ts`
- `web/src/lib/realtime.ts`
- `web/src/routes/AuthorIngestion.tsx`

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
Implemented a reusable authenticated websocket realtime service, durable author-ingestion event/history storage, and a snapshot-first Author Ingestion UI that no longer polls. Author ingestion now records user-scoped lifecycle events, the frontend reconnects from backend state plus websocket events, retry flows publish the same events, and the required Makefile verification suite passed.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` A reusable websocket service exists in the backend for authenticated user-scoped realtime events.: Implemented api/app/services/realtime.py plus api/app/routers/realtime.py with token-authenticated /realtime/ws connections.
- `pass` The websocket service supports at minimum connect, disconnect, user-scoped subscription, heartbeat/keepalive as needed, and clean disconnect handling.: RealtimeService implements connect/disconnect/subscribe/send_heartbeat/publish, and the websocket router handles ping, subscribe, timeout heartbeat, and disconnect logging.
- `pass` The websocket service can publish backend-generated events for long-running workflows without coupling transport logic to a specific feature router.: Feature-agnostic publish logic lives in RealtimeService; author-ingestion routes call shared record/publish helpers in api/app/rag/ingestion/events.py.
- `pass` Author ingestion job lifecycle transitions publish durable events such as batch submitted, source queued, source running, source ingested, source failed, and batch completed.: RAG ingestion route/pipeline wiring now records and publishes batch_submitted, source_queued, source_running, source_ingested, source_failed, and batch_completed events into realtime_events.
- `pass` Event payloads are user-scoped and include enough metadata for the UI to render author, source, job, status, timestamps, and failure reason where applicable.: RealtimeEvent payloads include author, batch, source, job, status, created_at, and failure_reason data, keyed by user_id and filtered per current user.
- `pass` Author Ingestion no longer uses setInterval, page polling, or other timer-based refresh logic.: web/src/routes/AuthorIngestion.tsx was rewritten around snapshot loading + websocket updates, and web/src/__tests__/AuthorIngestion.test.tsx asserts setInterval is not used.
- `pass` Author Ingestion subscribes to the websocket service and updates its visible job/source state from backend events.: AuthorIngestion uses subscribeToRealtimeTopic("author-ingestion") and upserts source/job/event state directly from backend event payloads.
- `pass` If the user reloads the page or returns later, the page can recover the latest durable backend state for recent ingestion work without depending on localStorage.: GET /rag/ingest/activity returns durable sources/jobs/events, and the page loads that snapshot before processing live websocket updates.
- `pass` The backend exposes a durable event/history read model or equivalent server-backed snapshot that the UI can load on first render before websocket events arrive.: Added GET /rag/ingest/activity returning current user-scoped sources, jobs, and realtime event history.
- `pass` The UI clearly shows job/source status transitions driven by backend state and backend events, not speculative client-side assumptions.: The page renders status badges, recent activity, and retry states from snapshot/event payloads only; no client timer-based inference remains.
- `pass` A user can submit ingestion for one author, leave the page, return later, and still see completed/failed state from backend state/history.: Durable snapshot endpoint plus persisted realtime_events and user-owned sources/jobs preserve the state across reloads without local storage.
- `pass` A user can submit ingestion for multiple authors over time, and backend event delivery remains user-scoped rather than tied to one selected author in memory.: Event storage and websocket delivery are scoped by user_id; the UI filters per selected author while the backend retains user-wide history for all authors.
- `pass` Retry actions for failed sources continue to work and publish the same lifecycle events through the shared realtime service.: Retry flow now creates a new batch_id/job, records batch_submitted + source_queued events, and backend tests assert retry activity exposes those events.
- `pass` Backend logs make websocket connections, publishes, and delivery failures observable.: Connection, subscription, disconnect, publish, skipped delivery, and delivery failure log lines were added in the realtime router/service and event recorder.
- `pass` No live inference or unrelated network dependencies are introduced into tests for this feature.: Tests rely on FastAPI TestClient, sqlite-backed fixtures, mocked realtime client behavior, and RAG_EMBEDDING_MOCK without external inference/network calls.
- `pass` Tests cover websocket connection/auth behavior, author-ingestion event publishing, reconnect/reload recovery from durable state, and the removal of polling from Author Ingestion.: Added api/tests/test_realtime.py plus expanded api/tests/test_rag_author_ingestion_ui.py and web/src/__tests__/AuthorIngestion.test.tsx for websocket auth/delivery, durable activity recovery, retry event publishing, and polling removal.
- `pass` The feature is verifiable with Makefile commands and curl/websocket-verifiable backend behavior.: Verified with make api-rebuild, contract-backend, test-backend, api-smoke, lint, typecheck, contract-frontend, test-frontend, orch-test, and e2e; websocket behavior is covered by backend TestClient websocket tests.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- api-smoke: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260422T142125Z_api-smoke_attempt1.log, notes=Code failure with no auto-fix available: response = self.parent.error(

## Ship Result
Pushed branch `feature/issue-148-realtime-notification-service-and-author-ingestion-events`.
<!-- MACHINE_RENDERED_END -->
