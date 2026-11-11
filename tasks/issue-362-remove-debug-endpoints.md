# Issue #362: remove debug crypto endpoints and unused endpoints

From #353 T5 (#130 §5.4).

## Change
- Removed `POST /crypto/debug/verify-sig` and `POST /crypto/debug/verify-bytes` (no sign-in, open when `CRYPTO_ADMIN_KEY` was unset, no caller), their `SolanaDebugVerifyIn` model and the `verify_solana_signature_debug` / `verify_solana_signature_bytes_debug` helpers.
- Kept `/crypto/tokens` and `/dashboard/stock-exposure`: not called by the web app, but tests use them as checks (one-number contract, valuation invariants, hidden-token count). D-100.

## Searched
web/src, web/tests, api/tests, orchestration, scripts, tools; the MCP connects to Postgres directly and calls no API route.

## Tests
- `api/tests/test_removed_debug_endpoints.py`: both paths 404, no `/crypto/debug` route registered.
