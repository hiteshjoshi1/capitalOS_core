# Issue 186: Observability phase 3 - operational job logs, DB visibility, sampling, and Grafana views

## Objective
- Add operational logging for background jobs, slow DB queries, and noisy high-frequency event categories.
- Make IBKR Flex, quote refresh, upload ingestion, snapshots, RAG ingestion, and slow dashboard queries easy to trace in Loki/Grafana.
- Add Grafana saved queries or dashboards for the flows that matter most in day-to-day CapitalOS operation.

## Dependencies
- Issue 184 should provide Loki, Grafana, Alloy, and `make observability-smoke`.
- Issue 185 should provide logfmt formatting, `capitalos.*` loggers, redaction, and request context propagation.

## Current State
- Scheduler/background jobs do not consistently expose a per-run correlation ID.
- IBKR Flex refresh, quote refresh, uploads, snapshots, and RAG ingestion logs cannot reliably be queried as one lifecycle batch.
- SQLAlchemy slow queries, connection errors, pool timeout/exhaustion, and rollback failures are not logged as structured operational events.
- High-frequency event categories can make Loki noisy if logged unsafely.
- Grafana has no CapitalOS-specific saved views for important operational flows.

## Architecture Decisions
- Every background job run should include a synthetic UUID `job_id`.
- Job lifecycle logs must use stable event names:
  - `event=ibkr_flex_refresh_started|succeeded|failed`
  - `event=quote_refresh_started|succeeded|failed`
  - `event=upload_ingest_started|succeeded|failed`
  - `event=snapshot_created|failed`
  - `event=rag_ingest_started|succeeded|failed`
- Warnings and errors must never be sampled.
- Sampling is allowed only for explicitly marked high-frequency info/debug events.
- DB observability must never log bind parameter values, raw account numbers, raw uploaded rows, or full SQL containing personal data.
- Grafana views should be useful immediately, but full dashboard polish is secondary to correct queries and searchable fields.

## Configuration Plan
- Add env defaults:
  - `DB_SLOW_QUERY_MS=500`
  - `LOG_SAMPLE_RATE_HIGH_FREQ=0.10`
- If Issue 185 introduced a central logging config file, add these values there.
- Keep these values configurable without code changes.

## Operational Job Logging Plan
- Add a job context helper:
  - create UUID `job_id` at the start of each run,
  - store it in a context variable for all logs emitted during the run,
  - include it in logfmt fields.
- Wire job context into:
  - IBKR Flex scheduler and manual refresh path,
  - quote refresh scheduler and manual refresh path,
  - upload ingestion runner in `api/app/ingestion/runner.py`,
  - snapshot creation flow,
  - RAG ingestion/background processing.
- In `api/app/ingestion/runner.py`, explicitly log structured lifecycle events for non-exception terminal states:
  - `event=upload_ingest_failed` at WARNING level whenever the runner returns `status=FAILED`, including the current branches that return HTTP 200 with a failed JSON body,
  - `event=upload_ingest_needs_mapping` at WARNING level when the runner returns `status=NEEDS_MAPPING`,
  - include job_id, job database id, parser key/signature when safe, platform when known, error_class or reason category, and duration_ms,
  - do not log raw uploaded file contents or statement rows.
- Include consistent fields where relevant:
  - job_id,
  - provider,
  - platform,
  - rows,
  - duration_ms,
  - stale/fresh decision,
  - inserted/updated/skipped counts,
  - error_class,
  - retry_count.

## Database Observability Plan
- Wire SQLAlchemy slow-query instrumentation in `api/app/db/session.py`, where the engine/session factory is created.
- Use SQLAlchemy event hooks on the application engine:
  - `event.listen(engine, "before_cursor_execute", ...)`
  - `event.listen(engine, "after_cursor_execute", ...)`
- Log `event=db_slow_query` on logger `capitalos.db` at WARNING level when duration exceeds `DB_SLOW_QUERY_MS`.
- Do not create a duplicate engine or session factory for logging.
- Log DB connection errors, pool timeout/exhaustion, and transaction rollback failures with structured fields.
- Prefer safe fields:
  - operation,
  - table when safely known,
  - duration_ms,
  - row_count when available,
  - error_class.
- Do not log bind parameter values or full SQL containing personal data.

