# Issue 112: Schedulers skip daily runs after the Mac sleeps (IBKR, stock quotes, crypto)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/112

## Objective
- IBKR, stock quotes and crypto refresh at least once a day, even when the Mac sleeps through the scheduled time: the run happens shortly after wake.

## Architecture Decisions
- D-19: a 5-minute "is a run due?" interval check per job (`app/core/catchup.py`), replacing cron + startup catch-up. Due = newest successful run finished before the most recent scheduled time. `misfire_grace_time=None`, `coalesce`, `max_instances=1` on every scheduler. A failed due run waits `SCHEDULER_RETRY_MINUTES` (30) before retrying.
- IBKR default time 18:30 SGT (was 08:15): IBKR's prior-day statement isn't built at 08:15 SGT.

## Acceptance Criteria
- [ ] After a sleep spanning a scheduled time, the run happens within one check interval of wake (IBKR, quotes per window, crypto).
- [ ] No repeat once a run succeeded since the scheduled time.
- [ ] A failing provider is retried every 30 min, not every 5.

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_scheduler_catchup.py tests/test_ibkr_flex_phase1.py tests/test_market_data.py tests/test_crypto.py tests/test_observability_logging.py`.
- After deploy: close the lid over 18:30 SGT, open it, and within ~5 min `docker logs` shows `ibkr_flex_refresh_succeeded`.

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
