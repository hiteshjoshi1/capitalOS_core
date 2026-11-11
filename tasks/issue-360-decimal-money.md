# Issue #360: Money as Decimal in canonical reads and valuation

From #353 T3 (#130 §2.11). Decision: D-106.

## What changed
- `app/valuation/money.py`: `D()` (any number → Decimal, a float by its shortest repr), `dsum()`, `floats()` (nested Decimal → float) and `@float_edge`.
- `app/portfolio/canonical_reads.py`: the 17 `DOUBLE PRECISION` casts are `NUMERIC`; every reader returns its money, quantity and rate columns as Decimal (positions, NAV, balances, card statements). `avg_cost` is computed in Python (a Decimal division).
- `app/portfolio/position_pricing.py`, `app/valuation/{prices,state,facts,holdings,exposure,bridge,move_causes,history,pages}.py`: Decimal arithmetic; FX rates and quotes through `D()`; thresholds are Decimal constants.
- Edges: `@float_edge` on the `pages` functions and `bridge.month_bridge`; `floats()` in the dividends router, `float()` in spending's cash bridge; History rollups bound exactly on Postgres (`_db_money`).
- Card ledger / dues / bank payments stay in floats (see D-106).

## Tests
- `tests/test_decimal_money.py`: `D`/`floats`; readers return Decimal; per scenario and base, net worth = its parts and the bridge adds up **exactly** before the edge; the API's floats equal those numbers.
- `tests/test_valuation_invariants.py`: one figure on two pages compared exactly (`EXACT`); sums the test makes of response floats at `SUM_TOL` (1e-6, not a cent).
- Tests that call valuation internals compare `float(...)` with `pytest.approx`.
- Golden files unchanged.

## Parity on real data
The 11 Nov 10:15 backup restored into the worktree stack; 37 responses for Hitesh (bootstrap, summary, bridge, holdings, cash, exposure, risk, spending, cards, crypto, dividends, income, timeline, inbox; Nov and Oct) with main's code and with this branch: no difference over 0.005; the largest was 3.8e-10.
