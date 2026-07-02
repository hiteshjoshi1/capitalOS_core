# Issue 184: Observability phase 1 - Loki, Grafana, and Alloy stack

## Objective
- Add local-first persistent log storage and viewing for CapitalOS using Loki, Grafana, and Alloy.
- Keep this phase infrastructure-only: collect existing Docker logs, make them searchable, and enforce env-driven retention.
- Provide deterministic Makefile commands to start, stop, inspect, and smoke-test observability without changing app logging semantics yet.

## Split Plan
- Issue 184: local observability stack, retention, Docker log collection, Grafana datasource, smoke test.
- Issue 185: API logfmt contract, request ID middleware, context propagation, logger namespace normalization, and redaction.
- Issue 186: operational job correlation, DB slow-query logging, sampling rules, and Grafana views for finance/RAG flows.

## Current State
- `make logs` and `make api-logs` only stream Docker logs.
- Logs are not persisted in a queryable local observability store.
- There is no Grafana datasource or saved view for application logs.
- Retention is not controlled by a CapitalOS configuration file.

## Architecture Decisions
- Use Loki for log storage, Grafana for viewing, and Alloy for Docker log collection.
- Keep API and frontend code unchanged in this phase.
- Keep existing stdout/stderr logging as the collection source.
- Do not write operational logs into Postgres. Postgres remains for product data and future explicit audit/business events.
- Do not build a custom in-app log viewer. Grafana is the viewer.
- Keep observability optional behind explicit Make targets. Normal `make up` should not require Loki/Grafana/Alloy unless a later issue changes that deliberately.
- Use low-cardinality Loki labels only: service, container, environment, level when safely available. Do not label request IDs, user IDs, account IDs, tickers, raw paths with IDs, or exception messages.

## Configuration Plan
- Add `config/observability.env.example` with safe local defaults:
  - `LOKI_RETENTION_PERIOD=15d`
  - `GRAFANA_ADMIN_USER=admin`
  - `GRAFANA_ADMIN_PASSWORD=capitalos`
  - `OBSERVABILITY_ENV=local`
- Runtime observability services should read from an env file, preferably `config/observability.env` copied from the example.
- Retention must come from `LOKI_RETENTION_PERIOD` in the env file, not a hardcoded duration inside Loki YAML.
- Add `config/loki/local-config.yaml`.
- Add `config/alloy/config.alloy`.
- Add Grafana datasource provisioning under `config/grafana/provisioning/`.
- Add Docker Compose services:
  - `loki`
  - `grafana`
  - `alloy`
- Add Docker volumes:
  - `loki-data`
  - `grafana-data`
- Configure Loki with environment expansion, for example `-config.expand-env=true`, so `LOKI_RETENTION_PERIOD` controls retention.
- Configure the local Alloy service with read-only Docker socket access:
  - `/var/run/docker.sock:/var/run/docker.sock:ro`
  - This is local-only and must not be copied into non-local deployment compose files without a separate security review.

## Makefile Plan
- Add:
  - `make observability-up`
  - `make observability-down`
  - `make observability-logs`
  - `make observability-smoke`
  - `make grafana-url`
- Keep existing:
  - `make logs`
  - `make api-logs`
- `make observability-smoke` must be end-to-end:
  - Implement it as a dedicated script, for example `scripts/observability-smoke.sh`, or an equivalent checked-in script invoked by Make.
  - Do not hide the Loki query/retry logic inside a long Makefile one-liner.
  - Start or require the observability services.
  - Verify Loki ready endpoint is healthy.
  - Verify Grafana health endpoint is healthy.
  - Verify Alloy container is running.
  - Generate a unique smoke ID.
  - Call an existing API endpoint such as `/health?observability_smoke=<smoke-id>` so the API container emits an access log containing that ID.
  - Query Loki through `/loki/api/v1/query` or `/loki/api/v1/query_range` using a short look-back window.
  - Use bounded retry with short backoff until Loki indexes the line, then assert a non-zero result count.
  - Do not rely on one fixed sleep.

## Retention Requirements
- Default retention: 15 days.
- `LOKI_RETENTION_PERIOD=15d` must live in `config/observability.env.example`.
- Loki config must reference the env value using environment expansion instead of hardcoding `15d`.
- Log volumes must persist across `make down`.
- Destructive log cleanup must require an explicit command and must not run as part of normal startup.

## Security And Privacy Requirements
- Grafana and Loki must bind only to localhost in local development.
- Alloy Docker socket access must be read-only and documented as a local-only tradeoff.
- Do not add remote log shipping.
- Do not add custom secrets to committed env files.
- Do not add app log payload changes in this phase; redaction and log format are handled by Issue 185.

