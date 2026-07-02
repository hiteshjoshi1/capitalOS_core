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
- [x] Add job context helper.
- [x] Wire `job_id` into scheduled/background flows.
- [x] Add upload ingestion `FAILED` and `NEEDS_MAPPING` structured WARNING logs.
- [x] Add slow DB query/error logging.
- [x] Add high-frequency sampling helper.
- [x] Add Grafana saved queries or dashboards.
- [x] Add focused tests.
- [x] Run deterministic safety gates.
- [x] Verify semantic intent is achieved.

## Execution Journal (Codex Mutable)
- Current Stage: `implemented`
- Workflow Status: `completed`
- Provider/Model: `codex`
- Last Updated: `2026-07-02T22:24:00+08:00`
- Implemented job context propagation, DB slow/error logging, high-frequency sampling, lifecycle events, Grafana dashboard provisioning, and focused tests.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `compile`: `pass` - `python3 -m compileall api/app api/tests/test_observability_logging.py`
- `api-rebuild`: `pass` - API image built and `capitalos-api` restarted
- `contract-backend`: `pass` - 3 passed
- `test-backend`: `pass` - 978 passed, 4 skipped
- `api-smoke`: `pass` - `/health` returned `{"status":"ok"}` and dashboard summary returned JSON
- `lint`: `pass` - frontend eslint passed; backend ruff unavailable in API image and Makefile skipped backend lint
- `typecheck`: `pass` - frontend `tsc -b` passed; backend mypy unavailable in API image and Makefile skipped backend typecheck
- `contract-frontend`: `pass` - 6 passed
- `test-frontend`: `pass` - 191 passed
- `e2e`: `pass` - 17 passed
- `web-rebuild`: `pass` - Vite production build completed
- `orch-test`: `pass` - 192 passed
- `observability-smoke`: `pass` - found 1 Loki log line
- `policy-checks`: `pass` - no commits, pushes, or PRs created

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
- Next expected action: review and ship.
- Open questions:
  - None.

## Automation Log (Mutable)
- 2026-07-02T00:00:00+08:00 - Created phase 3 observability issue for operational job correlation, DB logging, sampling, and Grafana views.
- 2026-07-02T22:24:00+08:00 - Implemented phase 3 observability logging, dashboards, and verification.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `waiting_for_human`

