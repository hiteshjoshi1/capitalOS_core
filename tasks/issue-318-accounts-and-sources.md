# Issue 318: Data Hub → Accounts & sources (#309 plan, step 4 of 7)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/318

## What
- New page `/operations/sources` (Data Hub tab "Accounts & sources"): one row per account, wallet,
  quote feed and FX source (the #252 freshness rows, joined to accounts and the Data Hub's unpriced
  holdings). Each row: name, type · platform · currency, last data, status pill + next due, ONE primary
  action, and a ⋯ menu.
- Primary action (`lib/sources.ts` `primaryAction`): statement accounts → **Upload** (prefilled, #278);
  IBKR Flex → **Refresh** (import now); wallets → **Refresh**; quote feeds → **Fix N** (unpriced on that
  exchange → Market data) else **Refresh** (admin); FX → **Fetch past** (admin, #290). Non-admins see
  "Admin refreshes this" on shared feeds. Closed accounts have no action.
- ⋯ menu: expected cadence (the #252 editor, moved here), Upload a statement, Close / Reopen account
  (#207 control, moved to `components/AccountCloseControl.tsx`), Wallet settings, Market data details.
- Filters (All · Banks · Brokers · Cards · Wallets · Feeds · Other, shown only when present) and search.
  What needs you sorts first (overdue, never loaded, unpriced), closed accounts last. "+ Add ▾"
  (account, wallet, statement upload) in the header.
- Replaced: the Inbox's "Every source and its schedule" table (now a link), Add Account's "Linked
  accounts" list and the wallets page's "Connected wallets" list (both now point here). Frontend only;
  no API change.

## Measured (Playwright, demo data)
- 1440×900: no overflow, first action at 378px, 17 rows. 375×812: no overflow, first action at 474px.
- The ⋯ menu was drawn under the next row; fixed (the row with an open menu is raised).

## Tests
- `AccountsSources.test.tsx`: ordering + actions, IBKR/wallet refresh, non-admin feed hint, filter +
  search, close from ⋯, carried-forward note + cadence editor, primaryAction/buildSourceRows units.
- AddAccount / CryptoWallets tests updated for the moved lists.

<!-- IMMUTABLE_PLAN_END -->