## Sampling Plan
- Add a small sampling helper for high-frequency categories.
- Use `LOG_SAMPLE_RATE_HIGH_FREQ` only for explicitly marked noisy info/debug events.
- Candidate categories:
  - WebSocket heartbeat/tick events,
  - verbose RAG trace internals,
  - repeated real-time price tick logs.
- Do not sample:
  - request summary logs,
  - scheduler job lifecycle logs,
  - warnings,
  - errors,
  - security logs,
  - upload ingestion outcomes,
  - quote refresh outcomes,
  - IBKR Flex outcomes,
  - snapshot creation outcomes.

## Grafana Views
- Provision saved queries or dashboards for:
  - Recent API errors and warnings.
  - Request latency by route/logger.
  - Slow DB queries.
  - IBKR Flex refresh lifecycle by `job_id`.
  - Quote refresh lifecycle by `job_id`.
  - Upload ingestion lifecycle by `job_id`.
  - Snapshot creation outcomes.
  - RAG ingestion failures.
- Each view should use Loki queries against low-cardinality labels plus logfmt fields, not high-cardinality labels.

## Testing Plan
- Unit test `job_id` context creation and propagation.
- Focused tests for lifecycle log fields in at least IBKR Flex and quote refresh paths.
- Unit test slow-query logger does not include bind parameter values.
- Unit test sampling never samples warnings/errors.
- Smoke check against Loki/Grafana when the issue 184 stack is running.

## Acceptance Criteria
- [ ] Background scheduler logs include a per-run `job_id` for IBKR Flex, quote refresh, upload ingestion, snapshot, and RAG ingestion jobs.
- [ ] Job lifecycle events use stable event names and include duration, status, rows/counts where available, provider/platform where relevant, and error class on failure.
- [ ] Upload ingestion runner logs WARNING events for both `FAILED` and `NEEDS_MAPPING` JSON-result branches, not only exception paths or happy paths.
- [ ] Slow DB queries emit `event=db_slow_query` at WARNING level when they exceed `DB_SLOW_QUERY_MS`.
- [ ] DB error logs do not leak bind parameters, account numbers, raw uploaded rows, or personal data.
- [ ] High-frequency info/debug events are sampled through `LOG_SAMPLE_RATE_HIGH_FREQ`.
- [ ] Warnings, errors, request summaries, and finance lifecycle events are never sampled.
- [ ] Grafana saved queries or dashboards exist for API errors, slow DB queries, IBKR Flex, quote refreshes, uploads, snapshots, and RAG ingestion failures.
- [ ] Backend tests and API smoke pass.
- [ ] When issue 184 observability stack is running, representative job and slow-query logs can be found in Loki by `job_id` or event name.

## Out Of Scope
- Loki/Grafana/Alloy infrastructure.
- Request ID middleware and redaction filters from Issue 185.
- Custom in-app log viewer.
- Remote/hosted observability.
- Alerting and notifications.
- Metrics collection with Prometheus.
- Business audit tables.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add job context helper.
- [ ] Wire `job_id` into scheduled/background flows.
- [ ] Add upload ingestion `FAILED` and `NEEDS_MAPPING` structured WARNING logs.
- [ ] Add slow DB query/error logging.
- [ ] Add high-frequency sampling helper.
- [ ] Add Grafana saved queries or dashboards.
- [ ] Add focused tests.
- [ ] Run deterministic safety gates.
- [ ] Verify semantic intent is achieved.

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `not-started`
- Provider/Model: `manual/task-planning`
- Last Updated: `2026-07-02T00:00:00+08:00`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` - planning issue only
- `typecheck`: `skip` - planning issue only
- `tests`: `skip` - planning issue only
- `e2e`: `skip` - planning issue only
- `api-smoke`: `skip` - planning issue only
- `observability-smoke`: `skip` - planning issue only
- `policy-checks`: `skip` - planning issue only

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- None.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason:
- Attempted mitigations:
- Suggested human action:

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: run after Issues 184 and 185 are implemented and verified.
- Open questions:
  - None.

## Automation Log (Mutable)
- 2026-07-02T00:00:00+08:00 - Created phase 3 observability issue for operational job correlation, DB logging, sampling, and Grafana views.
