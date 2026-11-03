# Issue 145: Load the Solana wallet stack only on the wallet page; lazy-load routes

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/145

## Objective
- The Solana wallet stack (wallet-adapter providers, Phantom adapter, modal CSS, @solana/web3.js) loads only when the Crypto Wallets page (`/crypto`) is opened.
- Every route except the landing page and the auth pages is its own chunk, so first load is smaller.

## Architecture Decisions
- `web/src/wallet/SolanaWalletShell.tsx` holds the Connection/Wallet/WalletModal providers, the Phantom adapter (module level, one instance per session) and the wallet CSS. `routes/CryptoWalletsPage.tsx` wraps `CryptoWallets` in it, and only that page module is lazily imported, so the whole stack lands in the `CryptoWalletsPage` chunk.
- Eager: `/` (redirect), `/wealth` (landing), `/login`, `/signup`, AppShell, RequireAuth. All other routes are `React.lazy` in `routes/lazyRoutes.ts` (a separate module so `main.tsx` passes the react-refresh lint rule).
- `Suspense` sits inside AppShell's content area around `<Outlet />`, with the pages' existing `<div className="card">Loading…</div>` look (`components/RouteFallback.tsx`), so sidebar and top bar stay up while a chunk loads.
- Behaviour change (intended): with a remembered Phantom choice, autoConnect used to fire on every page (the providers wrapped the whole app). It now fires when the wallet page mounts, which is the only page that uses the connection. On that page it behaves as before (checked in a browser with a synthetic Phantom provider).
- No Vite config change: web3.js 1.x ships its own Buffer polyfill in its browser build; there was no global polyfill before and the lazy chunk works the same (Sign & verify path exercised in the production build).

## Acceptance Criteria
- [x] Initial JS chunk no longer contains wallet-adapter/web3 code (build output in the PR).
- [x] Wallet page still connects Phantom and verifies; all route tests pass.

## How To Test
- `cd web && npx vite build`: entry `index-*.js` ~309 KB / ~95 KB gzip (was 848 / 240); `grep -c getLatestBlockhash dist/assets/index-*.js` is 0; `CryptoWalletsPage-*.js` holds the wallet stack.
- `npx vitest run src/__tests__/WalletLazyLoad.test.tsx src/__tests__/AppShell.test.tsx src/__tests__/MainEntry.test.tsx`.
- In a worktree stack, log in as demo, open `/wealth` (no `CryptoWalletsPage` request), then `/crypto`, choose Solana: the purple wallet button renders.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `make verify`: pass (lint, typecheck, backend 472 passed, frontend 43 files / 287 tests passed).
- `WalletLazyLoad.test.tsx` fails if `main.tsx` imports the wallet shell eagerly (checked by adding the import back temporarily).
- Browser (Playwright, isolated stack, production build via `vite preview` and the dev server): no console errors other than the pre-login 401 session probe; wallet chunk requested only on `/crypto`; client-side navigation to `/cash-flow`, `/liabilities`, `/crypto` renders each page in the shell; autoConnect fires on `/crypto` with a synthetic Phantom provider; Sign & verify calls init and verify (backend rejects the synthetic signature with 400, as it should).
