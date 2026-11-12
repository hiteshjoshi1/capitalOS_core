# Issue #418: Stocks holdings table fits at 1440px with the Dividends column

## Problem
At 1440px the holdings table was 1,420px wide in a 1,084px card (with #396's Dividends column), so Dividends needed a sideways scroll.

## Change
- Quote freshness is off by default (still in the Columns picker). With it off, a stale price is still flagged under the price in the Current Price cell.
- New column-choice storage key (`…visibleColumns.v2`), so a saved "all on" choice from before doesn't keep the table too wide.
- Tighter cells: 10px side padding (was 16px), asset cell min-width 160px (was 220px), header letter-spacing 0.08em (was 0.16em).
- Δ, P&L, % NW and Dividends stay on by default; phone cards unchanged.

## Verification
- New e2e `web/tests/e2e/desktop-stock-table.spec.ts`: at 1440px no sideways scroll, and Δ / P&L / % NW / Dividends headers inside the card (natural table width 1,037px in 1,084px).
- `make verify`; `make e2e-smoke` with the desktop holdings baseline updated (looked at).
