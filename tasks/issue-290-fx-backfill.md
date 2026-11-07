# Issue 290: FX back-fill and one page-level FX note

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/290

## Objective
- Past months stop leaving foreign holdings out for want of a rate: past rates are fetched once for
  the span of the user's data.
- One FX note per page instead of a copy on every card, with a way to fetch what's missing.

## Architecture Decisions
- `app/fx_backfill.py` (D-75): span from the user's dated facts (balance, position and cash snapshots,
  transactions; ownership via `accounts.user_id`), one lookback early to yesterday. Covered weekday =
  a Frankfurter row on it, or inside a hole of at most 5 days between stored rows (holidays). Uncovered
  days become ranges (gaps up to 7 days joined, at most 366 days each, newest first), capped at
  `FX_BACKFILL_MAX_REQUESTS` (12). Rows stored through `fx._store_rows` (History dirty, #138; cache
  dropped, #188). Currencies the provider doesn't publish are named. A `job_runs` row per run
  (`fx_backfill`), shown on Data Hub once it has run.
- `GET /fx/backfill-plan` (any user, read only), `POST /fx/backfill` (admin, #152). After an import
  (`/ingest/upload`, `/ingest/ibkr`) it runs in a background thread for the importing user, unless
  `FX_DISABLE_REMOTE=1` or `FX_BACKFILL_AFTER_IMPORT=0`.
- Frontend: `FxNoteScope` in `PageShell`; every `<FxNote>` inside reports its sources and renders
  nothing; `<PageFxNote>` under the month bar shows them once, with "Fetch missing rates" (admins) or
  "An admin can fetch the missing rates." Data Hub gains a "Past exchange rates" card.
- No migration; API fields only added (new endpoints, new job name).

## Acceptance Criteria
- [x] Span, stored days skipped, idempotent re-run, cap with the rest reported, History dirty, a failed
      range recorded not raised, unsupported currency named, admin-only (`tests/test_fx_backfill.py`).
- [x] One note per page combining every card's gaps; admin action and member text (`PageFxNote.test.tsx`).
- [ ] On the test instance: Data Hub "Fetch past rates", then History's past months include foreign holdings.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_fx_backfill.py`
- `cd web && npx vitest run src/__tests__/PageFxNote.test.tsx`

<!-- IMMUTABLE_PLAN_END -->
