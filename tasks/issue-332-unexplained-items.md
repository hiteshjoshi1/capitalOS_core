# Issue 332: every Unexplained part names its items

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/332 (builds on #329, #330; supersedes #302)

## Decisions (D-83)
- `parts[].items[]` (label, amount, reason, link), largest first, max 8 + a "Rest" item so items add
  up to the part. API fields only added (BridgeItem); TS mirrors; the Overview card lists them under
  each part, phone-friendly (labels wrap, amounts don't).
- Untracked trades: per holding + platform. Crypto moved: per token, plus "In newly tracked wallets".
  Cards: per card, its share, why (no statement balance / statement of <date> + since), link to
  Liabilities. No price/quantity: per holding with which side lacks it. Statement gap: per holding,
  plus "Statement totals beyond the holdings listed". Other: bank rows no line counts, per account
  and category, then the rest. Catch-up (holdings) and Newly tracked: per holding / token.

## Real data, Nov 2026
- Card: Citibank (no statement balance). No price: SOL (no price at the start). Statement gap: IBKR's
  totals beyond its holdings. Other: DBS −6,100 (an excluded category), OCBC +1,460 (internal transfer,
  other side not recorded), DBS −7.50, rest +1,258.

## Tests
- tests/test_bridge_items.py (4), MonthBridgeCard.test.tsx (+1).

<!-- IMMUTABLE_PLAN_END -->
