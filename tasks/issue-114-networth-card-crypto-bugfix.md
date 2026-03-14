# Issue 114: Net Worth Card Crypto Total Bugfix

## Objective
The dashboard Net Worth card shows an incorrect crypto total (S$183,620) that differs from the Crypto Holdings page (S$122,378). The discrepancy is caused by the dashboard **double-counting** crypto: it sums `positions` table rows where `asset_class='CRYPTO'` (legacy/corrupted data from Coinbase ingestion experiments) **plus** `crypto_wallet_snapshots` from active wallets. The Crypto Holdings page correctly uses only `crypto_wallet_snapshots`.

Goals:
1. Identify and remove corrupted Coinbase-originated CRYPTO rows from the `positions` table.
2. Eliminate the dual-source crypto calculation in the dashboard so both pages derive crypto from the single authoritative source: `crypto_wallet_snapshots`.
3. Ensure the net worth card and crypto holdings page show the same crypto total.

## Architecture Decisions
- **Decision 1: Single source of truth for crypto = `crypto_wallet_snapshots`.**
  The `positions` table is designed for brokerage-style holdings (stocks, funds, cash). Crypto is tracked through the wallet-snapshot pipeline (`crypto_wallets` → `crypto_wallet_snapshots` → `crypto_wallet_snapshot_items`). The `_networth_components()` function in `dashboard.py` should stop reading CRYPTO rows from `positions` and rely solely on `crypto_wallet_snapshots`.

- **Decision 2: Remove corrupted CRYPTO positions data, not the Coinbase platform seed.**
  The `platforms` table entry for COINBASE is harmless reference data and may be needed for future Coinbase integration. Only the corrupted `positions`/`accounts`/`assets` rows linked to experimental Coinbase ingestion should be cleaned. A diagnostic SQL script will be run first to inventory the damage before any deletes.

- **Decision 3: No schema changes.**
  This is a data-cleanup + query-fix issue. No migrations, no new tables, no model changes.

## Risks
- **Risk 1:** Removing positions rows may affect historical snapshots or other dashboard components (e.g., geography breakdown, asset allocation) if they reference CRYPTO-class assets. Mitigation: audit all queries in `dashboard.py` that touch `positions` and confirm CRYPTO filtering is appropriate.
- **Risk 2:** The S$122,378 on the Crypto Holdings page may itself be stale or wrong (old snapshot dates, inactive wallets with residual data). Mitigation: verify snapshot freshness and wallet statuses via SQL before declaring the fix complete.
- **Risk 3:** Currency conversion differences (anchor-date rate vs. `datetime.now()` rate) may cause minor discrepancies even after the fix. Mitigation: document that small FX-timing differences are expected; verify both values are within ~1% after fix.

## Open Questions
- **Q1:** Are there any `accounts` rows with `platform = 'COINBASE'` that were created during experiments? If so, should those accounts (and their linked transactions) also be deleted?
- **Q2:** Should the `positions`-table CRYPTO path be removed entirely, or guarded behind a feature flag for future exchange-based crypto ingestion (e.g., Coinbase CSV import)?
- **Q3:** Is the Crypto Holdings page total (`/crypto/summary`) considered the ground truth? The user should confirm the wallet-based number is correct before we align the dashboard to it.

## Acceptance Criteria
- [ ] AC1: `/dashboard/summary` crypto value matches `/crypto/summary` total (converted to same base currency) within 1% FX tolerance.
- [ ] AC2: No CRYPTO-class rows from corrupted Coinbase experiments remain in the `positions` table.
- [ ] AC3: `_networth_components()` in `dashboard.py` no longer sums `positions` rows where `asset_class='CRYPTO'` — crypto comes exclusively from `crypto_wallet_snapshots`.
- [ ] AC4: Crypto Holdings page (`/crypto/summary`) is unaffected — returns same value as before.
- [ ] AC5: All other net worth components (cash, stocks_funds, liabilities) remain unchanged.
- [ ] AC6: `make api-rebuild` succeeds, `curl /health` returns 200, `make api-smoke` passes.
- [ ] AC7: No orphaned `assets` rows left behind (assets with `asset_class='CRYPTO'` that are no longer referenced).

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Phase 1: Diagnostic (Read-Only)
- [ ] 1.1 Run SQL to list all `positions` rows joined to `assets` where `asset_class='CRYPTO'`, showing `account_id`, `asset_id`, `as_of`, `cost_basis_base`, and the linked account's platform.
- [ ] 1.2 Run SQL to list all `accounts` where platform = `'COINBASE'` or linked to CRYPTO positions.
- [ ] 1.3 Run SQL to list all `crypto_wallets` with their `status`, and the latest `crypto_wallet_snapshots.total_usd` per wallet.
- [ ] 1.4 Compute both totals via SQL: (a) `SUM(cost_basis_base)` from CRYPTO positions, (b) `SUM(total_usd)` from active wallet snapshots, confirm the delta explains the discrepancy.
- [ ] 1.5 Record diagnostic output in **Verification Evidence** section.

