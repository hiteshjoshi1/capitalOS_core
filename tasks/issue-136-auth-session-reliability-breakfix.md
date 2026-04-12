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