## Workflow Snapshot
- latest_outcome: Implemented operational observability phase 3: job correlation IDs, structured lifecycle logs, safe DB slow/error logging, high-frequency sampling, Grafana dashboard provisioning, and focused backend tests.
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`
- retry_detail: `test-backend` stopped after attempt 1/3: Code failure with no auto-fix available: E       AssertionError: assert 'event=db_slow_query' in ''

## Active Requirements
- Acceptance criterion: Background scheduler logs include a per-run job_id for IBKR Flex, quote refresh, upload ingestion, snapshot, and RAG ingestion jobs.
- Acceptance criterion: Job lifecycle events use stable event names and include duration, status, rows/counts where available, provider/platform where relevant, and error class on failure.
- Acceptance criterion: Upload ingestion runner logs WARNING events for both FAILED and NEEDS_MAPPING JSON-result branches.
- Acceptance criterion: Slow DB queries emit event=db_slow_query at WARNING level when they exceed DB_SLOW_QUERY_MS.
- Acceptance criterion: DB error logs do not leak bind parameters, account numbers, raw uploaded rows, or personal data.
- Acceptance criterion: High-frequency info/debug events are sampled through LOG_SAMPLE_RATE_HIGH_FREQ.
- Acceptance criterion: Warnings, errors, request summaries, and finance lifecycle events are never sampled.
- Acceptance criterion: Grafana saved queries or dashboards exist for API errors, slow DB queries, IBKR Flex, quote refreshes, uploads, snapshots, and RAG ingestion failures.
- Acceptance criterion: Backend tests and API smoke pass.
- Acceptance criterion: When issue 184 observability stack is running, representative logs can be found in Loki by job_id or event name.

## Prepare
Checked out `feature/issue-186-operational-logging-job-db-sampling-and-grafana-views` from `main` and ensured task file exists.

## Plan Summary
Extended existing logfmt/request-context logging with job context and sampling, instrumented existing SQLAlchemy engine, wired lifecycle events into scheduler/manual/background flows, added Grafana Loki dashboard provisioning, and verified through required Makefile gates plus observability smoke.

### Architecture Decisions
- Extended api/app/core/logging.py instead of adding a parallel logging stack.
- Attached SQLAlchemy event hooks to the existing application engine/session factory only.
- Used a contextvar-backed synthetic UUID job_id for scheduler, manual, and background job logs.
- Kept high-cardinality fields in logfmt body fields, not Loki labels.
- Limited sampling to explicitly marked realtime info logs; warnings, errors, requests, and finance lifecycle logs remain unsampled.

### Acceptance Criteria
- Background scheduler logs include a per-run job_id for IBKR Flex, quote refresh, upload ingestion, snapshot, and RAG ingestion jobs.
- Job lifecycle events use stable event names and include duration, status, rows/counts where available, provider/platform where relevant, and error class on failure.
- Upload ingestion runner logs WARNING events for both FAILED and NEEDS_MAPPING JSON-result branches.
- Slow DB queries emit event=db_slow_query at WARNING level when they exceed DB_SLOW_QUERY_MS.
- DB error logs do not leak bind parameters, account numbers, raw uploaded rows, or personal data.
- High-frequency info/debug events are sampled through LOG_SAMPLE_RATE_HIGH_FREQ.
- Warnings, errors, request summaries, and finance lifecycle events are never sampled.
- Grafana saved queries or dashboards exist for API errors, slow DB queries, IBKR Flex, quote refreshes, uploads, snapshots, and RAG ingestion failures.
- Backend tests and API smoke pass.
- When issue 184 observability stack is running, representative logs can be found in Loki by job_id or event name.

### Planned Paths
- `api/app/core/logging.py`
- `api/app/db/session.py`
- `api/app/portfolio/`
- `api/app/market_data/`
- `api/app/ingestion/`
- `api/app/rag/`
- `api/app/crypto/`
- `api/app/routers/`
- `api/app/services/realtime.py`
- `api/tests/`
- `config/grafana/provisioning/`
- `docker-compose.yml`
- `tasks/issue-186-operational-logging-job-db-sampling-and-grafana-views.md`

## Build Summary
Implemented operational observability phase 3: job correlation IDs, structured lifecycle logs, safe DB slow/error logging, high-frequency sampling, Grafana dashboard provisioning, and focused backend tests.

### Changed Files
- `api/app/core/logging.py`
- `api/app/crypto/refresh.py`
- `api/app/crypto/scheduler.py`
- `api/app/db/session.py`
- `api/app/ingestion/runner.py`
- `api/app/market_data/scheduler.py`
- `api/app/portfolio/scheduler.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/routers/market_data.py`
- `api/app/routers/portfolio.py`
- `api/app/services/realtime.py`
- `api/tests/test_observability_logging.py`
- `config/grafana/provisioning/dashboards/capitalos.yaml`
- `config/grafana/provisioning/dashboards/json/capitalos-operational-logs.json`
- `config/grafana/provisioning/datasources/loki.yaml`
- `docker-compose.yml`
- `tasks/issue-186-operational-logging-job-db-sampling-and-grafana-views.md`

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
Implemented operational observability phase 3: job correlation IDs, structured lifecycle logs, safe DB slow/error logging, high-frequency sampling, Grafana dashboard provisioning, and focused backend tests.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` Background scheduler logs include a per-run job_id for IBKR Flex, quote refresh, upload ingestion, snapshot, and RAG ingestion jobs.: job_context wired into IBKR scheduler, market-data scheduler, ingestion runner, RAG pipeline, and crypto snapshot scheduler/refresh.
- `pass` Job lifecycle events use stable event names and include duration, status, rows/counts where available, provider/platform where relevant, and error class on failure.: Stable events implemented for ibkr_flex_refresh, quote_refresh, upload_ingest, snapshot, and rag_ingest flows.
- `pass` Upload ingestion runner logs WARNING events for both FAILED and NEEDS_MAPPING JSON-result branches.: Focused tests cover FAILED and NEEDS_MAPPING branches; Loki found event=upload_ingest_needs_mapping.
- `pass` Slow DB queries emit event=db_slow_query at WARNING level when they exceed DB_SLOW_QUERY_MS.: SQLAlchemy after_cursor_execute hook logs event=db_slow_query; tests verify threshold behavior and Loki found event=db_slow_query.
- `pass` DB error logs do not leak bind parameters, account numbers, raw uploaded rows, or personal data.: DB logs only operation, table, duration_ms, row_count, and error_class; test confirms bind parameter values are absent.
- `pass` High-frequency info/debug events are sampled through LOG_SAMPLE_RATE_HIGH_FREQ.: Realtime publish info logs use high_frequency_log_enabled and include sample_rate.
- `pass` Warnings, errors, request summaries, and finance lifecycle events are never sampled.: Sampling helper always returns true for WARNING and above, and lifecycle/request logs do not call the sampling helper.
- `pass` Grafana saved queries or dashboards exist for API errors, slow DB queries, IBKR Flex, quote refreshes, uploads, snapshots, and RAG ingestion failures.: Provisioned CapitalOS Operational Logs dashboard with panels for all requested views.
- `pass` Backend tests and API smoke pass.: make test-backend passed; make api-smoke passed after rebuild and after final container restore.
- `pass` When issue 184 observability stack is running, representative job and slow-query logs can be found in Loki by job_id or event name.: make observability-smoke passed; Loki query found event=upload_ingest_needs_mapping and event=db_slow_query.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- test-backend: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260702T143458Z_test-backend_attempt1.log, notes=Code failure with no auto-fix available: E       AssertionError: assert 'event=db_slow_query' in ''
<!-- MACHINE_RENDERED_END -->
