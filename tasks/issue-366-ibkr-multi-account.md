# Issue #366: IBKR Flex, refuse a file with more than one account

From #353 T8 (#130 §3.5). Low priority; okayed by Hitesh 2026-11-10.

## Problem
`parse_flex_statement` took the account from the first statement but collected rows from all of them, so a
Flex query covering two accounts would be merged into one broker account.

## Change
- `_reject_multiple_accounts` (api/app/portfolio/ibkr_flex.py): every element's `accountId` (statements,
  AccountInformation, rows) is collected; `-` and empty (IBKR summary rows) are ignored. More than one →
  `IbkrFlexImportError("multiple_accounts", "This Flex file has 2 accounts (U111…, U222…); import each
  account's query separately")`. Account numbers are masked to their first 4 characters.
- Raised inside parsing, so the run fails like any parse error: raw XML and the failed run row stay (as for
  every unreadable statement), no broker account, NAV, positions or cash are written.

## Tests
`api/tests/test_ibkr_flex_phase1.py`: two statements, a foreign row inside one statement, summary rows with
`-`/empty ignored, and the import run failing with no facts. All 17 real Flex files on the real-data stack
still parse (checked read-only).
