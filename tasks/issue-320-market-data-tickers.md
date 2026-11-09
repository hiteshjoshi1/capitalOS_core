# Issue 320: Market data with actions (ticker-only scope)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/320

## Objective
- An Indian holding Yahoo lists only on BSE gets priced without help; anything still unpriced
  can be fixed from the Market data page by setting its Yahoo ticker. No manual prices (Hitesh,
  2026-11-09).

## Architecture Decisions (D-86)
- `_try_bse_fallback` after the provider chain: NSE rows still unpriced, without an override,
  are tried as `<CODE>.BO` (one yfinance batch); a hit stores the price and saves `<CODE>.BO` as
  the Yahoo override; the run item (provider `yfinance_bse`) notes "auto: …". `MARKET_DATA_BSE_FALLBACK=0` off.
- `GET /market-data/unpriced` (the caller's unpriced holdings + suggested tickers + `can_fix`),
  `POST /market-data/ticker-test`, `POST /market-data/ticker` (admin; tests, saves, stores the quote),
  `POST /market-data/refresh-now?exchange=X` (one exchange).
- Page: action bar with Refresh all (admin), "Needs a fix" list (Test → Save ticker, suggestions
  `<CODE>.NS` / `<CODE>.BO`), Refresh per exchange (admin). Non-admins see the list, no actions.
- Data Hub "Fix N" (Accounts & sources) and the Inbox unpriced item ("Fix ticker") link to
  `/market-data#needs-fix`.

## Real data (read-only)
- 37 NSE symbols: 34 priced via .NS; NSE and NSDL are BSE-only on Yahoo and would auto-resolve
  (both already have manual .BO overrides, which the fallback never replaces); GUJGASLTD has
  neither (inactive since the demerger).

## Tests
- `api/tests/test_market_data_tickers.py` (10): NS empty → BO stored + override + note, next
  refresh asks BO; neither → stays unpriced; set override never replaced; env off; unknown exchange
  422; ticker-test admin/403; set-ticker saves/prices, 422 when no quote, 403; map row created;
  unpriced list suggestions + can_fix.
- `web/src/__tests__/MarketData.test.tsx` (+4): test → save, failed test keeps Save disabled,
  refresh one/all, non-admin view.

<!-- IMMUTABLE_PLAN_END -->