## Acceptance Criteria
- [ ] `config/observability.env.example` exists and includes `LOKI_RETENTION_PERIOD=15d`.
- [ ] `make observability-up` starts Loki, Grafana, and Alloy locally.
- [ ] Grafana is reachable locally and has Loki auto-provisioned as a datasource.
- [ ] Loki persists logs to a named Docker volume and enforces retention from `LOKI_RETENTION_PERIOD`.
- [ ] Alloy collects API container logs through a read-only local Docker socket mount and forwards them to Loki.
- [ ] `make observability-smoke` proves a uniquely identified `/health` request appears in Loki through the Loki query API with bounded retry and non-zero result assertion.
- [ ] Existing `make logs` and `make api-logs` remain usable.
- [ ] No API or frontend behavior depends on Grafana/Loki being available.
- [ ] Backend tests and API smoke still pass.

## Out Of Scope
- API logfmt formatting.
- Request ID middleware.
- Redaction filters.
- Logger namespace normalization.
- Job IDs for scheduler/background work.
- Slow DB query logging.
- High-frequency log sampling.
- Grafana dashboards beyond datasource provisioning.
- Custom in-app log viewer.
- Remote/hosted observability.
- Alerting and notifications.
- OpenTelemetry tracing.
- Metrics collection with Prometheus.
- Frontend browser error reporting.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add observability env example with `LOKI_RETENTION_PERIOD=15d`.
- [ ] Add Loki, Grafana, and Alloy config files.
- [ ] Add Docker Compose services and persistent volumes.
- [ ] Add Makefile observability targets.
- [ ] Add dedicated observability smoke script with Loki query and bounded retry.
- [ ] Wire `make observability-smoke` to the smoke script.
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
- Next expected action: run the orchestration workflow for issue 184 first, then 185, then 186.
- Open questions:
  - Confirm whether observability should remain behind `make observability-up` after phase 1, or become part of `make up` later.

