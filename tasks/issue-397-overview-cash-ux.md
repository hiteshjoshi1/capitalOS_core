# Issue #397: Overview & Cash UX (U1, U2, U12, U13, U14 from #354)

## What changed
- **U1 (Overview):** the "Signals" section is titled "Cash flow, liabilities and largest positions" (it had no risk content).
- **U2 (Overview):** the "Where the money sits" donut has two more views, **By currency** (Risk summary's currency exposure, gross: stocks by trading currency, cash by held currency, stablecoins as USD, other crypto "not a currency") and **By country** (/summary's geography). Both add up to the same gross assets. Two-by-two buttons on a phone.
- **U12 (Cash):** the currency mix lists the currencies actually held (now or at the compare point), no zero rows, no fixed buckets.
- **U13 (Cash):** "Cash by account": balance, change vs last month, newest data date, and an **Overdue** pill from Data Hub's source freshness (live month). Rows add up to the headline.
- **U14 (Cash):** "Foreign cash revalued": what exchange rates alone did to the foreign-currency cash held at the compare point, per currency. Same figure as the bridge's FX part for foreign-currency cash (shared function).

## API (additive)
- `GET /dashboard/cash-deposits`: `accounts[]`, `fx_revaluation`; `currency_breakdown` now lists held currencies only.

## Checks
- Backend: new `test_dashboard_cash_deposits_accounts_currencies_and_fx_revaluation` (incl. FX = bridge cash FX part). Golden files regenerated (new fields; zero currency rows gone).
- Web: CashOverview (2 new), WealthOverview (1 new). `make verify` green. `make e2e-smoke` 45/45; baselines updated for desktop/phone Cash and phone Overview (looked at).
- Real data (backup 11 Nov 13:00 restored into the worktree stack): accounts sum = Cash total (S$ 457,959.74); FX revaluation −S$ 8.3786 = bridge cash FX part; currency and country donuts both S$ 1,094,335 gross.
