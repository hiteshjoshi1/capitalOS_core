# Issue 184: Observability logging with Loki, Grafana, and Alloy

## Objective
- Add local-first persistent application logging for CapitalOS using Loki for log storage, Grafana for viewing, and Alloy for Docker log collection.
- Make logs readable in terminal and searchable in Grafana with retention controlled by configuration.
- Keep application changes minimal: API logs continue to go to stdout/stderr, with structured redacted logfmt-style fields.

## Current State
- `make logs` and `make api-logs` only stream Docker logs.
- Logs are not persisted as an application-level observability store with query UI, retention policy, or saved views.
- The API already uses Python `logging` in multiple modules, but formatting, request context, redaction, and event names are inconsistent.
- Frontend logging is mostly browser-local and should not be pulled into the first observability phase unless explicit client error reporting is added later.

## Architecture Decisions
- Use Loki + Grafana + Alloy as the standard local observability stack.
- Do not write operational logs into Postgres. Postgres should be reserved for product data and explicit audit/business events.
- Do not build a custom log viewer in CapitalOS for this phase. Grafana already solves search, filtering, saved views, and retention visibility.
- Keep API logging on stdout/stderr. Alloy collects Docker container logs and forwards them to Loki.
- Use human-readable key-value logs, also called logfmt-style logs, for application logs:
  - Example: `ts=2026-07-02T09:15:22Z level=info logger=capitalos.request event=http_request method=GET path=/dashboard/summary status=200 duration_ms=42 request_id=...`
  - This is readable in `docker compose logs`, and still structured enough for Loki/Grafana queries.
  - Use low-cardinality Loki labels only: service, container, environment, level, logger. Keep request IDs, paths, user IDs, tickers, and account IDs as log fields, not labels.
- Add JSON logging only if a later need appears. Logfmt is the better first step because this is a local operational workflow and human readability matters.
- Add a separate `audit_events` or `job_runs` model later only for business facts that must be queryable in-app, such as IBKR Flex refresh status, quote refresh status, uploads, and snapshots. That is not a replacement for operational logs.

## Proposed Stack
- `loki`
  - Stores logs on a Docker volume.
  - Enforces retention through Loki compactor config.
  - Exposes API on localhost for health checks and Grafana queries.
- `grafana`
  - Stores Grafana state on a Docker volume.
  - Auto-provisions Loki as the default datasource.
  - Provides saved queries/dashboards for API errors, request latency, ingestion jobs, IBKR Flex, quote refreshes, and RAG ingestion.
- `alloy`
  - Reads Docker container logs.
  - Adds service/container/environment labels.
  - Forwards logs to Loki.
  - Does not require the API to know Loki exists.

## Configuration Plan
- Add `config/observability.env.example` with safe local defaults:
  - `LOG_LEVEL=INFO`
  - `LOG_FORMAT=logfmt`
  - `LOKI_RETENTION_PERIOD=15d`
  - `GRAFANA_ADMIN_USER=admin`
  - `GRAFANA_ADMIN_PASSWORD=capitalos`
- Runtime observability services should read from an env file, either:
  - `config/observability.env`, copied from the example for local use, or
  - the repo root `.env` if the implementation keeps all local env values in one file.
- Retention must come from `LOKI_RETENTION_PERIOD` in the env file, not a hardcoded duration inside Loki config.
- Add `config/loki/local-config.yaml`.
- Add `config/alloy/config.alloy`.
- Add Grafana provisioning under `config/grafana/provisioning/`.
- Add Docker Compose services:
  - `loki`
  - `grafana`
  - `alloy`
- Add Docker volumes:
  - `loki-data`
  - `grafana-data`
- Configure Loki with environment expansion, for example `-config.expand-env=true`, so `LOKI_RETENTION_PERIOD` from the env file controls retention.
- Do not require these services for normal `make up` unless intentionally chosen. Prefer a separate observability target first, so app startup stays simple.

## Application Logging Plan
- Add one backend logging setup module, for example `api/app/core/logging.py`.
- Configure Python logging once during FastAPI startup.
- Keep existing module loggers working.
- Add request middleware that logs one event per HTTP request:
  - event name
  - method
  - path pattern where feasible
  - status code
  - duration
  - request ID
  - authenticated user identifier if already safely available
- Add `X-Request-ID` propagation:
  - accept incoming request ID if present,
  - generate one otherwise,
  - return it in the response,
  - include it in logs.
- Add redaction rules before anything reaches stdout:
  - redact Authorization headers,
  - redact cookies,
  - redact IBKR tokens/query IDs/ref codes,
  - redact API keys,
  - redact uploaded file contents and raw statement rows,
  - avoid logging full SQL rows with account numbers or personal data.
