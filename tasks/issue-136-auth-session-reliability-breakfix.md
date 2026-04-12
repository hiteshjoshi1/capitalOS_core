# Issue 136: Auth Session Reliability Breakfix

## Objective
- Stop unexpected user logout behavior.
- Make auth/session handling behave like a normal production app:
  - users stay signed in across reloads and routine usage
  - users are not logged out by transient refresh problems
  - logout only happens on explicit logout, real session expiry, or a security-invalidated session

## Problem Statement
- Users are getting logged out unexpectedly.
- The current system appears too brittle around:
  - bootstrap refresh
  - refresh-token rotation
  - multi-tab behavior
  - transient network failures
- This is not an AI Sage issue. It is a core application session-reliability issue.

## Why This Matters
- Unexpected logout breaks trust immediately.
- It makes every other workflow feel unstable, including:
  - AI Sage
  - dashboard usage
  - ongoing research sessions
  - multi-step investment work

## Central Product Idea
- Session reliability should follow normal industry practice:
  - refresh should preserve a valid session, not make it fragile
  - a temporary failure should not immediately destroy local auth state
  - the user should only be forced out when the session is truly invalid

## Known Risk Areas To Investigate
- Frontend access token is memory-only.
- App bootstrap depends on `/auth/refresh` succeeding immediately.
- Frontend clears local user state quickly on refresh failure.
- Backend rotates and revokes refresh sessions on every refresh call.
- That rotation strategy may create race conditions across:
  - multiple tabs
  - concurrent requests
  - back-to-back refresh attempts

## User Intent
- The user expects to remain signed in while actively using the app.
- The user does not expect refresh or reload to behave like logout.
- The user expects explicit logout to be the normal sign-out path.

## Scope
- Investigate and fix unexpected sign-out behavior.
- Make bootstrap auth more resilient.
- Make refresh behavior robust under concurrent / repeated requests.
- Prevent transient refresh/network failures from immediately clearing a valid session.
- Add tests for realistic session lifecycle behavior.

## Out Of Scope
- New auth providers
- SSO / OAuth
- MFA
- Full auth redesign beyond what is necessary to make sessions reliable
- UI polish unrelated to session reliability

## Acceptance Criteria
- [ ] Reloading the app does not log out a valid signed-in user.
- [ ] Opening multiple tabs does not randomly invalidate the session.
- [ ] Concurrent or near-concurrent refresh attempts do not break the session.
- [ ] Short-lived refresh/network failures do not immediately force logout.
- [ ] Explicit `/auth/logout` still reliably signs the user out.
- [ ] Truly invalid / expired refresh sessions still produce logout behavior.
- [ ] Frontend and backend tests cover:
  - bootstrap refresh success
  - bootstrap refresh failure handling
  - refresh-token rotation behavior
  - multi-request / multi-tab refresh scenarios
  - explicit logout semantics

## Product Guardrails
- Do not weaken security just to hide the problem.
- Do not add hacks that make auth state inconsistent between frontend and backend.
- Do not treat a transient transport failure as proof that the user session is invalid.
- Fix the lifecycle correctly rather than layering retries blindly.

## Suggested Areas To Inspect
- `web/src/lib/api.ts`
- `web/src/context/AuthContext.tsx`
- `api/app/routers/auth.py`
- `api/app/services/auth.py`
- existing auth coverage in:
  - `web/src/__tests__/AuthContext.test.tsx`
  - `web/src/__tests__/api.coverage.test.ts`
  - backend auth tests

## Verification Plan
- `make api-rebuild`
- `make web-rebuild`
- `make test-backend`
- `make test-frontend`
- `make e2e`
- Manually verify:
  - login
  - reload while signed in
  - open second tab while signed in
  - idle then continue using app
  - explicit logout

## Human Notes
- Treat this as a breakfix, not a feature.
- The system should be biased toward preserving a valid session, while still respecting true expiry and explicit logout.
- The key question is:
  `Does the app behave like a stable signed-in product, or like a fragile demo?`

