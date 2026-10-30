# Issue 95: @solana/web3.js 3 (Dependabot #86): assess and migrate or hold

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/95

## Objective
- Decide on @solana/web3.js 3.0.2.

## Architecture Decisions
- Hold on 1.x. 3.x is a rewrite on `@solana/kit`; every current `@solana/wallet-adapter-*` package (react 0.15.40, base 0.9.28, phantom 0.9.30, react-ui 0.9.40) and `@solana-mobile/wallet-adapter-mobile` 3.0.0 declares `@solana/web3.js ^1.99.0`. Migrating means replacing the wallet connection stack (Phantom/Ledger verification on Crypto Wallets), not bumping one package.
- Dependabot ignores @solana/web3.js majors (with the reason) so #86 doesn't come back; revisit when wallet-adapter supports kit or we replace it.

## Acceptance Criteria
- [x] Peer ranges checked; Dependabot ignore added; #86 closed with the reason.

<!-- IMMUTABLE_PLAN_END -->
