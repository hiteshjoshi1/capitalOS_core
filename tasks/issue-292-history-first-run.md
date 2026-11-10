# Issue 292: History first run: generate in the background with progress, cap FX fetches, default range = the data's span, explain "carried"

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/292

## Objective
- "Generate history" no longer blocks one request for dozens of months: it runs in the background and the page shows progress.
- FX provider calls during a run are capped: past rates are fetched once (#290's capped back-fill), then every month is valued from stored rates.
- The default range is the span of the user's data; "carried" is explained in plain words.

## Architecture Decisions
- D-89: an in-memory run per (user, currency) in a daemon thread with its own session (`app/valuation/history_job.py`), polled via `GET /dashboard/net-worth-timeline/generate/status`; `POST /dashboard/net-worth-timeline/generate` starts one (or returns the running one). A finished run leaves a `job_runs` row (`history_generate`).
- FX: `fx_backfill.run_backfill` first (capped by `FX_BACKFILL_MAX_REQUESTS`), then the months inside `fx.stored_rates_only()` (a context variable checked where a read would call the provider, `fx.provider_allowed`).
- Default range: `history_span` = the month of the earliest dated fact (balances, positions, cash, transactions, wallet snapshots) to now, ≤ 120 months; returned as `data_span` on the timeline (additive). The page applies it once unless a range was picked; "All" stretches to the span when it's over 5 years.
- The old synchronous `POST /net-worth-timeline/backfill` stays (API contract: only add).

## Acceptance Criteria
- [x] Generate runs in the background with a progress line and bar (stage FX, then "Valuing month N of M").
- [x] No provider call while months are valued; the FX back-fill's cap applies; what it left is said on the page.
- [x] Generate with no range = the span of the data; the page's default range covers the span.
- [x] One plain line explains "carried"; the chart legend says it too.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_history_job.py tests/test_wealth_timeline.py`
- `cd web && npx vitest run src/__tests__/WealthHistory.test.tsx`
- Test instance: History → Refresh: the progress card shows, then the chart reloads.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [ ] Verify semantic intent is achieved (test instance)