## Human Approval Gate
- [ ] Approved for implementation

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
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
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
**Current Stage**: `deterministic_gates`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: Implemented auth session reliability fixes across backend and frontend. Backend gets a concurrent refresh grace window (30s) with revoke_reason tracking so multi-tab rotation races don't cause logout. Frontend stops treating transient network/server errors as auth failures — only definitive 401s trigger logout. Bootstrap distinguishes AuthSessionExpiredError from network errors. All 342 backend, 173 frontend, 13 e2e, and 187 orch tests pass.
- next_action: Inspect deterministic gate failures, apply mitigations, then rerun the workflow.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- latest_failed_checks: `api-smoke`
- retry_gate_pending: `no`
- retry_detail: `api-smoke` stopped after attempt 1/3: Code failure with no auto-fix available: response = self.parent.error(
- blocked_reason: Deterministic gates failed: api-smoke
- stopped_due_to: Verification remained red after the available automated recovery steps.

## Active Requirements
- Acceptance criterion: Reloading the app does not log out a valid signed-in user.
- Acceptance criterion: Opening multiple tabs does not randomly invalidate the session.
- Acceptance criterion: Concurrent or near-concurrent refresh attempts do not break the session.
- Acceptance criterion: Short-lived refresh/network failures do not immediately force logout.
- Acceptance criterion: Explicit /auth/logout still reliably signs the user out.
- Acceptance criterion: Truly invalid/expired refresh sessions still produce logout behavior.
- Acceptance criterion: Frontend and backend tests cover: bootstrap refresh success, bootstrap refresh failure handling, refresh-token rotation behavior, multi-request/multi-tab refresh scenarios, explicit logout semantics.

## Prepare
Checked out `feature/issue-136-auth-session-reliability-breakfix` from `main` and ensured task file exists.

## Plan Summary
1) Add revoke_reason column to auth_sessions (migration + conftest). 2) Backend refresh endpoint: tag rotated sessions as 'rotation', logged-out as 'logout'; on revoked-token refresh, if reason='rotation' and within 30s grace window, find active session and rotate it instead of returning 401. 3) Frontend api.ts: only call notifyAuthFailure() on HTTP 401/403, not on network/5xx errors; export AuthSessionExpiredError class; throw it on skipAuth 401. 4) AuthContext bootstrap: only clear token/user on AuthSessionExpiredError, not generic errors. 5) Tests for all new behaviors.

### Architecture Decisions
- Concurrent refresh grace window uses revoke_reason='rotation' column to distinguish token rotation from explicit logout — so logout-revoked tokens are never recovered within the grace window.
- AuthSessionExpiredError is a typed Error subclass exported from api.ts to let callers distinguish real session expiry from transient network failures.
- Grace window is configurable via AUTH_REFRESH_GRACE_SECONDS env var (default 30s, 0 disables it).
- callRefreshEndpoint only triggers notifyAuthFailure on HTTP 401/403; network errors and 5xx are treated as transient — auth state is preserved.

### Acceptance Criteria
- Reloading the app does not log out a valid signed-in user.
- Opening multiple tabs does not randomly invalidate the session.
- Concurrent or near-concurrent refresh attempts do not break the session.
- Short-lived refresh/network failures do not immediately force logout.
- Explicit /auth/logout still reliably signs the user out.
- Truly invalid/expired refresh sessions still produce logout behavior.
- Frontend and backend tests cover: bootstrap refresh success, bootstrap refresh failure handling, refresh-token rotation behavior, multi-request/multi-tab refresh scenarios, explicit logout semantics.

### Planned Paths
- `migrations/039_auth_sessions_revoke_reason.sql`
- `api/app/routers/auth.py`
- `api/tests/conftest.py`
- `api/tests/test_auth.py`
- `web/src/lib/api.ts`
- `web/src/context/AuthContext.tsx`
- `web/src/__tests__/AuthContext.test.tsx`
- `web/src/__tests__/api.test.ts`

