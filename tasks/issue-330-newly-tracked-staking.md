# Issue 330: Newly tracked, and staking rewards as income

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/330 (builds on #329)

## Decisions (D-82)
- Newly tracked line: wallets whose first snapshot is after the period start (value at the end, per
  token), cash accounts with no starting balance (end balance less own period transactions), holdings
  accounts with no starting holdings (no cash record). Taken out of crypto moved / untracked trades.
- Staking rewards: stETH/eETH held at both ends, quantity growth <= 2% -> income ("Dividends, interest
  & staking", part "staking"), not crypto moved.

## Results (real data, Nov 2026)
- Newly tracked: the Solana wallet (first seen 5 Nov) +S$ 6,505; staking (stETH) +S$ 156.
- Crypto moved +S$ 6,136 -> −S$ 526, which with "no price" +S$ 525 is the 5 SOL without a 30 Oct price
  (#331 back-fills it). Unexplained +S$ 3,611 -> −S$ 3,051.

## Tests
- tests/test_bridge_newly_tracked.py (8): staking yes/no cases, new cash account, new holdings account,
  new wallet with its tokens. test_month_bridge.py: newly_tracked is an optional line.

<!-- IMMUTABLE_PLAN_END -->
