# Issue 315: Data Hub quick fixes (#309 plan, step 1 of 7)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/315

## Changes
- Wallets: removed the leftover "Same sign-and-verify flow as today — just restyled." text.
- Upload list: each import names its account ("Citi · <account name> · date"), not "Account 11".
- "Needs mapping" → **"Unknown format"** with a **Fix format** button. NEEDS_MAPPING means no parser
  knows the file's format (registering it is the fix), not transaction category mapping, so the
  review's "link to Map Transactions" was corrected. `/ingest?job=<id>` opens that upload's report,
  so Data Hub's Inbox (#316) can link straight to it.
- Market data: exchanges with nothing held are left out; a reason line only on rows that aren't fresh.
- Accounts: "CLOSE…" (11px uppercase link) → a normal small "Close account…" button.

## Tests
- Ingest: account names, "Unknown format" + "Fix format", `?job=` opens the report.
- MarketData: exchange with no symbols hidden; fresh rows have no reason line.
- Frontend: 73 files / 619 tests pass; typecheck and ESLint clean.

<!-- IMMUTABLE_PLAN_END -->
