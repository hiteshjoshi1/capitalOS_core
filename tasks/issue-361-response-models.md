# Issue #361: response models, drop stored_path, consistent 422

From #353 T4 (#130 §5.5, §7.8).

## Change
- `response_model` on 16 routes:
  - crypto: wallets, summary, tokens, token-visibility (GET and PUT), allowlist, solana/blockhash, price-backfill-plan
  - ingest: jobs, jobs/{id}
  - market-data: status, runs, unpriced
  - portfolio: ibkr-flex import-runs, reconciliations, data-quality-events
- Models: `api/app/schemas/{crypto,ingest,market_data,portfolio,common}.py`. `IsoDateTime` keeps `isoformat()` timestamps; `/market-data/status` uses `response_model_exclude_unset` so an exchange that never ran has no run fields, as before.
- `GET /ingest/jobs/{id}` no longer returns `stored_path` (server path; the web app never read it). TS type and test mocks updated.
- 400 → 422 for invalid request values (36 sites outside `auth.py`); 400 stays for valid requests the server can't act on. D-99.

## Checked
- All 16 routes captured on the demo seed before and after (`/tmp` script): identical except `stored_path` gone and whole-number Decimal prices written `3000.0`.

## Follow-up (needs Hitesh's okay)
- Generate the TS types from OpenAPI with a CI diff (new dev dependency).
- `report_path` in the same response is also a server path; not removed here (only `stored_path` was agreed).
