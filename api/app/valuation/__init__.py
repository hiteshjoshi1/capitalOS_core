"""The valuation service (#143): what the dashboard, History, crypto and
dividends pages compute from the canonical facts, split out of
``app.routers.dashboard``.

Modules, from the bottom up (each imports only the ones above it):

- ``clock``: the one clock and anchor rule (SNAPSHOT_DAY, the app timezone).
- ``fx``: rates for valuation (re-exports ``app.fx``; the patch point in tests).
- ``prices``: a holding's price under D-21/D-42 (``app.portfolio.position_pricing``).
- ``state``: account state at an anchor: the one cash scope, card accounts,
  wallets, snapshot coverage.
- ``facts``: net worth, liabilities, cash, cash flow.
- ``holdings``: holdings, movers, stock exposure.
- ``exposure``: platform allocation and geography.
- ``history``: the History rollups (D-29) and month-on-month changes.
- ``pages``: one function per dashboard response, composing the above.
"""