- Normalize job logs for scheduled/background work:
  - `event=ibkr_flex_refresh_started|succeeded|failed`
  - `event=quote_refresh_started|succeeded|failed`
  - `event=upload_ingest_started|succeeded|failed`
  - `event=snapshot_created|failed`
  - include duration, rows, provider, stale/fresh decision, and error class where relevant.

## Makefile Plan
- Add:
  - `make observability-up`
  - `make observability-down`
  - `make observability-logs`
  - `make grafana-open` if local browser opening is acceptable, otherwise document URL only.
- Keep existing:
  - `make logs`
  - `make api-logs`
- Optional:
  - `make observability-smoke` should verify:
    - Loki ready endpoint returns healthy,
    - Grafana health endpoint returns healthy,
    - Alloy is running,
    - a generated API request appears in Loki query results.

## Grafana Views
- Provision saved dashboards or documented saved queries for:
  - API errors by endpoint/logger.
  - Recent warnings/errors.
  - Request latency by route.
  - IBKR Flex refresh lifecycle.
  - Quote refresh lifecycle.
  - Upload ingestion lifecycle.
  - RAG ingestion failures.
- First version may use Explore queries instead of full dashboards, but datasource provisioning is required.

## Retention Requirements
- Retention must be set in Loki config, not by manually deleting files.
- Default retention: 15 days.
- Retention must be configured through `LOKI_RETENTION_PERIOD=15d` in an env file.
- Loki config must reference the env value using environment expansion instead of hardcoding `15d`.
- Log volumes must be persistent across `make down`.
- Destructive cleanup must require an explicit command and must not run as part of normal startup.

## Security And Privacy Requirements
- Do not expose Grafana/Loki beyond localhost in local development.
- Do not log secrets, bearer tokens, cookies, IBKR tokens/query IDs/ref codes, API keys, or raw uploaded statement contents.
- Do not use high-cardinality Loki labels for request IDs, users, symbols, accounts, paths with IDs, or exception messages.
- Docker socket access for Alloy must be documented as a local observability tradeoff. If Alloy requires Docker socket read access, keep it scoped to local development and do not deploy that mode publicly.

## Acceptance Criteria
- [ ] `make observability-up` starts Loki, Grafana, and Alloy locally.
- [ ] Grafana is reachable locally and has Loki auto-provisioned as a datasource.
- [ ] Loki persists logs to a named Docker volume and enforces documented retention.
- [ ] `LOKI_RETENTION_PERIOD=15d` lives in an observability env file or documented `.env` entry, not hardcoded only in Loki YAML.
- [ ] API request logs are emitted as readable logfmt-style key-value lines.
- [ ] Existing Python loggers continue to work without rewriting every module.
- [ ] API request logs include request ID, method, path, status, duration, level, logger, and event name.
- [ ] Sensitive values are redacted from logs before they reach stdout.
- [ ] Alloy collects API container logs and forwards them to Loki.
- [ ] A smoke command proves a request to `/health` or `/dashboard/summary` appears in Loki.
- [ ] Existing `make logs` and `make api-logs` remain usable.
- [ ] No frontend behavior depends on Grafana/Loki being available.
- [ ] Backend tests and API smoke still pass.

## Out Of Scope
- Custom in-app log viewer.
- Remote/hosted observability.
- Alerting and notifications.
- OpenTelemetry tracing.
- Metrics collection with Prometheus.
- Frontend browser error reporting.
- Business audit tables for IBKR/quote/upload run history, except to document the later need.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add Loki, Grafana, and Alloy config files.
- [ ] Add observability env example with `LOKI_RETENTION_PERIOD=15d`.
- [ ] Add Docker Compose services and persistent volumes.
- [ ] Add Makefile observability targets.
- [ ] Add backend logging setup and request middleware.
- [ ] Add request ID propagation.
- [ ] Add redaction tests.
- [ ] Add observability smoke verification.
- [ ] Run deterministic safety gates.
- [ ] Verify semantic intent is achieved.

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `not-started`
- Provider/Model: `manual/task-planning`
- Last Updated: `2026-07-02T00:00:00+08:00`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` — planning issue only
- `typecheck`: `skip` — planning issue only
- `tests`: `skip` — planning issue only
- `e2e`: `skip` — planning issue only
- `api-smoke`: `skip` — planning issue only
- `policy-checks`: `skip` — planning issue only

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
- Next expected action: run the orchestration workflow for issue 184 after issue 183 is merged.
- Open questions:
  - Confirm whether `make up` should include observability by default or whether observability should stay behind `make observability-up`.

## Automation Log (Mutable)
- 2026-07-02T00:00:00+08:00 - Created planning issue for local persistent logging using Loki, Grafana, and Alloy with logfmt-style API logs.
