# Issue 200: Claude Code Pipeline Hygiene (Phase 2)

## Objective
- Close two silent gaps in the quality gates so they check what they claim to check: backend lint/typecheck currently no-op, and CI never runs automatically.
- Stop wasting agent turns (Claude or Codex) diagnosing known-bad tests that aren't caused by the change under review.
- Give the inner dev loop a genuinely fast path so a one-file change doesn't require spinning the full Docker-backed suite.

This is **Phase 2** of the Claude Code DX upgrade (see `tasks/issue-199-claude-code-dx-upgrade.md` for Phase 1, which already shipped: `CLAUDE.md`, allowlist + `PreToolUse` hook, `run`/`verify` project skills).

## Current State (confirmed clean at doc-writing time, 2026-07-16 — re-verify anyway before starting, since this changed once already in one day)
- **`make lint` / `make typecheck` silently skip the backend.** Both targets guard with `if command -v ruff/mypy >/dev/null 2>&1; then ... ; else echo '... skipping'; fi` (`Makefile` `lint`/`typecheck` targets) — neither tool is installed in the `api` Docker image (`api/Dockerfile` only installs from `api/requirements.txt`, which doesn't include either). Net effect: every `make lint`/`make typecheck`/`make verify` run has been checking the frontend only; backend Python has shipped with zero automated lint/type coverage.
- **CI does not run on PRs.** `.github/workflows/pr-validate.yml` is `on: workflow_dispatch` only (manual trigger) — it never runs automatically on `pull_request`, despite otherwise being a complete gate (lint, typecheck, backend tests, frontend tests, optional e2e).
- **The previously-known-failing test set is now fixed — do not re-fix it.** As of the Phase 1 audit (2026-07-15), 13 tests under `test_uob_*`/`test_ingest_uob_*` failed due to missing `html5lib`/`openpyxl` in the `api` image. As of a clean, isolated `docker compose run --rm api pytest -q` full-suite run the next day (2026-07-16, no other test process running concurrently — an earlier concurrent run had produced two false "database is locked" SQLite errors, since resolved by not overlapping runs), **the entire backend suite passes: 100%, exit code 0.** `openpyxl`/`xlrd`/`lxml` are now present in `api/requirements.txt`; `html5lib` is still absent but nothing in the current suite exercises it. This line item is now a **no-op** — the dependency gap resolved itself between the two dates (likely via an unrelated requirements.txt update). Still worth a fresh run at execution time before assuming this holds, since it visibly moved once in one day already, but do not spend time hunting for a fix that isn't needed.
- No `make verify-fast` (or equivalent) target exists today.

## Architecture Decisions
- **ruff + mypy**: add both to `api/requirements.txt` (dev-only; if the repo wants to keep the runtime image lean, split into a `requirements-dev.txt` installed in the Dockerfile — check whether that pattern already exists before inventing a new one). Add minimal, non-disruptive configs (`pyproject.toml` or `ruff.toml` / `mypy.ini`) — the goal here is "these tools run and report something," not "achieve zero warnings on day one." Do not attempt a repo-wide lint-clean pass in this issue; that's a separate, much larger, unscoped effort. If turning the tools on surfaces a large pre-existing warning backlog, the right move is a permissive baseline config (or a documented ignore list) that passes today, not fixing everything at once — flag the backlog size in the PR description instead of silently suppressing it.
- **UOB tests**: confirmed a no-op as of 2026-07-16 (see Current State) — re-run once at the start of execution to confirm it still holds, then move on without further action. If a fresh run does show failures (dependency drift is clearly possible in this repo), prefer fixing the real gap (install the missing dependency) over `skipif`-guarding it, unless the fixture/data itself is the problem (not just a missing package), in which case document why skip is the correct call.
- **CI**: change `.github/workflows/pr-validate.yml` trigger from `workflow_dispatch` only to `on: pull_request` (keep `workflow_dispatch` too, so manual re-runs still work). No other change to the workflow's steps unless the ruff/mypy addition above requires wiring them into the `Lint`/`Typecheck` steps (it shouldn't — those steps already call `make lint`/`make typecheck`, which will pick the tools up automatically once installed).
- **`verify-fast`**: before building this, check whether it's still needed given Phase 1's `.claude/skills/verify/SKILL.md` already documents the targeted single-file commands (`npx vitest run <file>`, `docker compose run --rm api pytest tests/test_X.py`) as the recommended inner-loop path. If a Makefile target still adds real value (e.g. a one-liner a human would actually type, vs. an agent following the skill), add `make verify-fast` as: frontend `npx vitest run` (whole frontend suite, still fast, no Docker) + backend `docker compose run --rm api pytest` scoped to skip anything slow that a full `test-all` would include (there is no slow step in today's plain `test-backend`/`test-frontend` themselves — the slowness lives in `test-all`'s extra `contract-backend`/`contract-frontend`/`orch-test`/`e2e` steps, which `verify-fast` should exclude, same as `verify` already does). If the skill already covers this adequately, record that decision instead of adding a redundant target.

