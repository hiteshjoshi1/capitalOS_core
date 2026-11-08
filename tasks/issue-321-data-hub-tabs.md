# Issue 321: Data Hub tabs and Settings → Admin (#309 plan, step 7 of 7; folds in #294)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/321 · builds on #318 (PR #335).

## What
- Data Hub tabs: **Inbox · Accounts & sources · Imports** (were Overview, Accounts & sources, Import
  Statements, Add Accounts, Add Platforms, Add Crypto Wallets, Refresh Market Data). Add Account and
  Market data count as the Accounts & sources tab (they open from its "+ Add" and row actions);
  /crypto (add a wallet) stays in Data Hub as a hidden tab. Ingest's title is "Imports".
- **Settings → Admin** (`/settings/admin`, admins only; Settings shows an "Admin" card to admins):
  background jobs (#156 job status), the platform directory (was the Add Platforms page,
  now `components/PlatformDirectory.tsx`), and the token allowlist (moved from the wallets page,
  `components/TokenAllowlistCard.tsx`). A non-admin is sent back to Settings.
- Old routes: `/platforms` → `/settings/admin`; `/accounts/new`, `/crypto`, `/market-data`, `/ingest`
  keep working. Frontend only.

## Tests
- `dataHubTabs.test.ts` (tabs, which tab each route belongs to, /crypto vs /crypto/holdings, redirect),
  `AdminSettings.test.tsx` (admin sees jobs/platforms/allowlist; non-admin redirected, no link;
  allowlist add + fallback labels moved from CryptoWallets), `PlatformDirectory.test.tsx` (renamed).
- E2E: home/operations specs updated for the tabs and the moved platform page; the mobile overflow
  spec covers /operations/sources.

<!-- IMMUTABLE_PLAN_END -->
