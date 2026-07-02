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
- [x] Add observability env example with `LOKI_RETENTION_PERIOD=15d`.
- [x] Add Loki, Grafana, and Alloy config files.
- [x] Add Docker Compose services and persistent volumes.
- [x] Add Makefile observability targets.
- [x] Add dedicated observability smoke script with Loki query and bounded retry.
- [x] Wire `make observability-smoke` to the smoke script.
- [x] Run deterministic safety gates.
- [x] Verify semantic intent is achieved.

## Execution Journal (Codex Mutable)
- Current Stage: `semantic_review`
- Workflow Status: `complete`
- Provider/Model: `codex/gpt-5`
- Last Updated: `2026-07-02T16:03:10+08:00`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `api-rebuild`: `pass` - built API image and restarted `capitalos-api`.
- `contract-backend`: `pass` - 3 backend contract tests passed.
- `test-backend`: `pass` - 967 passed, 4 skipped.
- `api-smoke`: `pass` - `/health` returned `{"status":"ok"}` and dashboard summary returned valid JSON.
- `lint`: `pass` - frontend eslint passed; backend lint skipped by existing target because `ruff` is not installed in the API image.
- `typecheck`: `pass` - TypeScript build passed; backend mypy skipped by existing target because `mypy` is not installed in the API image.
- `contract-frontend`: `pass` - 6 passed.
- `test-frontend`: `pass` - 191 passed.
- `e2e`: `pass` - 17 Playwright tests passed.
- `orch-test`: `pass` - 192 passed.
- `observability-up`: `pass` - Loki, Grafana, and Alloy containers were running.
- `observability-smoke`: `pass` - started API/Loki/Grafana/Alloy, verified Loki ready, Grafana health, Grafana Loki datasource provisioning, Alloy running, and found 1 uniquely identified API `/health` log line in Loki.

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- None.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- None.

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: proceed to ship review.
- Open questions: None.

## Automation Log (Mutable)
- 2026-07-02T00:00:00+08:00 - Split observability work into three phases and scoped issue 184 to local Loki/Grafana/Alloy infrastructure only.
- 2026-07-02T14:44:36+08:00 - Implemented phase-1 observability verification tightening and ran deterministic gates; observability smoke passed, but exact Docker-backed targets had socket permission failures.
- 2026-07-02T15:34:55+08:00 - Reran the full requested verification suite; all non-failing gates stayed green, observability smoke passed end-to-end, and exact `make contract-backend` plus `make observability-up` remained blocked by Docker socket permission errors.
- 2026-07-02T16:03:10+08:00 - Reran the full required verification suite successfully; `make contract-backend`, `make observability-up`, and `make observability-smoke` all passed, so semantic intent is achieved.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-184-observability-logging-loki-grafana-alloy`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`

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
Keep observability infrastructure-only and optional behind explicit Make targets. Add local Loki persistence with retention from env expansion, Grafana datasource provisioning, Alloy Docker log collection through a read-only local socket, and a dedicated smoke script that proves a uniquely identified API /health request reaches Loki.

### Architecture Decisions
- Use Loki for persistent local log storage, Grafana for viewing, and Alloy for Docker log collection.
- Keep API and frontend logging semantics unchanged in this phase.
- Keep observability optional behind make observability-* targets; normal make up does not require Loki, Grafana, or Alloy.
- Use LOKI_RETENTION_PERIOD through Loki environment expansion instead of hardcoding retention in Loki YAML.
- Bind Loki and Grafana ports to localhost only for local development.
- Use low-cardinality Loki labels only: service, container, and environment.

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
Implemented and verified Issue 184 observability phase 1. The branch contains optional local Loki, Grafana, and Alloy infrastructure, env-driven Loki retention, Grafana Loki datasource provisioning, read-only Docker log collection through Alloy, and an end-to-end bounded-retry smoke script. This session updated the task ledger after all required gates passed.

### Changed Files
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
Implemented and verified Issue 184 observability phase 1. The branch contains optional local Loki, Grafana, and Alloy infrastructure, env-driven Loki retention, Grafana Loki datasource provisioning, read-only Docker log collection through Alloy, and an end-to-end bounded-retry smoke script. This session updated the task ledger after all required gates passed.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` config/observability.env.example exists and includes LOKI_RETENTION_PERIOD=15d.: File exists and contains LOKI_RETENTION_PERIOD=15d plus local Grafana admin defaults and OBSERVABILITY_ENV=local.
- `pass` make observability-up starts Loki, Grafana, and Alloy locally.: make observability-up passed and reported capitalos-loki, capitalos-grafana, and capitalos-alloy running.
- `pass` Grafana is reachable locally and has Loki auto-provisioned as a datasource.: make observability-smoke verified Grafana /api/health and datasource CapitalOS Loki with type loki and URL http://loki:3100.
- `pass` Loki persists logs to a named Docker volume and enforces retention from LOKI_RETENTION_PERIOD.: docker-compose.yml defines loki-data mounted at /loki; Loki config uses retention_period: ${LOKI_RETENTION_PERIOD} with -config.expand-env=true.
- `pass` Alloy collects API container logs through a read-only local Docker socket mount and forwards them to Loki.: docker-compose.yml mounts /var/run/docker.sock:/var/run/docker.sock:ro for Alloy; make observability-smoke found the unique API /health marker in Loki.
- `pass` make observability-smoke proves a uniquely identified /health request appears in Loki through the Loki query API with bounded retry and non-zero result assertion.: make observability-smoke generated observability-smoke-1782979376-63064 and found 1 Loki log line.
- `pass` Existing make logs and make api-logs remain usable.: Both existing Makefile targets remain present and unchanged in behavior.
- `pass` No API or frontend behavior depends on Grafana/Loki being available.: No api/app or web/src changes were required; observability services are optional and explicit.
- `pass` Backend tests and API smoke still pass.: make contract-backend, make test-backend, and make api-smoke all passed.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-184-observability-logging-loki-grafana-alloy`.
<!-- MACHINE_RENDERED_END -->
