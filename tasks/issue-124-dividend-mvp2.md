# Issue 124: Dividends MVP 2

## Objective
- Deliver a realized-dividends MVP with period totals (month/quarter/year) and company-level breakdown.
- Add a dedicated `Wealth > Dividends` page and a compact dividend history + yield view in stock holdings.
- Keep scope intentionally simple: no expected-payout engine and no reconciliation engine in this stage.

## Architecture Decisions
- Decision 1: Use realized cash transactions as source of truth for dividends, withholding, and net payout.
- Decision 2: Support rough tax estimation using configurable assumed tax rate inputs (API/query level), not treaty logic.
- Decision 3: Keep internal API modular with dedicated `/dividends/*` endpoints and reuse existing FX conversion service.
- Decision 4: Improve ingestion for brokerage trades by persisting `transactions.asset_id` and `transactions.quantity` when available.
- Decision 5: Place dividends navigation under `Wealth`, and keep account/platform setup in `Operations`.

## Acceptance Criteria
- [x] Add `Dividends` navigation under `Wealth`.
- [x] Create a dedicated dividends page route with:
- [x] period summary (monthly/quarterly/yearly)
- [x] by-company totals
- [x] gross/withholding/net and rough post-tax payout columns
- [x] Add a compact dividend history + yield panel in stock holdings.
- [x] Implement backend dividends APIs:
- [x] `GET /dividends/summary`
- [x] `GET /dividends/by-company`
- [x] `GET /dividends/history`
- [x] Implement rough tax estimate (`assumed_tax_rate`) in dividends responses.
- [x] Do not implement expected payout calculations.
- [x] Do not implement reconciliation endpoints/workflow.
- [x] Update ingestion so trade transactions can persist `asset_id` and `quantity` where parser data supports it.
- [x] Add/update unit tests for backend and frontend dividend flows.
- [ ] Add/update UI/e2e verification for new nav/page behavior.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement backend changes (if required)
- [x] Implement frontend changes (if required)
- [x] Add/update tests
- [x] Run verification commands

## Implementation Plan
1. Backend API and schema integration
- Add a new dividends router with endpoints for summary, by-company, and per-asset history.
- Reuse transaction categorization conventions (`Brokerage::Dividend`, `Brokerage::Tax`, mapped categories) for realized dividend flows.
- Add period grouping logic (`month`, `quarter`, `year`) and base-currency conversion using `get_rates`.
- Add rough tax estimation fields using `assumed_tax_rate`.

2. Ingestion linkage improvement
- Extend IBKR trade normalization + ingestion insert path so trade transactions can carry `asset_id` and `quantity` where available.
- Keep non-asset cash events (tax/fees/transfers/dividend cash lines without mapping) nullable for `asset_id`/`quantity`.

3. Frontend routes and UI
- Add `Dividends` page under Wealth navigation.
- Build page sections:
- period cards/table (gross, withholding, net, estimated tax, post-tax)
- company breakdown table
- Add compact stock-holdings dividend panel (history + trailing yield) with drill-through link to full dividends page.

4. Test coverage
- Backend: unit tests for period aggregation, company rollup, FX conversion path, and assumed-tax output.
- Frontend: route/component tests for Wealth navigation and Dividends page rendering.
- Playwright: e2e path validating navigation to Dividends and rendered data states.

5. Verification
- Run frontend and backend tests.
- Run Playwright e2e.
- Record evidence in this file after implementation.

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

### Stage 2 Addendum (Holdings-Based Expected Dividends)
- Kept realized dividend logic intact (cash-hit/category-mapped) for reconciliation.
- Added a parallel expected-dividends path based on holdings + corporate actions.
- Added backend endpoint: `GET /dividends/expected/overview`
  - Uses holdings universe from latest positions (stocks/funds).
  - Fetches dividend corporate actions via yfinance provider.
  - Checks entitlement quantity on event date using BUY/SELL transaction history when available; falls back to snapshot quantity.
  - Produces monthly/quarterly/yearly totals and by-company breakdown with rough tax estimates.
- Updated Dividends UI to show both sections:
  - Realized (existing behavior)
  - Expected (new holdings-based behavior)
- Fixed period card semantics:
  - Month/Quarter/Year cards are now anchored to selected month period slices.
  - Company table remains window-based (`from_month` -> `to_month`) and includes event count.
- Fixed expected-dividends consistency:
  - Backend now returns expected month/quarter/year as selected-period totals (anchored to `to_month`).
  - Expected by-company list is aligned to selected year totals, preventing stale prior-year amounts from appearing against current-year totals.
- Added backend and frontend tests for the new expected-dividends flow.

## Verification Evidence (Codex Mutable)
2026-03-28 Stage 1 verification run:

- `make test-backend` -> pass (`122 passed`)
- `make test-frontend` -> pass (`92 passed`)
- `make e2e` -> pass (`12 passed`)
- `make api-rebuild` -> pass (API image rebuilt, container restarted)
- `make api-up` -> pass (API running)
- `docker compose exec api python -c '.../health...'` -> `{"status":"ok"}`
- `docker compose exec api python -c '.../dashboard/summary?month=2026-02...'` -> valid JSON response
- `make web-up` -> pass (Vite dev server started on `http://localhost:5174/` because `5173` was already in use)

Notes:
- Existing e2e suite passes with current changes.
- Dedicated dividends e2e coverage is intentionally deferred to Stage 2 (per gated rollout request).
- `make web-rebuild` currently fails in this repo with `no such service: web` (pre-existing make/docker setup mismatch).

2026-03-28 Stage 2 verification run:

- `make test-backend` -> pass (`127 passed`)
- `make test-frontend` -> pass (`92 passed`)
- `make e2e` -> pass (`12 passed`)
- `make api-up` -> pass (rebuilt/restarted API)
- `GET /dividends/expected/overview?from_month=2026-02&to_month=2026-03...` -> pass
  - sample totals: monthly gross `875.79`, after-tax `862.14` (SGD base)

2026-03-28 Stage 2.1 (expected dividends annualized via cached yield) verification run:

- `make db-migrate` -> pass (new `030_market_dividend_yields.sql` applied)
- `make test-backend` -> pass (`127 passed`)
- `make test-frontend` -> pass (`92 passed`)
- `make typecheck` -> pass (frontend TS compile; backend mypy skipped in container as before)
- `docker compose run --rm api pytest tests/test_dividends.py tests/test_market_data.py -q` -> pass (`9 passed`)
- `docker compose run --rm api python -c "...yf.download(['RELIANCE.NS','TCS.NS','INFY.NS'])..."` -> pass (`empty False`)

Stage 2.1 behavior notes:
- Expected dividends now use cached DB snapshots (`market_dividend_yields`) and do not call live market APIs from `/dividends/expected/overview`.
- Refreshing market data (`POST /market-data/refresh-now`) now also refreshes dividend-yield snapshots in batch for mapped symbols.
- Expected company rows now include `shares`, `yield`, `price`, and `yearly/quarterly/monthly` dividend values.

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._
