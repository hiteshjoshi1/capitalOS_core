# Issue 150: Shared base-currency state and one formatting library

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/150

Based on #148's branch (PR #195); its diff includes #148 until that merges.

## Objective
- One base currency for the whole app: chosen once, the same on every page, and kept across navigation and reloads (#130 finding 7.3).
- One formatting library with a fixed locale: money, compact, signed delta, percent, month, date (7.4). Plus one chart palette.
- The #131 UX formatting findings that match: `S$ 53,512.9`, `$10` on an S$ page, raw ISO timestamps, mismatched delta signs, "down" shown blue in one place and red in another, and raw enum labels.

## Architecture Decisions
- `web/src/lib/format.ts` is the only place that formats numbers and dates.
  - Fixed locale `en-SG`. Month names are spelled out in code because ICU versions disagree ("Sep" vs "Sept").
  - Money is `<prefix> <amount>` with one space: `S$` for SGD, the ISO code otherwise. The sign goes before the prefix (`-S$ 1,234`, `+S$ 1,234`).
  - Whole units by default. Fixed decimals when asked (prices, transactions, Map Transactions). Compact only for chart labels and donut totals.
  - A missing value is `—`, never `0` and never `+—`.
- `web/src/lib/chartColors.ts`: one palette and one `donutGradient()` replace 7 copies. Wealth Overview's oklch donut now uses the shared palette.
- `useBaseCurrency()` (`context/CurrencyContext.tsx`) is a small external store (`useSyncExternalStore`) persisted in localStorage, with a `storage` listener for other tabs. The header picker and every page share one value, even when a component is rendered alone in a test, so no provider is needed. `BaseCurrencyPicker` is the one control. `CURRENCY_OPTIONS` is the one list.
- **Not a server preference yet.** Saving it with theme/accent needs a `base_currency` column on `user_preferences`, i.e. a migration. None was assigned to this task, so it is proposed, not done.
- Down is one colour: `--trend-negative` now aliases `--bad` in both themes.
- Crypto holding deltas compute their % from the same base-currency amounts as the money delta, so the two signs can't disagree.
- Map Transactions labels each amount with the transaction's own currency (the API doesn't convert queue rows). Before, every amount was labelled with the selected base currency.

## Acceptance Criteria
- [x] Currency persists across pages and reloads (`CurrencyContext.test.tsx`, `CashOverview` shared-currency test).
- [x] Deltas format the same everywhere (`format.test.ts`, and the `formatGuard.test.ts` static guard against page-local formatters).

## How To Test
- `cd web && npx vitest run src/__tests__/format.test.ts src/__tests__/chartColors.test.ts src/__tests__/CurrencyContext.test.tsx src/__tests__/formatGuard.test.ts`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `npx eslint .`
- `typecheck`: pass — `npx tsc -b --pretty false`
- `tests`: pass — `npx vitest run` (53 files, 377 tests); `make verify`
- `e2e`: skip
- `api-smoke`: skip (no backend change)

## Human Action Summary (Codex Mutable)
- Decide whether the base currency should also be a server preference (needs a migration number for `user_preferences.base_currency`).