## Automation Log (Mutable)
- 2026-07-02T00:00:00+08:00 - Split observability work into three phases and scoped issue 184 to local Loki/Grafana/Alloy infrastructure only.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: Implemented the phase-1 local observability stack wiring for Loki, Grafana, and Alloy, with env-driven Loki retention, Grafana datasource provisioning, Make targets, and a bounded end-to-end smoke script. Runtime observability verification could not complete because Docker socket access became intermittently permission-denied while resolving required images/services.
- next_action: Inspect deterministic gate failures, apply mitigations, then rerun the workflow.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`
- blocked_reason: Agent run reported semantic intent not achieved.

## Active Requirements
- Acceptance criterion: config/observability.env.example exists and includes LOKI_RETENTION_PERIOD=15d.
- Acceptance criterion: make observability-up starts Loki, Grafana, and Alloy locally.
- Acceptance criterion: Grafana is reachable locally and has Loki auto-provisioned as a datasource.
- Acceptance criterion: Loki persists logs to a named Docker volume and enforces retention from LOKI_RETENTION_PERIOD.
- Acceptance criterion: Alloy collects API container logs through a read-only local Docker socket mount and forwards them to Loki.
- Acceptance criterion: make observability-smoke proves a uniquely identified /health request appears in Loki through the Loki query API with bounded retry and non-zero result assertion.
- Acceptance criterion: Existing make logs and make api-logs remain usable.
- Acceptance criterion: No API or frontend behavior depends on Grafana/Loki being available.
- Acceptance criterion: Backend tests and API smoke still pass.

## Prepare
Checked out `feature/issue-184-observability-logging-loki-grafana-alloy` from `main` and ensured task file exists.

## Plan Summary
Add env/config files for Loki, Grafana, and Alloy; add profiled Docker Compose services with named persistent volumes and localhost-only ports; add Make targets for lifecycle, logs, URL, and smoke testing; add a dedicated smoke script that starts services, waits on readiness, emits a unique API health request, and queries Loki with bounded retries; run the required verification suite and classify any failures against acceptance criteria.

### Architecture Decisions
- Observability services are in the existing docker-compose.yml but gated behind the observability Compose profile so normal make up does not require Loki, Grafana, or Alloy.
- Loki retention is configured with ${LOKI_RETENTION_PERIOD} and -config.expand-env=true, with the default value stored in config/observability.env.example.
- Loki and Grafana persist to named Docker volumes loki-data and grafana-data so logs survive normal compose down.
- Grafana is provisioned with a local Loki datasource under config/grafana/provisioning/datasources.
- Alloy tails Docker logs through a read-only Docker socket mount and forwards low-cardinality labels service, container, and environment to Loki.
- Grafana and Loki publish ports only on 127.0.0.1 for local development.
- No API or frontend application code was changed; stdout/stderr logging semantics remain unchanged.

### Acceptance Criteria
- config/observability.env.example exists and includes LOKI_RETENTION_PERIOD=15d.
- make observability-up starts Loki, Grafana, and Alloy locally.
- Grafana is reachable locally and has Loki auto-provisioned as a datasource.
- Loki persists logs to a named Docker volume and enforces retention from LOKI_RETENTION_PERIOD.
- Alloy collects API container logs through a read-only local Docker socket mount and forwards them to Loki.
- make observability-smoke proves a uniquely identified /health request appears in Loki through the Loki query API with bounded retry and non-zero result assertion.
- Existing make logs and make api-logs remain usable.
- No API or frontend behavior depends on Grafana/Loki being available.
- Backend tests and API smoke still pass.

### Planned Paths
- `Makefile`
- `docker-compose.yml`
- `config/observability.env.example`
- `config/loki/`
- `config/alloy/`
- `config/grafana/provisioning/`
- `scripts/observability-smoke.sh`
- `tasks/issue-184-observability-logging-loki-grafana-alloy.md`

## Build Summary
Implemented the phase-1 local observability stack wiring for Loki, Grafana, and Alloy, with env-driven Loki retention, Grafana datasource provisioning, Make targets, and a bounded end-to-end smoke script. Runtime observability verification could not complete because Docker socket access became intermittently permission-denied while resolving required images/services.

### Changed Files
- `Makefile`
- `config/alloy/config.alloy`
- `config/grafana/provisioning/datasources/loki.yaml`
- `config/loki/local-config.yaml`
- `config/observability.env.example`
- `docker-compose.yml`
- `scripts/observability-smoke.sh`
- `tasks/issue-184-observability-logging-loki-grafana-alloy.md`

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
Implemented the phase-1 local observability stack wiring for Loki, Grafana, and Alloy, with env-driven Loki retention, Grafana datasource provisioning, Make targets, and a bounded end-to-end smoke script. Runtime observability verification could not complete because Docker socket access became intermittently permission-denied while resolving required images/services.

- semantic_intent_achieved: `False`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` config/observability.env.example exists and includes LOKI_RETENTION_PERIOD=15d.: config/observability.env.example was added with LOKI_RETENTION_PERIOD=15d.
- `partial` make observability-up starts Loki, Grafana, and Alloy locally.: Make target and Compose services are wired and profile config renders; runtime startup was not confirmed because Docker socket access failed during smoke attempts.
- `partial` Grafana is reachable locally and has Loki auto-provisioned as a datasource.: Grafana service binds 127.0.0.1:3000 and datasource provisioning file points to http://loki:3100; runtime health could not be reached because services did not start.
- `partial` Loki persists logs to a named Docker volume and enforces retention from LOKI_RETENTION_PERIOD.: docker-compose.yml defines loki-data mounted at /loki; Loki config uses retention_period: ${LOKI_RETENTION_PERIOD} and command -config.expand-env=true. Runtime retention behavior was not observed.
- `partial` Alloy collects API container logs through a read-only local Docker socket mount and forwards them to Loki.: Alloy config discovers Docker containers, labels service/container/environment, and writes to Loki; compose mounts /var/run/docker.sock read-only. Runtime forwarding was not observed.
- `fail` make observability-smoke proves a uniquely identified /health request appears in Loki through the Loki query API with bounded retry and non-zero result assertion.: Smoke script implements the required flow, but make observability-smoke failed before startup due Docker socket permission denied.
- `pass` Existing make logs and make api-logs remain usable.: Existing Makefile targets were not changed.
- `pass` No API or frontend behavior depends on Grafana/Loki being available.: No api/app or web/src files changed; observability services are behind a Compose profile and explicit Make targets.
- `pass` Backend tests and API smoke still pass.: make test-backend passed 967 tests with 4 skipped; make api-smoke passed.

### Risk Flags
- runtime_observability_unverified_due_docker_socket_permission
- exact_contract_backend_target_unverified_due_docker_socket_permission
- observability_image_pull_or_start_not_confirmed

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Blockers
- Agent run reported semantic intent not achieved.

## Permanently Failed / Gave Up
- Stop reason: Agent run reported semantic intent not achieved.
- Attempted mitigations:
- mitigation: No automated mitigation was recorded.
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->
