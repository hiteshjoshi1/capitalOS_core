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
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
