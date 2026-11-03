# Issue 114: IBKR Flex token logged in plain text by httpx request logs

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/114

## Objective
- The IBKR Flex token (and query id / reference code) never appears in container logs or Loki.

## Architecture Decisions
- Keep httpx's INFO request log (useful for provider debugging) and extend the existing `RedactionFilter` URL pattern to IBKR's one-letter params `t=` / `q=`, rather than silencing httpx.
- Existing copies: `make logs-purge-secrets` files a Loki delete request (applied after Loki's 24h cancel period; 15-day retention would drop them by itself) and checks the API container's log (fresh after `make deploy` recreates it). Token rotation: Hitesh's call.

## Acceptance Criteria
- [ ] A test drives real httpx requests to the Flex URLs and asserts the token, query id and reference code are absent from the log.
- [ ] After deploy + `make logs-purge-secrets`: no unredacted token in `docker logs`; Loki delete request filed.

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_observability_logging.py -k ibkr_flex_token` (fails without the fix: checked).
- After deploy: `make logs-purge-secrets`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `<stage>`
- Workflow Status: `<running|blocked|shipped|failed>`
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

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