## Explicitly out of scope
- Full backend lint-clean / type-clean pass (separate effort once the tools are actually running and the backlog size is known).
- Any change to `e2e`/`orch-test` speed or scope.
- Phase 3 (RAG/research tooling) and Phase 4 (remote dev) — separate issues.

## Acceptance Criteria
- [ ] `docker compose run --rm api sh -lc "command -v ruff && command -v mypy"` succeeds (both installed in the image).
- [ ] `make lint` and `make typecheck` visibly run backend checks (no more "skipping" message) and both pass (or fail only on genuine, disclosed issues — not silently green because the tool is absent).
- [ ] `.github/workflows/pr-validate.yml` triggers on `pull_request` (verified by opening a test PR, or by inspecting the triggered-workflow list on an existing PR after merge) — `workflow_dispatch` still present as a fallback.
- [ ] Fresh `docker compose run --rm api pytest -q` result is captured in this doc's Deterministic Gate Results with the actual current failure list (may be empty) — anything still failing is either fixed or explicitly justified as a documented skip.
- [ ] Decision recorded on `make verify-fast`: added (with its exact definition) or explicitly deferred to the existing `verify` skill, with reasoning either way.
- [ ] `CLAUDE.md` / `.claude/skills/verify/SKILL.md` updated if any of the above changes what those docs currently claim (e.g. remove the "lint/typecheck silently skip backend" gotcha once fixed; update or remove the UOB known-failure note based on the fresh count).

