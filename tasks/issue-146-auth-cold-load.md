# Issue 146: Cold load: remove the three sequential auth calls

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/146

## Objective
- A page reload makes one auth request before any protected route renders, not three
  sequential ones (POST /auth/refresh, then GET /auth/me, then GET /auth/preferences).
- Theme/accent preferences never block rendering.

## Why there were three calls (and which are needed)
- `POST /auth/refresh`: **needed**. The access token lives only in JS memory (never in
  storage), so after a reload the HttpOnly refresh cookie (`capitalos_refresh[_<instance>]`,
  #65) is the only credential; refresh trades it for a new access token.
- `GET /auth/me`: **not needed as a separate call**. It existed only because refresh
  returned just a token, and RequireAuth needs the user object.
- `GET /auth/preferences`: **not needed before render**. It only drives theme + accent,
  which ThemeProvider has already painted from localStorage; it was awaited inside the
  `loading` window anyway.

## Architecture Decisions
- `/auth/login` and `/auth/refresh` return `AuthSessionResponse` = the existing token fields
  plus additive `user` (AuthMeResponse shape) and `preferences` (UserPreferencesResponse
  shape). No field removed. All three refresh success paths (claim, grace-window) include them.
- Preferences on login/refresh are read-only: a missing row returns the defaults (same
  values GET /auth/preferences would create) without inserting.
- Web: `refreshSessionNow()` (same deduped in-flight promise as `refreshAccessTokenNow()`)
  returns the whole response. AuthProvider uses `user` (falls back to `/auth/me` if absent)
  and applies `preferences` in the same tick as `setUser`; if absent, `/auth/preferences`
  is fetched in the background. `authMe` / `getPreferences` stay for other callers.
- ThemeProvider: replaced the "server sync" counter + `setTimeout(0)` reset with a ref of
  the values the server is known to hold. The counter raced React's render when preferences
  arrived outside an event handler and sent two redundant PATCH /auth/preferences on every load.

## Acceptance Criteria
- [x] Cold start makes exactly one auth request before rendering a protected route.
- [x] Server theme/accent still applied on cold start and after login.
- [x] Preferences never block rendering (background fetch if absent; localStorage fallback).
- [x] Refresh/login failure paths unchanged (status codes and bodies).
- [x] API contract: additive fields only; TS types mirror backend.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_auth_session_payload.py tests/test_auth.py -q`
- `cd web && npx vitest run src/__tests__/authColdLoad.test.tsx src/__tests__/AuthContext.test.tsx src/__tests__/ThemeContext.test.tsx`
- Browser: isolated stack, sign in as demo, reload: only `POST /api/auth/refresh` before the
  protected route renders, theme from the server applied.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `backend tests (auth)`: pass — 29 passed (test_auth_session_payload, test_auth, test_auth_secret_and_signup)
- `frontend`: pass — vitest 43 files / 289 tests; `tsc -b` 0; `eslint .` 0
- `make verify`: pass — backend 478 passed, frontend 43 files / 289 tests, lint + typecheck clean
- `e2e (Playwright, isolated stack)`: pass — reload: `POST /api/auth/refresh` at +134ms,
  protected route rendered at +285ms, no other auth request before it; data-theme=light and
  accent from the server applied. A second refresh at ~+1.3s comes from the realtime
  WebSocket reconnect under React StrictMode (dev only), not from the auth bootstrap.

## Extra Files Changed (Codex Mutable)
- `web/src/context/ThemeContext.tsx` — reason: the echo-PATCH race surfaced by the new
  cold-load test (two redundant PATCH requests per load).
