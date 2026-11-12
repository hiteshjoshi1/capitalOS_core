# Issue 408: Overview & Crypto: since your last visit, price vs quantity per token, stablecoin filter and wrapped badge

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/408

## Objective
- U3: Overview says what changed since the last look (net worth, imports, items needing action).
- U9: each crypto token's change is split into price vs quantity (a buy, transfer or staking reward is not a gain).
- U10: a stablecoin filter and a "Wrapped BTC" style badge on the Crypto page.

## Architecture Decisions
- D-112 (see docs/decisions.md): `user_last_visit` (migration 086) with an hour's gap before the mark moves; crypto `month_change` from the bridge's `_split`; display-only token kinds in `app/crypto/token_kinds.py`.

## Acceptance Criteria
- [x] Strip on Overview (live month only), dismissible; nothing on a first visit or without news.
- [x] Crypto rows show the split (hover/tap), with the token as the unit.
- [x] Stablecoin filter and stablecoin / wrapped tags; no total changes.
- [x] Tests: backend (split, new token, kinds, visit mark and gap, currency change), web (strip, split wording).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_overview_crypto_408.py`
- `cd web && npx vitest run src/__tests__/overviewCrypto408.test.tsx`
- On the test instance: open Overview twice (the second time, the strip appears if anything changed), Crypto → hover a token's change.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved
