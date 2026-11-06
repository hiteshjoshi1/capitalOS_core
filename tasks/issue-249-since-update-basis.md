# Issue 249: Overview "Since last update": holdings from an older statement are compared at that statement's prices

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/249

## Objective
- "Since last update" on Overview (`/dashboard/net-worth-since-update`) is market movement since
  the compare date for every holding, whichever broker's statement is older (owner: option **a**).
- A holding that can't be priced that way (no usable quote by the compare date) says so and is
  counted, instead of silently showing months of moves as "since yesterday".

## Architecture Decisions
- D-65 (docs/decisions.md). The compare date is unchanged: the newest statement date at or before
  yesterday (`compare_as_of`, the label). The compare side used to be valued at "yesterday"
  (`now - 1 day`); it is now valued **at the compare date** (`clock._compare_date_anchor_ts`: that
  date at yesterday's time of day, so it is never mistaken for a 00:00Z month-end anchor):
  - stocks and funds: holdings as of that date, each at its last quote on or before it (stored
    `prices`, D-21's rule, the same `price_position` the live headline uses: a quote older than the
    holding's own statement, or over 2x off, leaves the statement price);
  - FX at that date's rate; crypto wallets at their snapshot on or before it (snapshots carry
    their own prices; there is no other crypto price history); card balances as of it.
- New fields only (nothing removed or renamed):
  - `basis: "quoted_at_compare_date"`;
  - `compare_basis: {price_date, holdings, quoted, statement_priced, older_statement_priced}`:
    per asset on the compare side, priced at a quote or at its statement, and how many of those
    are statements older than the compare date while the holding is quote-priced now (its move
    then starts at that statement; a holding the price job never quotes is at its statement on
    both sides, moves only with FX, and isn't counted);
  - per mover (`SinceUpdateTopMover`, a subclass used only by this endpoint so /summary's movers
    keep their shape): `compare_price_basis` (`quote` | `statement` | null for crypto / not held),
    `compare_price_as_of`, `compare_price_fallback` (the same rule as `older_statement_priced`).
- Overview: the "SINCE LAST UPDATE" label's tooltip states the basis; when some holdings were
  compared with an older statement price the hero says "N holdings vs an older statement price";
  the Today tab ends with "Moves since <date>, each holding at its last quote on or before that
  date." and marks fallback rows with `*` (and a footnote). Dates via `lib/format.ts`.

## What changes for whom
- **Newest statement from yesterday (daily IBKR Flex) and quotes for every holding**: no change in
  the figures. The compare date is yesterday, as the old compare point was. Holdings from an
  older statement (a Sharekhan file from weeks ago) were already priced at quotes up to yesterday,
  and still are.
- **Newest statement older than yesterday** (no Flex report for a few days, a weekend, or uploads
  only): the compare side moves back from yesterday to that statement date. The change now
  includes everything between that date and yesterday, which the label ("since <date>") already
  claimed: quotes, crypto snapshots, FX and card spending after that date. Before, it was missing.
- **A holding with no quote on or before the compare date, but a quote today** (most likely the
  real-data case in the issue: Sharekhan's NSE holdings only got quotes once #222 merged on 6 Nov,
  so none had one dated on or before the compare date; to confirm on the test instance with
  `compare_basis`): it is still compared with its own statement price, because
  there is no earlier market price. It is now flagged (`compare_price_fallback`, `*` on Today) and
  counted (`compare_basis.older_statement_priced`, the hero note). It goes away by itself once a
  quote on or before the compare date exists, the next day for a holding the price job now quotes
  daily. Leaving such holdings out (option b's approach) was rejected in D-65.

## Golden changes (api/tests/golden/valuation)
Only `/dashboard/net-worth-since-update` changes. Every scenario gains `basis` and `compare_basis`,
and every mover gains the three `compare_price_*` fields. Rates: March SGD per USD 1.455/1.085 =
1.34101, per HKD 1.455/8.47 = 0.17178, per INR 1.455/91.5 = 0.015902.
- **first** (1 Apr 06:00 SGT): compare date 31 Mar = yesterday, so the figures don't change.
  `compare_basis`: 4 holdings, all quoted (31 Mar quotes are as recent as IBKR's 31 Mar report).
- **mid** (18 Mar 10:00 SGT; label "16 Mar"): the compare side was valued at 17 Mar, the same data
  as now, so the change was 0. It is now valued at 16 Mar:
  - stocks compare 13,361.98 -> 13,095.11; change 0 -> +266.88. On 16 Mar no quote is as recent as
    the statements (the newest are 27 Feb), so IBKR's holdings are at IBKR's 16 Mar prices and
    Sharekhan's at its 15 Mar prices, instead of 17 Mar's quotes. AAPL 25 x (205 - 200) USD =
    +167.63; 0700 100 x (315 - 310) HKD = +85.89; INFY 20 x (1650 - 1620) INR = +9.54; RELIANCE
    12 x (2900 - 2880) INR = +3.82. `compare_basis`: 4 holdings at a statement price, 2 of them
    (Sharekhan, 15 Mar) older than 16 Mar, flagged.
  - crypto compare 21,188.02 -> 19,645.85; change 0 -> +1,542.17. The main wallet's snapshot on or
    before 16 Mar is 28 Feb's (2 ETH at 2,800, 2,000 USDC) instead of 17 Mar's (2.5 ETH at 3,100,
    1,000 USDC): ETH +2,150 USD = +2,883.18, USDC -1,000 USD = -1,341.01.
  - net worth compare 94,903.19 -> 93,094.14; change 0 -> +1,809.04 (= 266.88 + 1,542.17).
    Movers: from none to ETH, AAPL, 0700, INFY, RELIANCE gaining and USDC losing.
- **first_us** (31 Mar 18:00 New York; label "16 Mar"): the compare side was valued at 30 Mar,
  now at 16 Mar (the same 16 Mar values as mid):
  - stocks change -200.61 -> +66.27: each holding is now measured from 16 Mar's statement prices
    instead of 17 Mar's quotes: 0700 -240.50 -> -154.60 (301 vs 310 HKD), AAPL +33.53 -> +201.15
    (206 vs 200 USD), RELIANCE +9.54 -> +13.36 (2,950 vs 2,880 INR), INFY -3.18 -> +6.36 (1,640 vs
    1,620 INR; it moves from detractors to gainers).
  - crypto change -33.53 -> +1,508.64: compared with the 28 Feb snapshot instead of 17 Mar's (ETH
    -167.63 -> +2,715.55; USDC +134.10 -> -1,206.91: 2,000 -> 1,100 instead of 1,000 -> 1,100).
  - net worth compare 94,828.19 -> 93,094.14, change -1,150.03 -> +584.01: the stocks and crypto
    above plus 75.00 of card spending on 30 Mar, which is now after the compare point.

## Demo data (make db-seed-demo, synthetic)
Compare date 6 Oct (the demo's newest statements before today). The change was +485,784.46 and is
now +489,709.07: FX is now taken at 6 Oct instead of 5 Nov (cash +58,546.52 -> +58,635.50, stocks
+375,372.96 -> +376,404.84, crypto +55,058.98 -> +55,240.13). `compare_basis`: 33 holdings, 30
quoted, 3 at their statement price, none older than 6 Oct. The e2e fixture's since-update entry
was re-recorded (only that entry).

## Acceptance Criteria
- [x] Each holding is compared with its last quote on or before the compare date (D-21's rule).
- [x] A holding with no usable quote by then falls back to its statement price, flagged and counted.
- [x] Existing fields kept; new fields added and mirrored in `web/src/lib/api.ts`.
- [x] Test (`api/tests/test_since_update_basis.py`): a household where Sharekhan's newest
      statement is 16 days older than IBKR's; the old statement's holdings are compared at the
      31 Mar quote, not the statement price or 1 Apr's; a holding first quoted today is at its
      statement, flagged and counted; one never quoted is at its statement and not flagged.
- [x] Overview states the basis and marks fallback rows.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_since_update_basis.py tests/test_valuation_golden.py`
- `cd web && npx vitest run src/__tests__/WealthOverview.test.tsx`, `npx playwright test`.
- On a test instance with a copy of the real data: `/dashboard/net-worth-since-update` before and
  after; `compare_basis` shows how many holdings are still at an older statement price.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `make verify`: lint, typecheck pass; backend 972 passed / 25 skipped (one assertion in the new
  test fixed after, then that file, the goldens and the one-number contract re-run: 16 passed);
  frontend 61 files / 484 tests passed.
- e2e: 36 passed (incl. mobile-no-overflow); Overview Today tab checked at 340px (no overflow).

## Extra Files Changed
- `web/tests/e2e/fixtures/demo-api.json` — reason: the since-update response gained fields.

## Human Action Summary
- Next expected action: test instance with a copy of the real data (before/after per the issue).
- Open questions:
  - `/dashboard/stock-holdings`' `geography_performance` (Stocks page, 1-day) still compares with
    yesterday's quotes; not changed here.