## Build Summary
Implemented auth session reliability fixes across backend and frontend. Backend gets a concurrent refresh grace window (30s) with revoke_reason tracking so multi-tab rotation races don't cause logout. Frontend stops treating transient network/server errors as auth failures — only definitive 401s trigger logout. Bootstrap distinguishes AuthSessionExpiredError from network errors. All 342 backend, 173 frontend, 13 e2e, and 187 orch tests pass.

### Changed Files
- `api/app/routers/auth.py`
- `api/tests/conftest.py`
- `api/tests/test_auth.py`
- `migrations/039_auth_sessions_revoke_reason.sql`
- `tasks/issue-136-auth-session-reliability-breakfix.md`
- `web/src/__tests__/AuthContext.test.tsx`
- `web/src/__tests__/api.test.ts`
- `web/src/context/AuthContext.tsx`
- `web/src/lib/api.ts`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: FAIL (exit 2)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented auth session reliability fixes across backend and frontend. Backend gets a concurrent refresh grace window (30s) with revoke_reason tracking so multi-tab rotation races don't cause logout. Frontend stops treating transient network/server errors as auth failures — only definitive 401s trigger logout. Bootstrap distinguishes AuthSessionExpiredError from network errors. All 342 backend, 173 frontend, 13 e2e, and 187 orch tests pass.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` Reloading the app does not log out a valid signed-in user.: Backend grace window handles concurrent rotation races on reload. Frontend bootstrap only clears state on AuthSessionExpiredError (true 401), not on transient errors. Verified by test_auth_refresh_grace_window_concurrent and AuthContext 'does not force logout on transient network error' tests.
- `pass` Opening multiple tabs does not randomly invalidate the session.: Backend refresh endpoint: when a recently-rotated token (revoke_reason='rotation', within 30s) is presented, it finds the active replacement session and rotates it instead of returning 401. Covered by test_auth_refresh_grace_window_concurrent.
- `pass` Concurrent or near-concurrent refresh attempts do not break the session.: Same grace window mechanism handles concurrent refresh requests. refreshInFlight deduplication in api.ts handles same-tab concurrent calls.
- `pass` Short-lived refresh/network failures do not immediately force logout.: callRefreshEndpoint no longer calls notifyAuthFailure() on network errors (catch block). AuthContext bootstrap no longer calls setAccessToken(null) on non-AuthSessionExpiredError errors. Covered by new frontend tests.
- `pass` Explicit /auth/logout still reliably signs the user out.: Logout sets revoke_reason='logout' which is excluded from grace window recovery. test_auth_refresh_grace_window_logout_not_recovered verifies old cookie returns 401 even within grace window after logout.
- `pass` Truly invalid/expired refresh sessions still produce logout behavior.: Tokens without revoke_reason='rotation' (expired, unknown, security-revoked) return 401. test_auth_refresh_requires_cookie and reuse-after-grace-window behavior tested. AuthSessionExpiredError is thrown and caught by AuthContext to clear state.
- `pass` Frontend and backend tests cover all required session lifecycle scenarios.: Backend: test_auth_refresh_rotates_session (rotation+strict), test_auth_refresh_grace_window_concurrent (multi-tab), test_auth_refresh_grace_window_logout_not_recovered (explicit logout). Frontend: AuthContext bootstrap success/failure/transient-error tests, api.test.ts AuthSessionExpiredError on 401, non-AuthSessionExpiredError on 500, network error behavior.

### Risk Flags
- The 30s grace window is a deliberate security trade-off (standard industry practice). Security-conscious deployments can set AUTH_REFRESH_GRACE_SECONDS=0 to disable it.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- api-smoke: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260412T123409Z_api-smoke_attempt1.log, notes=Code failure with no auto-fix available: response = self.parent.error(

## Blockers
- Deterministic gates failed: api-smoke

## Permanently Failed / Gave Up
- Stop reason: Deterministic gates failed: api-smoke
- Attempted mitigations:
- mitigation: Code failure with no auto-fix available: response = self.parent.error(
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->
