# Issue #443: Overview & demo fixes from review #432 (V5, V7, V8, V10)

Hitesh, 2026-11-16: build V5+V7, V8, V10 from the UX review #432.

## V5: one baseline in the hero
The hero carried three different "since" numbers: the "since your last visit" strip, "Since last
update (date)" and "vs <month> month-end". "Since last update" left the hero
(`web/src/routes/WealthOverview.tsx`); the page's baseline is month-end, and the strip answers
"since I last looked". The since-update data still feeds Today's movers.

## V7: Unexplained isn't a gain
`Delta` gets a `neutral` tone (`delta--neutral`, the `--warn` caution colour, either sign; the
arrow stays). The bridge rows use it for the Unexplained line, so This month (Overview) and History →
Compare (which reuses `BridgeRow`) both show it amber, never green or red.

## V8: demo closed months put market moves in Unexplained
Demo data only; real data was checked (Sep −S$ 15.0k, Oct −S$ 13.9k under Markets).
Root cause in `migrations/seed_dummy.sql`:
- Stock snapshots stored the **average cost** as the statement's `market_price` (a constant) while
  `market_value` grew each month. For closed months the bridge prices holdings at the statement
  price (D-21), saw "same price, different value", and put the whole move into
  "Statement values that differ from quantity × price × rate".
  Now the price is the month's value per share.
- Crypto snapshot items grew the **amount held** at a fixed price, which read as "crypto moved into
  the wallets". Now the price moves and the amount stays (stablecoins keep $1 and a growing amount).
- Demo October went from Markets S$ 0 / Unexplained +S$ 279k to Markets +S$ 240k
  (stocks +199k, crypto +41k) / Unexplained +S$ 38k (cards without a statement balance, a
  stablecoin top-up, timing). No bridge code changed.

## V10: racing first visits
`POST /dashboard/visit` raised UniqueViolation (500) when two first visits raced.
`services/last_visit.mark_visit` now inserts with `ON CONFLICT DO NOTHING` (or `DO UPDATE` for
Dismiss), Postgres and SQLite. Tests simulate the race (fail on the old code).

## Tests
- Backend: three new tests in `api/tests/test_overview_crypto_408.py`.
- Web: Delta neutral tone, bridge Unexplained colour, Overview hero without "since last update".
- `make e2e-smoke`: only the phone Overview baseline changed (Unexplained amber, shorter hero).