### Phase 2: Data Cleanup
- [ ] 2.1 Delete corrupted CRYPTO `positions` rows (and associated `transactions` if any) linked to Coinbase experiments.
- [ ] 2.2 Delete orphaned Coinbase `accounts` rows (if found in Phase 1).
- [ ] 2.3 Delete orphaned `assets` rows with `asset_class='CRYPTO'` that have zero remaining references in `positions`.
- [ ] 2.4 Verify cleanup: re-run Phase 1 queries to confirm CRYPTO positions are gone.

### Phase 3: Backend Code Fix
- [ ] 3.1 In `api/app/routers/dashboard.py`, function `_networth_components()` (lines 144–153): remove the `elif r["asset_class"] == "CRYPTO": crypto += value` branch so positions-table CRYPTO rows are excluded from net worth. Add a comment explaining crypto comes from wallet snapshots only.
- [ ] 3.2 Verify no other functions in `dashboard.py` depend on CRYPTO rows from positions (check `_geography()`, `_asset_allocation()`, etc.).
- [ ] 3.3 `make api-rebuild` — confirm container starts clean.

### Phase 4: Verification
- [ ] 4.1 `curl http://localhost:8000/health` — 200 OK.
- [ ] 4.2 `curl http://localhost:8000/dashboard/summary?month=2026-03&base_currency=SGD` — verify `net_worth.crypto` matches crypto holdings.
- [ ] 4.3 `curl http://localhost:8000/crypto/summary?base_currency=SGD` — verify `total_crypto_base` unchanged.
- [ ] 4.4 Compare the two crypto values — must match within 1%.
- [ ] 4.5 `make api-smoke` — all smoke tests pass.
- [ ] 4.6 Verify dashboard loads in browser at `http://localhost:5173`.

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

### Root Cause Analysis
The `_networth_components()` function in `api/app/routers/dashboard.py` (lines 103–187) computes crypto as:

```
crypto = SUM(positions.cost_basis_base WHERE asset_class='CRYPTO')   ← LEGACY/CORRUPTED
       + SUM(crypto_wallet_snapshots.total_usd WHERE wallet.status='active') * FX_rate
```

The `/crypto/summary` endpoint in `api/app/routers/crypto.py` computes crypto as:

```
crypto = SUM(crypto_wallet_snapshots.total_usd WHERE wallet.status='active') * FX_rate
```

The ~S$61,242 difference is the `positions`-table CRYPTO component — stale data from Coinbase ingestion experiments that wrote CRYPTO-class entries into the traditional positions pipeline.

### Files to Modify
| File | Change |
|------|--------|
| `api/app/routers/dashboard.py` | Remove CRYPTO branch from positions loop in `_networth_components()` (lines 152–153) |

### Files to Inspect (no changes expected)
| File | Reason |
|------|--------|
| `api/app/routers/crypto.py` | Confirm `/crypto/summary` query is correct — no changes needed |
| `web/src/components/dashboard/NetWorthHeroCard.tsx` | Confirm it reads `net_worth.crypto` — no frontend changes needed |
| `web/src/routes/CryptoHoldings.tsx` | Confirm it reads `total_crypto_base` — no frontend changes needed |

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-114-networth-card-crypto-bugfix.md
make task-build TASK=tasks/issue-114-networth-card-crypto-bugfix.md
make task-review TASK=tasks/issue-114-networth-card-crypto-bugfix.md
make task-rework TASK=tasks/issue-114-networth-card-crypto-bugfix.md
make task-ship TASK=tasks/issue-114-networth-card-crypto-bugfix.md
```
