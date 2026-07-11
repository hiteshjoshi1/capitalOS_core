# Issue 191: Persist theme and accent-color preference server-side

## Objective
- Move the user's theme (dark/light) and accent-color choice from client-only `localStorage` to a real, server-persisted user preference, so the choice follows the user across devices/browsers.
- Give the frontend a stable contract (`GET`/`PATCH` on the authenticated user's preferences) to read/write these values, replacing the current `ThemeContext` `localStorage` read/write.

## Current State
- `web/src/context/ThemeContext.tsx` persists `theme` (`"dark" | "light"`) to `localStorage` under `capitalos.theme` only. There is no accent-color concept anywhere in the backend or frontend beyond the fixed `--accent` CSS variable.
- As part of the CapitalOS Wealth screens design-handoff implementation, `ThemeContext` was extended to also hold an `accent` value (one of the existing brand swatches), persisted the same way (`localStorage`) as an interim — this issue is the follow-up to make that persistence real/server-backed instead.
- `models/user.py:User` has no preferences/settings columns or related table. `routers/auth.py` (`GET /auth/me`) returns only identity fields.

## Architecture Decisions
- New `user_preferences` table (one row per user, FK to `users.id`), columns: `theme` (enum/string, default `"dark"`), `accent_color` (string hex, default `"#0f7a5c"`), `updated_at`.
- New endpoints on the auth/user router: `GET /auth/preferences` (create-on-read with defaults if missing) and `PATCH /auth/preferences` (partial update, validates `theme` is one of `dark`/`light` and `accent_color` is one of the supported swatch hexes: `#0f7a5c`, `#2b6ddb`, `#8650d9`, `#b5842a`).
- Frontend `ThemeContext` should fetch preferences once on auth bootstrap, fall back to existing `localStorage` value (or defaults) while the request is in flight/if it fails, and `PATCH` on every change — keep `localStorage` as an offline/instant-paint cache, not the source of truth.

## Acceptance Criteria
- [ ] `user_preferences` table + migration exist.
- [ ] `GET /auth/preferences` and `PATCH /auth/preferences` implemented and tested.
- [ ] Signing in on a second browser/device shows the same theme/accent as the first.
- [ ] No regression to existing dark/light theme toggle behavior or accent swatch rendering.

## How To Test
- Run `make test-backend` and confirm new preference endpoint tests pass.
- Run `make test-frontend` and confirm `ThemeContext` tests pass with the new fetch/patch flow (mocked).
- Manual: change theme/accent while logged in as user A, log out, log back in as user A in a different browser profile — confirm the preference persisted.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not started`
- Workflow Status: `blocked`
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
- Stop reason: `Not started — filed from design-handoff implementation pass (2026-07-08) as a flagged backend need, not yet picked up.`
- Attempted mitigations:
  - `Frontend interim: theme + accent persisted client-side via localStorage in ThemeContext, functionally equivalent minus cross-device sync.`
- Suggested human action: `Prioritize and implement the user_preferences table + endpoints described above.`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Schedule for implementation; no blocking dependency on other open issues.`
- Open questions:
  - `Should accent color be restricted to the 4 defined swatches, or open to arbitrary hex input?`
- If PR raised but intent partial:
  - unmet criteria: `n/a — not started`
  - follow-up issue: `n/a`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: Implemented server-side persistence for theme and accent-color user preferences (Issue 191). Added user_preferences table, GET/PATCH /auth/preferences endpoints, and updated ThemeContext + AuthContext to sync with the server while keeping localStorage as an instant-paint fallback.
- next_action: Inspect deterministic gate failures, apply mitigations, then rerun the workflow.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- latest_failed_checks: `lint`, `e2e`
- retry_gate_pending: `no`
- retry_detail: `e2e` stopped after attempt 1/3: Code failure with no auto-fix available: Error: [2mexpect([22m[31mlocator[39m[2m).[22mtoBeVisible[2m([22m[2m)[22m failed
- retry_detail: `lint` stopped after attempt 1/3: Code failure with no auto-fix available: 59:5  error  Error: Calling setState synchronously within an effect can trigger cascading renders
- blocked_reason: Deterministic gates failed: lint, e2e
- stopped_due_to: Verification remained red after the available automated recovery steps.

## Active Requirements
- Acceptance criterion: user_preferences table + migration exist
- Acceptance criterion: GET /auth/preferences and PATCH /auth/preferences implemented and tested
- Acceptance criterion: Signing in on a second browser/device shows the same theme/accent as the first (server-persisted)
- Acceptance criterion: No regression to existing dark/light theme toggle behavior or accent swatch rendering

## Prepare
Checked out `feature/issue-191-user-preferences-theme-accent-persistence` from `main` and verified task file exists.

## Plan Summary
1) Create migrations/063_user_preferences.sql with user_preferences table. 2) Add UserPreference ORM model. 3) Add Pydantic schemas + validation constants. 4) Add GET/PATCH /auth/preferences endpoints with create-on-read and input validation. 5) Update test conftest to include user_preferences table. 6) Add backend tests (9 scenarios). 7) Add frontend API types + methods. 8) Update ThemeContext to PATCH on change and accept server prefs without feedback loop. 9) Update AuthContext to fetch and apply server preferences after auth bootstrap/login. 10) Add frontend tests for both contexts.

### Architecture Decisions
- New user_preferences table (one row per user, FK to users.id) with columns: theme (string, default 'dark'), accent_color (string hex, default '#0f7a5c'), updated_at
- GET /auth/preferences uses create-on-read pattern — inserts defaults if no row exists, then returns
- PATCH /auth/preferences accepts partial updates; validates theme in {'dark','light'} and accent_color in the 4 defined swatches (#0f7a5c, #2b6ddb, #8650d9, #b5842a)
- ThemeContext gains applyServerPreferences() to allow AuthContext to push server values without triggering a PATCH feedback loop (suppression counter pattern)
- api.isAuthenticated() helper added to api object so ThemeContext can guard PATCH calls without importing internal auth tokens
- localStorage retained as instant-paint cache and offline fallback; server is source of truth when authenticated

### Acceptance Criteria
- user_preferences table + migration exist
- GET /auth/preferences and PATCH /auth/preferences implemented and tested
- Signing in on a second browser/device shows the same theme/accent as the first (server-persisted)
- No regression to existing dark/light theme toggle behavior or accent swatch rendering

### Planned Paths
- `migrations/063_user_preferences.sql`
- `api/app/models/user.py`
- `api/app/schemas/auth.py`
- `api/app/routers/auth.py`
- `api/tests/conftest.py`
- `api/tests/test_preferences.py`
- `web/src/lib/api.ts`
- `web/src/context/ThemeContext.tsx`
- `web/src/context/AuthContext.tsx`
- `web/src/__tests__/ThemeContext.test.tsx`
- `web/src/__tests__/AuthContext.test.tsx`

## Build Summary
Implemented server-side persistence for theme and accent-color user preferences (Issue 191). Added user_preferences table, GET/PATCH /auth/preferences endpoints, and updated ThemeContext + AuthContext to sync with the server while keeping localStorage as an instant-paint fallback.

### Changed Files
- `api/app/models/user.py`
- `api/app/routers/auth.py`
- `api/app/schemas/auth.py`
- `api/tests/conftest.py`
- `api/tests/test_preferences.py`
- `migrations/063_user_preferences.sql`
- `tasks/issue-191-user-preferences-theme-accent-persistence.md`
- `web/src/__tests__/AuthContext.test.tsx`
- `web/src/__tests__/ThemeContext.test.tsx`
- `web/src/context/AuthContext.tsx`
- `web/src/context/ThemeContext.tsx`
- `web/src/lib/api.ts`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: FAIL (exit 2)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: FAIL (exit 2)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented server-side persistence for theme and accent-color user preferences (Issue 191). Added user_preferences table, GET/PATCH /auth/preferences endpoints, and updated ThemeContext + AuthContext to sync with the server while keeping localStorage as an instant-paint fallback.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` user_preferences table + migration exist: migrations/063_user_preferences.sql created with user_preferences(user_id PK FK→users, theme VARCHAR default 'dark', accent_color VARCHAR default '#0f7a5c', updated_at TIMESTAMP); applied to Postgres via make db-migrate
- `pass` GET /auth/preferences and PATCH /auth/preferences implemented and tested: Both endpoints added to api/app/routers/auth.py; 9 backend tests in api/tests/test_preferences.py all pass (1031 total passed); manual smoke confirmed correct responses including 422 for invalid inputs and 401 for unauthenticated requests
- `pass` Signing in on a second browser/device shows the same theme/accent as the first: Preferences are stored in user_preferences table keyed by user_id; ThemeContext fetches via GET /auth/preferences on auth bootstrap and applies server values via applyServerPreferences(); manual smoke: PATCH then re-GET confirmed persistence in Postgres
- `pass` No regression to existing dark/light theme toggle behavior or accent swatch rendering: make test-frontend: 223 passed (37 test files) — all pre-existing tests pass; ThemeContext localStorage fallback preserved; make web-rebuild: 296 modules compiled cleanly; make typecheck: no errors

### Risk Flags
- Pre-existing lint errors in WealthHistoryChart.tsx and WealthOverview.tsx — confirmed not introduced by this change via stash verification
- Large JS bundle (855 kB gzip: 247 kB) pre-existed — no regression

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- lint: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260711T055330Z_lint_attempt1.log, notes=Code failure with no auto-fix available: 59:5  error  Error: Calling setState synchronously within an effect can trigger cascading renders
- e2e: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260711T055352Z_e2e_attempt1.log, notes=Code failure with no auto-fix available: Error: [2mexpect([22m[31mlocator[39m[2m).[22mtoBeVisible[2m([22m[2m)[22m failed

## Blockers
- Deterministic gates failed: lint, e2e

## Permanently Failed / Gave Up
- Stop reason: Deterministic gates failed: lint, e2e
- Attempted mitigations:
- mitigation: Code failure with no auto-fix available: Error: [2mexpect([22m[31mlocator[39m[2m).[22mtoBeVisible[2m([22m[2m)[22m failed
- mitigation: Code failure with no auto-fix available: 59:5  error  Error: Calling setState synchronously within an effect can trigger cascading renders
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->
