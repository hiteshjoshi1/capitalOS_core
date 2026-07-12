# Issue 196: Market Data Per-Symbol Stale Reason Taxonomy

## Objective
- The new Market Data screen design (`design_handoff_capitalos_wealth/screens/Market Data.dc.html`) shows a curated, human-readable reason per stale symbol when an exchange row is expanded — e.g. "Rate limited" or "No trade reported" — distinct from the fresh/stale status pill itself.
- Today, `market_data_run_items.source_note` (surfaced as `failure_reason` in `_exchange_diagnostics()`, `api/app/market_data/service.py`) is free-form text, not a curated taxonomy: it is either `None`, the literal string `"missing/invalid price from provider"`, `"resolved via fallback"`, or the raw `str(exception)` bubbled up from whichever provider call failed (`api/app/market_data/providers.py` raises generic `ValueError`/`httpx` exceptions with no rate-limit- or no-trade-specific classification — grep of `providers.py` shows no "rate limit" string anywhere).
- Producing the exact curated strings the design shows would mean guessing a provider error taxonomy without visibility into real provider failure modes (HTTP 429 bodies, "no trade" sentinel responses, etc. differ per provider — EODHD, Finnhub, EODData, yfinance, Yahoo). This is a product/data decision that needs confirmation with real provider behavior, not something to fabricate client-side.

## Architecture Decisions
- Decision 1: Introduce a small closed `reason_code` enum (e.g. `RATE_LIMITED`, `NO_TRADE_REPORTED`, `PROVIDER_ERROR`, `MISSING_MAPPING`) populated in `api/app/market_data/service.py` at the point each provider call in `api/app/market_data/providers.py` fails or returns no data, replacing the current freeform exception-text capture.
- Decision 2: Persist `reason_code` alongside the existing `source_note` column on `market_data_run_items` (additive migration; keep `source_note` for the raw/debug text) rather than replacing it, so nothing existing regresses.
- Decision 3: Providers must actually surface enough signal to classify (e.g. HTTP status code, provider-specific "no data" response shape) — needs a short investigation into each of the 5 provider integrations in `api/app/market_data/providers.py` before committing to the enum's exact members.

## Acceptance Criteria
- [ ] `market_data_run_items` gains a `reason_code` column populated by a curated, closed set of values (not raw exception text) for every stale/failed symbol
- [ ] `_exchange_diagnostics()` (`api/app/market_data/service.py`) exposes `reason_code` (and keeps `failure_reason`/`source_note` as the raw debug string) per symbol
- [ ] `GET /market-data/status` response includes the new field so the frontend can render it directly instead of the freeform `source_note`
- [ ] At least the two design-called-out cases ("Rate limited", "No trade reported") are reliably distinguishable from generic provider errors for the providers currently in use
- [ ] No existing fields removed; `source_note` unchanged for backward compatibility

## How To Test
- Run `make test-backend` and confirm new/updated tests in `api/tests/test_market_data.py` cover reason-code classification for at least a simulated rate-limit response and a simulated no-trade response per provider path exercised in tests today.
- Manually trigger `POST /market-data/refresh-now` against a provider sandbox/mock that returns a 429, and confirm the resulting `GET /market-data/status` row shows `reason_code: "RATE_LIMITED"`.

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
- Last Updated: `2026-07-09`

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
- Stop reason: `Deferred at design-handoff time — flagged by the Data Hub/Stocks restyle work (this session) as a genuine backend gap rather than implemented speculatively, since it requires confirming real provider error shapes before committing to a reason-code enum.`
- Attempted mitigations:
  - `Frontend (Market Data screen restyle) ships showing the existing freeform source_note text with a plain "Reason unavailable" fallback, rather than fabricating "Rate limited"/"No trade reported" strings.`
