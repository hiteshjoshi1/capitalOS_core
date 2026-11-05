# Issue 202: Per-user timezone for months and anchors, and base currency saved on the server

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/202

## Objective
- Month logic (open month, when a month's anchor passes, "vs last month", History completion,
  card-transaction month boundary) follows each user's **home timezone**, not one app-wide `TZ`.
- The base currency is saved on the server (the #150 follow-up), so it follows the user across devices.
- Nothing changes for the existing (Singapore) household.

## Architecture Decisions
- Owner decisions (fixed): the user's home timezone is a setting, not the device's; quote and FX
  date lookups stay on market/UTC dates (D-44); job schedules are unchanged.
- Migration 077: `user_preferences.timezone` (IANA, NULL = the app's `TZ`), `timezone_from_app`
  (TRUE for every account that existed before 077: they keep following the app's `TZ`, whatever
  `.env` sets, until they pick one), `base_currency` (NULL until set; `^[A-Z]{3}$` check). Every
  existing user gets a preferences row. A SQL migration can't read the container's `TZ`, so
  "follow the app's TZ" is stored as a flag instead of copying a value.
- `app.core.clock`: `app_now()`/`app_today()` use the timezone bound for the current context.
  `RequestTimezoneMiddleware` gives each HTTP/WebSocket request a mutable slot; the auth
  dependency fills it with the user's timezone (the slot is shared with the threadpool copies
  of the context, so the endpoint sees it). `_current_anchor_ts` is already frozen per request
  (D-28 request memo, keyed by timezone). Background work uses `use_timezone(...)`: the
  History refresh after jobs runs each user in their own timezone, and dirty marks check each
  target user's own latest completed anchor.
- Card transactions: the month boundary is midnight of the anchor date in the user's
  timezone. A date-only timestamp (stored as 00:00 UTC, as statement imports write them) is
  that calendar date in every timezone and is compared by date; a timestamp with a time is an
  instant compared with local midnight. For Singapore and date-only rows nothing moves; only
  a timed card row between 00:00 and 08:00 SGT on the anchor date moves to the next month.
- Valuation cache (D-28): the shared-entry stamp carries the user's timezone and today's date
  in it. Changing timezone (PATCH) marks History dirty (D-29) from the user's earliest card
  transaction (the only stored input whose month boundary is a local midnight); which months
  are completed is decided on read, in the new timezone (provisional rows are deleted then).
- API (add-only): `UserPreferencesResponse` gains `timezone` (effective), `timezone_source`
  (`user` | `app` | `unset`) and `base_currency`; PATCH accepts `timezone` and `base_currency`
  (one of SGD/USD/HKD/INR). `/auth/login` and `/auth/refresh` carry them (D-26).
- Web: first sign-in fills an `unset` timezone from `Intl.DateTimeFormat().resolvedOptions()`;
  the base-currency store (#150) paints the per-browser value first, then applies the server's
  (or sends the browser's saved choice up when the server has none); the picker and Settings
  save to the server. Settings → "Timezone and currency" changes both.
- Not in scope: spending/cash-flow month windows (`/spending/*`, `_cashflow`) still use UTC
  month starts; display-side "days old" labels (owner: later).

## Acceptance Criteria
- [x] Two synthetic users (Asia/Singapore, America/New_York) at the same instant see their own
      open month and completed months (`test_two_users_at_the_same_instant_see_their_own_months`).
- [x] Golden + invariant tests extended with a US-timezone household moment (`first_us` golden,
      cache on/off invariant for it, `test_us_household_dashboard_and_history_agree`).
- [x] Existing goldens (`mid`, `first`) unchanged.
- [ ] The owner's real numbers are unchanged (test-instance comparison; coordinator).
- [x] Base currency persists across devices (server) with the per-browser value as first paint.

## How To Test
- `make verify`.
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_user_timezone.py tests/test_valuation_golden.py tests/test_valuation_invariants.py`.
- `cd web && npx vitest run src/__tests__/UserTimezoneAndCurrency.test.tsx`.
- Test instance: compare Wealth Overview, History and Liabilities with the real app; Settings →
  Timezone and currency shows "Asia/Singapore (the app's default)".

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `make verify`: see the PR description (lint, typecheck, backend and frontend tests).
- Migration 077 applied on an isolated Postgres (`make db-migrate`), and re-run inside a
  rolled-back transaction with synthetic users to check the backfill and the currency check.

## Extra Files Changed (Codex Mutable)
- `api/tests/conftest.py` — reason: the SQLite `user_preferences` DDL gains the new columns, and
  `clear_db` clears `user_preferences` so one test's home timezone can't leak into the next.
- `api/tests/test_auth_session_payload.py` — reason: asserted the exact preferences dict; now
  checks the original fields are present (fields are only added).
