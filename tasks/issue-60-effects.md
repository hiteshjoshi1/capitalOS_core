# Issue 60: Refactor effects flagged by react-hooks/set-state-in-effect

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/60

## Objective
- `react-hooks/set-state-in-effect` (new in eslint-plugin-react-hooks 7.1, #49) is an error again, not a "warn" override, and `npx eslint .` is clean.
- The six effects that tripped it behave the same: same requests, same loading/error/rendered states.

## Architecture Decisions
- State that only follows an input is adjusted while rendering by tracking the previous input ("adjusting state when a prop changes", react.dev/learn/you-might-not-need-an-effect), not in an effect:
  - `AddAccount.tsx`: country prefill when `selectedPlatform` changes (tracked by identity, so a refreshed platforms list still re-applies it, as before).
  - `CryptoWallets.tsx`: Ledger adapter ticks "Using Ledger / hardware wallet" when `wallet` changes; the initial value comes from a lazy `useState` initializer, which covers the mount run the effect used to do.
  - `WealthHistory.tsx`: a range/currency change resets `selectedMonth` and puts timeline, dividends and cash flow back to `loading` in one place.
- Data fetching stays in effects, but state is only set after the `await`, with an `ignore`/`cancelled` flag:
  - `WealthHistory.tsx` timeline and dividends + cash-flow effects: fetch inline (no `useCallback` fetchers that set "loading" first); load states start as `"loading"` (the unused `"idle"` state is gone). The backfill handler sets `loading` and bumps a `timelineReload` counter that the timeline effect depends on, instead of calling the fetcher.
  - `CryptoWallets.tsx` mount fetch: wallets and allowlist fetched inline; `loadAllowlist` (only used there) removed, `loadWallets` kept for the verify handlers.
- Kept on purpose: dividends and cash flow share one effect, so a range change still refetches cash flow (as before), though that card doesn't depend on range.
- Intended differences: the first frame after a range/currency change now already shows loading (before, one frame showed the old data and selection); a superseded response is dropped instead of overwriting a newer one; `backfilling` clears when the backfill returns, not after the refetch (not visible: the loading card hides both buttons).

## Acceptance Criteria
- [x] No `react-hooks/set-state-in-effect` override in `web/eslint.config.js`; the rule is at severity 2 (`--print-config`).
- [x] `npx eslint .`: 0 problems (was 6 warnings).
- [x] `npx tsc -b --pretty false` clean; `npx vitest run` 275 passed; `npm run build` succeeds.
- [x] No eslint-disable comments, no setTimeout/queueMicrotask wrappers; no test changes.

## How To Test
- `cd web && npx eslint . && npx tsc -b --pretty false && npx vitest run && npm run build`.

<!-- IMMUTABLE_PLAN_END -->