- Suggested human action: `Confirm the reason-code enum members and investigate actual failure response shapes for each configured provider (EODHD, Finnhub, EODData, yfinance, Yahoo) before implementation.`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Prioritize and schedule this issue; confirm enum members with product before implementation.`
- Open questions:
  - `Do all 5 configured providers even expose enough signal (HTTP status, response body) to distinguish "rate limited" from "no trade reported" from a generic error today?`
- If PR raised but intent partial:
  - unmet criteria: `n/a — not started`
  - follow-up issue: `n/a`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-196-market-data-stale-reason-taxonomy`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.6-sol`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: market_data_run_items gains a reason_code column populated from a closed taxonomy for failed symbols.
- Acceptance criterion: _exchange_diagnostics() exposes reason_code while preserving failure_reason from source_note.
- Acceptance criterion: GET /market-data/status includes reason_code per symbol.
- Acceptance criterion: Rate limited and No trade reported outcomes are distinguishable from generic provider errors.
- Acceptance criterion: No existing fields are removed and source_note remains backward compatible.

## Prepare
Checked out `feature/issue-196-market-data-stale-reason-taxonomy` from `main` and verified task file exists.

## Plan Summary
Inspected provider behavior and refresh flow, added a constrained additive reason_code column, classified provider outcomes per symbol, exposed and rendered curated reasons, and completed all required verification gates.

### Architecture Decisions
- Use the closed values RATE_LIMITED, NO_TRADE_REPORTED, PROVIDER_ERROR, and INVALID_PRICE.
- Persist reason_code alongside source_note, retaining source_note and failure_reason as raw debugging information.
- Classify HTTP 429 and yfinance YFRateLimitError signals as RATE_LIMITED, successful calls without usable quotes as NO_TRADE_REPORTED, invalid values as INVALID_PRICE, and other exceptions as PROVIDER_ERROR.
- Preserve provider failures per request batch so one batch error is not incorrectly assigned to symbols from another batch.
- Render human-readable frontend labels from reason_code while falling back to legacy failure_reason values.

### Acceptance Criteria
- market_data_run_items gains a reason_code column populated from a closed taxonomy for failed symbols.
- _exchange_diagnostics() exposes reason_code while preserving failure_reason from source_note.
- GET /market-data/status includes reason_code per symbol.
- Rate limited and No trade reported outcomes are distinguishable from generic provider errors.
- No existing fields are removed and source_note remains backward compatible.

### Planned Paths
- `api/app/market_data/`
- `api/tests/`
- `migrations/`
- `web/src/lib/api.ts`
- `web/src/routes/MarketData.tsx`
- `web/src/__tests__/MarketData.test.tsx`
- `tasks/issue-196-market-data-stale-reason-taxonomy.md`

## Build Summary
Implemented per-symbol stale reason taxonomy across persistence, provider classification, status API diagnostics, frontend rendering, and tests.

### Changed Files
- `api/app/market_data/providers.py`
- `api/app/market_data/service.py`
- `api/tests/conftest.py`
- `api/tests/test_market_data.py`
- `migrations/065_market_data_stale_reason_code.sql`
- `tasks/issue-196-market-data-stale-reason-taxonomy.md`
- `web/src/__tests__/MarketData.test.tsx`
- `web/src/lib/api.ts`
- `web/src/routes/MarketData.tsx`

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
- None

## Agent Run Summary
Implemented per-symbol stale reason taxonomy across persistence, provider classification, status API diagnostics, frontend rendering, and tests.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.6-sol`

### Semantic Checks
- `pass` market_data_run_items gains a reason_code column populated by a curated, closed set for every stale or failed symbol.: Migration 065 adds the column, backfills historical failed rows, constrains allowed values, and requires codes for missing or invalid statuses; the database invariant query found no uncoded failed rows.
- `pass` _exchange_diagnostics() exposes reason_code and keeps failure_reason/source_note as raw debug text.: Latest run-item queries select both reason_code and source_note; diagnostics return reason_code separately while failure_reason remains sourced from source_note.
- `pass` GET /market-data/status includes the new field.: Status endpoint tests assert reason_code values returned through GET /market-data/status for seeded, rate-limited, and no-trade cases.
- `pass` Rate limited and No trade reported are reliably distinguishable from generic provider errors for current providers.: Parameterized tests cover both outcomes across EODHD, Finnhub, EODData, yfinance, and Yahoo; EODData additionally verifies real HTTP 429 and 500 propagation.
- `pass` No existing fields are removed and source_note is unchanged for backward compatibility.: The schema change is additive, failure_reason remains present, raw exception text remains in source_note, frontend types only add reason_code, and all contract suites pass.

### Risk Flags
- Backend ruff and mypy were unavailable in the API image, so their portions were skipped by the successful Make targets.
- The local Postgres database has a pre-existing collation-version mismatch warning.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-196-market-data-stale-reason-taxonomy`.
<!-- MACHINE_RENDERED_END -->
