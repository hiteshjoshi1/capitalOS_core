# Issue 74: Remove the unused React Native dependency tree and deprecated npm packages

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/74

## Objective
- No unused React Native packages and no deprecated packages in `web/`'s install.

## Architecture Decisions
- D-15: `web/.npmrc` `legacy-peer-deps=true`; jsdom 25 → 29.1.1 (30 needs Node ≥ 22.22.2).

## Acceptance Criteria
- [x] 744 → 473 packages; no `react-native`; npm reports no deprecated packages; `npm audit` 0.
- [x] No required peer that the web build uses is missing (`@solana/codecs-strings`' text-encoder peer is unused in the browser build: it uses `globalThis.TextEncoder`).
- [x] Production bundle unchanged (unminified diff vs main differs only by `web/.env.local` values).
- [ ] Crypto Wallets page: connect Phantom and verify a Solana wallet still works (Hitesh, test instance).

## How To Test
- `cd web && npm ci && npm run build && npx vitest run`.
- Test instance: Crypto Wallets → connect Phantom.

<!-- IMMUTABLE_PLAN_END -->
