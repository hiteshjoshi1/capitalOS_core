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
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
