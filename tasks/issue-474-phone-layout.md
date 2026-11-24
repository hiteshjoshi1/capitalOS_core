# Issue 474: Phone layout: Stocks positions jump + search + compact rows, crypto Hide in a menu, Cash Flow folds

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/474

## Objective
- V4: on a phone the Stocks page was ~13,500 px tall and the positions came after five sections. Get to them in one
  tap, find one by name or ticker, and see one line per holding (tap for the details).
- V13: the crypto "Hide" (spam) button sat on almost every token row, real coins included, easy to tap by mistake.
- V21: Cash Flow Overview stacked four trend blocks on a phone.

## Architecture Decisions
- Stocks: a "Positions (N) ↓" jump link under the hero, on a phone only (≤900px, the page's existing table/card
  switch). The positions stay where they are; the jump link changes less than reordering the page. It scrolls to the
  section and moves focus to its heading.
- Stocks: a search box (name or ticker, case-insensitive) in the positions header, on desktop and phone. It filters
  the table and the phone list, resets paging, and the count reads "N of M positions match". Sorting and columns on
  desktop are unchanged.
- Stocks phone rows: a `<button aria-expanded aria-controls>` per holding with ticker, name (ellipsis), value and one
  figure: the change since the compare month-end when sorted by change, else P&L %. As in #251, a purchase, sale or
  new holding isn't coloured. A stale live price shows a "stale" mark on the closed row (#418: a stale price must
  still show). Opening it shows the previous card (exchange, platform · geography, freshness, value / % NW, P&L, the
  change split, dividends, price date).
- Crypto: the action moved into a ⋯ menu (`<details>`, as on Accounts & sources: Enter/Space opens it, Escape or a tap
  outside closes it). Shown when the token is unknown by #342's rule (`unknown_token`: never priced and not
  allowlisted), or when it is hidden or has the user's own override, so an earlier choice can be undone. Priced
  coins (JUP, LINK...) have no menu. Trade-off: a priced token can no longer be hidden from its row.
- Cash Flow: a `FoldSection` component: a plain `<section>` on a wide screen, a `<details>` whose `<summary>` is the
  section heading on a phone (`NARROW_SHELL_QUERY`, the shell's phone layout). Six-month net and the twelve-month
  savings rate come first and start open; "Vs. last month" and the cash bridge start closed.

## Acceptance Criteria
- [x] Stocks phone: Positions jump link near the top; search by name/ticker; one-line rows that open for details.
- [x] Stocks desktop: sorting and columns unchanged (search box added to the header).
- [x] Crypto: Hide/Not spam/Show only in a ⋯ menu, only on unknown (or user-overridden) tokens; keyboard operable.
- [x] Cash Flow Overview phone: the four blocks fold, net and savings rate first and open.

## How To Test
- `cd web && npx vitest run src/__tests__/StockHoldings.test.tsx src/__tests__/CryptoHoldings.test.tsx src/__tests__/CashFlowDetail.test.tsx`
- `make verify`
- `make e2e-smoke` (baselines updated with `make e2e-smoke-update`: phone/desktop holdings, phone cash-flow).
- In the app at 375px: Stocks → tap "Positions", search "app", tap a row; Crypto → an unknown token has ⋯ → Hide;
  Cash Flow → Overview shows four headings, the first two open.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `running`
- Provider/Model: `anthropic/claude-opus-5-5`
- Last Updated: `2026-11-24`

## Deterministic Gate Results (Codex Mutable)
- `lint`: see PR CI
- `typecheck`: see PR CI
- `tests`: vitest (Stocks, Crypto, Cash Flow) pass; `make verify`
- `e2e`: `make e2e-smoke-update`, changed PNGs reviewed

## Extra Files Changed (Codex Mutable)
- `web/src/components/CashFlowYearOverYear.tsx` — reason: the savings-rate block lives there; it takes `fold`.
- `web/src/components/FoldSection.tsx`, `.css` — reason: the shared phone fold.
