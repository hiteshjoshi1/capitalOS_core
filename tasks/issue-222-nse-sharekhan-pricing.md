# Issue 222: Indian (NSE) holdings never priced: Sharekhan parser swaps ticker/name, and pre-link uploads have no asset

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/222

## Objective
- Sharekhan holdings get live NSE prices instead of staying at the uploaded file's prices.
- Existing Sharekhan instruments (imported with ticker/name swapped and no asset) are repaired.
- A holding that can't be priced is visible (run warning + Data Hub list), never silently skipped.

## Architecture Decisions
- Swap detection is per file (parser) / per upload (repair) by a vote: a company name has spaces, a scrip code doesn't. Per row would miss one-word company names. (D-54)
- The repair keeps every `broker_instruments.id` (position snapshots reference it with RESTRICT) but renames the synthetic `broker_instrument_id` to `<TICKER>_INR`, what a fixed upload looks up, so later uploads reuse the row. If that id already exists (a fixed upload ran first), the old id is kept and reported.
- A 0-symbol run on an exchange with held positions is `partial` in `market_data_runs` (still satisfies the scheduler's done-check, #137) and `no_new_data` in `job_runs` (Data Hub amber). No new status value. (D-54)
- `market_symbol_map.yahoo_symbol_override` already existed; a symbol that already ends in a Yahoo market suffix (`.NS`, `.BO`, `.SI`, `.HK`) is now quoted as is (it used to become `<CODE>.BO.NS`), in the service, the yfinance provider and the dividends page. `make market-symbol-override` sets it per asset.
- The holdings file states no date (only a financial year); the Ingest page already pre-fills the date from the file name (D-34), so the parser doesn't guess one.

## Acceptance Criteria
- [x] Parser detects the swapped layout and swaps; synthetic fixture reproduces Sharekhan's layout.
- [x] `make sharekhan-instrument-repair` (dry run; `APPLY=1` writes): fixes symbol/name, links/creates INR assets (home_country IN), marks History dirty from the earliest affected snapshot; idempotent.
- [x] Per-asset Yahoo symbol override (`make market-symbol-override`), `.BO` honoured end to end.
- [x] Held positions that can't be priced are listed (Data Hub) with the reason; an exchange run with held positions and 0 symbols is a warning, without reintroducing all-day retries.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_nse_sharekhan_pricing.py tests/test_parsers.py`
- `cd web && npx vitest run src/__tests__/OperationsOverview.test.tsx`
- On a copy of the real data: `make sharekhan-instrument-repair`, then `APPLY=1`, then refresh prices and check NSE run counts, the Data Hub unpriced list, net worth / Stocks totals and History.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr-open`
- Workflow Status: `running`
- Provider/Model: `claude-code/claude-opus-5-5`
- Last Updated: `2026-11-06`

## Deterministic Gate Results (Codex Mutable)
- See the PR description for command-level results.

## Extra Files Changed (Codex Mutable)
- `api/app/routers/dividends.py` — reason: its Yahoo symbol builder had the same `.BO` → `.BO.NS` bug.
- `api/app/market_data/providers.py` — reason: the yfinance provider re-normalizes symbols and appended `.NS` to `.BO`.

## Human Action Summary (Codex Mutable)
- Next expected action: test on a test instance, then on the real stack after deploy:
  `make sharekhan-instrument-repair` (dry run), `make sharekhan-instrument-repair APPLY=1`, then set the one `.BO`-only holding with `make market-symbol-override SYMBOL=<CODE> CURRENCY=INR EXCHANGE=NSE YAHOO=<CODE>.BO APPLY=1`, then refresh prices.
- Open questions:
  - One holding has no Yahoo data on `.NS` or `.BO` (possibly renamed/delisted): it shows in the Data Hub as unpriced (no quote) until its ticker is corrected.