## How To Test
- `make lint` and `make typecheck` — confirm backend tools actually execute (look for ruff/mypy output, not the skip message).
- `docker compose run --rm api pytest -q` — confirm the full current failure list, and confirm it matches what Acceptance Criteria #4 was resolved to.
- Push a throwaway branch/PR (or inspect Actions tab after the workflow file changes are merged) to confirm `pr-validate` fires without manual dispatch.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Run a fresh full backend suite and record the real current failure list (do this FIRST, before assuming the Phase 1 audit's numbers still hold)
- [x] Add ruff + mypy to the api image; minimal permissive config
- [x] Re-confirm the fresh run is still clean (done at doc-writing time, 2026-07-16: 100% pass, exit 0 — re-check once more at execution start since it visibly moved once already)
- [x] Flip CI trigger to `on: pull_request` (keep `workflow_dispatch`)
- [x] Decide on `make verify-fast` vs. relying on the existing `verify` skill; implement or document the decision
- [x] Update `CLAUDE.md`/`verify` skill to match the new reality

## Execution Journal (Codex Mutable)
- Current Stage: `verify`
- Workflow Status: `passed`
- Provider/Model: `codex/gpt-5.6-sol`
- Last Updated: `2026-07-22`
- Latest note: `Implementation and the complete required verification matrix passed; ready for Ship to commit and raise the PR.`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `full backend suite (fresh, 2026-07-16)`: `pass` — `docker compose run --rm api pytest -q`, clean isolated run, 100% pass, exit 0, no `test_uob_*`/`test_ingest_uob_*` failures. Re-run at execution start to confirm still current.
- `full backend suite (fresh, 2026-07-22)`: `pass` — `make test-backend`, 1122 passed, 4 skipped, exit 0; no UOB failures.
- `backend tool availability`: `pass` — `docker compose run --rm api sh -lc "command -v ruff && command -v mypy"` resolved both tools under `/usr/local/bin`.
- `lint`: `pass` — `make lint` visibly ran ESLint and `ruff check app tests`; ruff initially found two undefined names, both fixed, then reported `All checks passed!`.
- `typecheck baseline`: `pass` — first mypy run measured 204 pre-existing errors in 33 of 137 modules; the explicit module baseline leaves 104 existing modules plus new modules checked by default and passes without globally disabling mypy.
- `ci trigger`: `pass` — static inspection confirms both `pull_request` and `workflow_dispatch` under `.github/workflows/pr-validate.yml`; live PR triggering remains a post-ship check.
- `verify-fast decision`: `pass` — deferred. The existing verify skill already provides genuinely targeted one-file commands for both stacks; a whole-suite Make target would duplicate `make verify`'s test scope and would not make a one-file inner loop faster.
- `api-rebuild`: `pass` — final `make api-rebuild` rebuilt the image with ruff, mypy, the baseline config, and the two lint fixes, then restarted the API.
- `contract-backend`: `pass` — `make contract-backend`, 3 passed.
- `test-backend`: `pass` — final `make test-backend`, 1122 passed and 4 skipped.
- `api-smoke`: `pass` — `make api-smoke`, `/health` returned `{"status":"ok"}` and the authenticated dashboard summary returned valid JSON.
- `lint`: `pass` — final `make lint`, ESLint passed and ruff reported `All checks passed!`.
- `typecheck`: `pass` — final `make typecheck`, TypeScript passed and mypy reported no issues in 137 source files under the recorded baseline.
- `contract-frontend`: `pass` — `make contract-frontend`, 6 passed.
- `test-frontend`: `pass` — `make test-frontend`, 292 passed across 44 files.
- `e2e`: `pass` — first `make e2e` found one stale accessible-name assertion; after aligning it with the existing UI/unit-test wording, the required rerun passed all 19 tests.
- `orch-test`: `pass` — `make orch-test`, 201 passed.
- `prepare`: `fail` — `The task file lacked the machine-rendered envelope; normalization now makes retries idempotent.`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `web/tests/e2e/author-library.spec.ts` — the mandated full-suite run exposed a stale exact accessible-name assertion (`Open source`) that no longer matched the established UI and unit-test wording (`Open original source`); updated only that assertion so the deterministic gate reflects current behavior.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `Not applicable — the prepare failure is recoverable and the workflow has not been abandoned.`
- Attempted mitigations:
  - `Normalized issues 200–202 to the current task template and required machine-rendered envelope.`
- Suggested human action: `Retry the issue-200 task workflow from its feature branch.`

## Human Action Summary (Codex Mutable)
- Next expected action: `Ship may commit the verified feature branch and raise the PR; confirm the automatic pull_request workflow after push.`
- Open questions:
  - None. No `requirements-dev.txt` convention exists, so the pinned tools use the existing `api/requirements.txt` image dependency path.
- If PR raised but intent partial:
  - unmet criteria: `To be populated by the workflow if applicable.`
  - follow-up issue: `To be populated by the workflow if applicable.`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-200-claude-code-pipeline-hygiene`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.6-sol`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: ruff and mypy are installed and executable in the API image.
- Acceptance criterion: make lint and make typecheck visibly execute backend checks and pass.
- Acceptance criterion: PR validation declares both pull_request and workflow_dispatch triggers.
- Acceptance criterion: A fresh complete backend-suite result is recorded in the task document.
- Acceptance criterion: The verify-fast decision and reasoning are recorded.
- Acceptance criterion: CLAUDE.md and the verify skill reflect the current behavior.

## Prepare
Checked out `feature/issue-200-claude-code-pipeline-hygiene` from `main` and verified task file exists.

## Plan Summary
Established a fresh backend baseline, installed and configured ruff/mypy, made Makefile checks unconditional, enabled pull-request CI, documented the verify-fast deferral, repaired surfaced gate failures, and ran the complete verification matrix.

### Architecture Decisions
- Added pinned ruff and mypy dependencies to api/requirements.txt because the repository has no requirements-dev.txt convention.
- Enabled high-value ruff correctness rules while deferring broad style enforcement.
- Recorded mypy's 204-error backlog as an explicit 33-module baseline; the other 104 existing modules and new modules remain checked by default.
- Deferred make verify-fast because the existing verify skill already provides genuinely targeted one-file commands; another whole-suite target would not improve the one-file loop.
- Kept both pull_request and workflow_dispatch CI triggers.
- Fixed the two genuine undefined-name errors exposed by ruff instead of suppressing them.

### Acceptance Criteria
- ruff and mypy are installed and executable in the API image.
- make lint and make typecheck visibly execute backend checks and pass.
- PR validation declares both pull_request and workflow_dispatch triggers.
- A fresh complete backend-suite result is recorded in the task document.
- The verify-fast decision and reasoning are recorded.
- CLAUDE.md and the verify skill reflect the current behavior.

### Planned Paths
- `Makefile`
- `api/Dockerfile`
- `api/requirements.txt`
- `api/pyproject.toml`
- `api/app/rag/eval/cli.py`
- `api/app/routers/crypto.py`
- `.github/workflows/pr-validate.yml`
- `CLAUDE.md`
- `.claude/skills/verify/SKILL.md`
- `tasks/issue-200-claude-code-pipeline-hygiene.md`

## Build Summary
Implemented Issue 200: backend lint/typecheck now execute, PR CI is automatic, stale guidance is corrected, and all required verification gates pass.

### Changed Files
- `.claude/skills/verify/SKILL.md`
- `.github/workflows/pr-validate.yml`
- `CLAUDE.md`
- `Makefile`
- `api/Dockerfile`
- `api/app/rag/eval/cli.py`
- `api/app/routers/crypto.py`
- `api/pyproject.toml`
- `api/requirements.txt`
- `tasks/issue-200-claude-code-pipeline-hygiene.md`
- `web/tests/e2e/author-library.spec.ts`

### Extra Files Outside Planned Scope
- `web/tests/e2e/author-library.spec.ts`: The mandated full-suite run exposed a stale accessible-name assertion expecting 'Open source' while the established UI and unit test use 'Open original source'; only that assertion was aligned. (source: `builder`)

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
- `web/tests/e2e/author-library.spec.ts` — reason: The mandated full-suite run exposed a stale accessible-name assertion expecting 'Open source' while the established UI and unit test use 'Open original source'; only that assertion was aligned. (source: `builder`)

## Agent Run Summary
Implemented Issue 200: backend lint/typecheck now execute, PR CI is automatic, stale guidance is corrected, and all required verification gates pass.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.6-sol`

### Semantic Checks
- `pass` Both ruff and mypy are installed in the API image.: The required command resolved both executables under /usr/local/bin.
- `pass` make lint and make typecheck visibly execute backend checks and pass.: Final output contains ruff check app tests with All checks passed and mypy app with no issues in 137 files; no skip branch remains.
- `partial` PR validation triggers on pull_request and retains workflow_dispatch.: Static inspection confirms both trigger keys in the workflow. Live dispatch requires Ship to push or open a PR, which this session was explicitly forbidden to do.
- `pass` Fresh full backend result is recorded with all current failures resolved or justified.: Task evidence records 1122 passed and 4 skipped with no failures or UOB regressions.
- `pass` The make verify-fast decision is recorded.: The task records an explicit deferral because the existing verify skill already supplies targeted one-file commands.
- `pass` CLAUDE.md and the verify skill match the new behavior.: Both documents remove the obsolete silent-skip and UOB-failure claims and describe active backend tooling and its permissive baseline.

### Risk Flags
- Post-ship observation is still required to prove GitHub actually dispatches the pull_request workflow.
- The explicit 33-module mypy debt baseline should be reduced in follow-up work.
- Repeated API rebuilds missed Docker's large dependency-layer cache, indicating an existing build-performance issue outside this task.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-200-claude-code-pipeline-hygiene`.
<!-- MACHINE_RENDERED_END -->
