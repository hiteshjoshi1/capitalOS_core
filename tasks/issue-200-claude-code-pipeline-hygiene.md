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
- [ ] Run a fresh full backend suite and record the real current failure list (do this FIRST, before assuming the Phase 1 audit's numbers still hold)
- [ ] Add ruff + mypy to the api image; minimal permissive config
- [x] Re-confirm the fresh run is still clean (done at doc-writing time, 2026-07-16: 100% pass, exit 0 — re-check once more at execution start since it visibly moved once already)
- [ ] Flip CI trigger to `on: pull_request` (keep `workflow_dispatch`)
- [ ] Decide on `make verify-fast` vs. relying on the existing `verify` skill; implement or document the decision
- [ ] Update `CLAUDE.md`/`verify` skill to match the new reality

## Execution Journal (Mutable)
- Current Stage: `not started`
- Workflow Status: `blocked`
- Provider/Model: `<provider>/<model>`
- Last Updated: `2026-07-16`

## Deterministic Gate Results (Mutable)
_Append command-level evidence here._
- `full backend suite (fresh, 2026-07-16)`: `pass` — `docker compose run --rm api pytest -q`, clean isolated run, 100% pass, exit 0, no `test_uob_*`/`test_ingest_uob_*` failures. Re-run at execution start to confirm still current.
- `lint`: `<pass|fail|skip>` — `<notes>`
- `typecheck`: `<pass|fail|skip>` — `<notes>`
- `ci trigger`: `<pass|fail|skip>` — `<notes>`

## Human Action Summary (Mutable)
- Next expected action: `<command or decision>`
- Open questions:
  - Does this repo already have a `requirements-dev.txt` convention, or should ruff/mypy go straight into `api/requirements.txt`? Check before assuming.
