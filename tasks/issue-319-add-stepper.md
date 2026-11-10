# Issue 319: Data Hub 5/7: "+ Add" stepper for accounts, wallets and statements

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/319

## Objective
- One flow to add an account (bank, card, brokerage, funds, exchange, loan) or a self-custody wallet, and its first data.
- Replace the Add Account form and the Add Crypto Wallets page; no disabled-button-with-no-hint.

## Architecture Decisions
- D-88: `/add` stepper (what → where → details → first data); `/accounts/new` and `/crypto` redirect to it.
- Reuses the existing endpoints (`/platforms`, `/accounts`, `/ingest/upload`, `/crypto/wallets/*`); no API change.
- The wallet signing form moved to `web/src/wallet/WalletConnectForm.tsx`, loaded lazily inside
  `SolanaWalletShell` (`WalletConnectStep`), so the Solana stack still loads only when needed (#145).

## Acceptance Criteria
- [x] A new card account with its first upload takes one flow.
- [x] Each step says what's missing instead of a disabled button.
- [x] Keyboard and screen-reader labels: radio groups, labelled inputs with described-by hints, `aria-current="step"`, focus moves to each step's heading.
- [x] Tests cover each type (account kinds, wallet, inline platform, refused upload, phone wallet notice).

## How To Test
- `cd web && npx vitest run src/__tests__/AddFlow.test.tsx src/__tests__/addFlow.lib.test.ts src/__tests__/WalletConnectForm.test.tsx src/__tests__/WalletLazyLoad.test.tsx`
- `npx playwright test tests/e2e/operations.spec.ts tests/e2e/mobile-no-overflow.spec.ts`
- Data Hub → Accounts & sources → + Add → Account or card: pick Credit card → a bank → Create account → upload a statement.

<!-- IMMUTABLE_PLAN_END -->

## Extra Files Changed
- `web/src/lib/monthBridge.ts` — reason: "Newly tracked" linked to `/crypto/wallets`, which isn't a page; it now opens Accounts & sources.
- `web/src/routes/AccountsSources.tsx` — reason: the row menu's "Wallet settings" opened the old add-wallet page (no settings there); removed. "+ Add" items point at the stepper.
