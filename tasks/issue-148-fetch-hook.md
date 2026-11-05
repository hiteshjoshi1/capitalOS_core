# Issue 148: Frontend fetch hook: cache, dedupe, abort, keep previous data; fix month/currency races

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/148

## Objective
- One small in-house data hook (`useApiResource`) instead of ad hoc `useEffect` fetching: keyed cache, in-flight dedupe, abort, keep previous data.
- A slow earlier response can never render under a later month or currency (#130 finding 7.2).
- Month/currency changes no longer blank the page to "Loading…" (6.4); Cash Flow tabs no longer remount and refetch (6.5).

## Architecture Decisions
- In-house hook, no new dependency (TanStack Query would need approval). `web/src/lib/useApiResource.ts`, built on `useSyncExternalStore` with a module-level store.
- Data is stored per key, so a reply can only be shown under the key it was fetched for. That is the race fix; abort is an optimisation on top.
- Stale-while-revalidate with `staleTimeMs = 0` by default: cached data renders at once and is always refetched on mount, so an upload elsewhere is never hidden behind a cache.
- Abort without touching ~40 API wrappers: `withAbortSignal` (in `lib/abortScope.ts`, outside `api.ts` so `vi.mock("../lib/api")` keeps it) sets an ambient signal that `req()` reads synchronously. An aborted fetch rethrows `AbortError` instead of "Unable to reach API".
- The last reader of a key leaving aborts its request, deferred by one tick so StrictMode's double mount keeps it.
- Amounts are labelled with the currency the shown data is in (`data.base_currency`), so a placeholder from the previous currency keeps its own prefix.
- The cache is cleared on login, signup, logout and auth failure (no cross-user data).
- Map Transactions opts out of keep-previous-data: it is a work list, and last month's rows under this month's heading would invite mistakes.
- `AppShell`'s `key={location.pathname}` is removed; different routes still mount fresh because they are different elements.

## Acceptance Criteria
- [x] Race tests: a slow earlier response never renders under a later month (Cash, Crypto, Stocks, Dividends, Liabilities, Map Transactions) or currency (Wealth Overview, Cash), and the superseded request is aborted.
- [x] Previous data stays on screen (dimmed, `aria-busy`, "Updating…" announced) while the next key loads.
- [x] Cash Flow tab switches do not refetch (AppShell test).
- [x] `/alerts/notifications` is one request for the sidebar and the Alerts page; Liabilities fetches `/accounts` once, not per filter change.

## How To Test
- `cd web && npx vitest run src/__tests__/useApiResource.test.tsx src/__tests__/api.abort.test.ts`
- `cd web && npx vitest run` (race tests are in each page's test file, under "... races").
- `make verify`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `npx eslint .`, `make verify`
- `typecheck`: pass — `npx tsc -b --pretty false`
- `tests`: pass — `npx vitest run` (51 files, 341 tests); `make verify`
- `e2e`: skip
- `api-smoke`: skip (no backend change)
- `policy-checks`: pass — `make verify`

## Extra Files Changed (Codex Mutable)
- `web/src/context/AuthContext.tsx` — reason: clear the API cache on sign-in/out so one user's cached data never shows for another.
- `web/src/components/Sidebar.tsx`, `web/src/routes/Alerts.tsx` — reason: dedupe `/alerts/notifications` (finding 7.1).
- `web/src/routes/WealthRisk.tsx` — reason: shares the dashboard-summary resource with Wealth Overview.
