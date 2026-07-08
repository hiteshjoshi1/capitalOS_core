# Issue 193: Real domicile/geography field for crypto wallets

## Objective
- Stop hardcoding all crypto holdings to `"US"` in geography/domicile attribution so the Wealth → Risk screen's "Where the wealth is booked" geography breakdown is accurate for users whose crypto custody (exchange account region, self-custody jurisdiction, etc.) isn't the US.

## Current State
- `api/app/routers/dashboard.py` — `_geography_exposure()` (and the related `_top_holdings()` helper) hardcodes every crypto row's `geo` field to `"US"` (see `dashboard.py:926`, `"geo": "US"` inside the crypto-rows loop), regardless of which exchange/wallet/chain the holding actually sits on.
- Stock/fund holdings already have real domicile inference via `_infer_country()` (`dashboard.py:~440-465`), using `home_country`, platform, quote currency, and exchange code.
- No crypto wallet/account model currently has a country/domicile column to infer from (confirmed via backend audit: no `country`/`domicile` field on the crypto wallet or exchange-account models).

## Architecture Decisions
- Add a nullable `domicile_country` (or `country`) column to whichever model represents a crypto wallet/exchange connection (self-custody wallet row and/or exchange-account row — inspect `models/` for the actual crypto wallet/account table names).
- Default/backfill strategy for existing rows: leave `NULL` and fall back to the current `"US"` default only when unset, rather than forcing a value — so this is additive, not a breaking migration.
- Surface the field in whatever UI already manages wallets (e.g. `routes/CryptoWallets.tsx`'s wallet list/add-wallet form) as an optional field, defaulting to blank/unset.
- Update `_geography_exposure()`/`_top_holdings()` to read the real field when present, falling back to `"US"` when null (no behavior change for users who don't set it).

## Acceptance Criteria
- [ ] New nullable domicile column on the crypto wallet/account model + migration.
- [ ] Geography exposure endpoint uses the real value when set.
- [ ] No regression for existing data (still defaults to `"US"` when unset).
- [ ] Optional UI to set the field on a wallet (can be minimal — a select/text input on the existing wallet form).

## How To Test
- Run `make test-backend` and confirm geography-exposure tests cover both the null-fallback and real-value cases.
- Run `make test-frontend` if the wallet form is touched.
- Manual: set a non-US domicile on a test wallet, confirm Wealth → Risk's geography donut/legend reflects it.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not started`
- Workflow Status: `blocked`
- Provider/Model: `<provider>/<model>`
- Last Updated: `<timestamp>`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `Not started — filed from design-handoff implementation pass (2026-07-08). Current hardcoded "US" behavior is unchanged/non-regressive, so this is an accuracy improvement, not a bug fix for the Wealth Risk screen rebuild.`
- Attempted mitigations:
  - `None — Wealth Risk screen ships using the existing (US-hardcoded) geography data as-is.`
- Suggested human action: `Prioritize based on how many users actually hold crypto custodied outside the US.`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Identify the exact crypto wallet/account model to extend, then schedule.`
- Open questions:
  - `Should domicile be per-wallet, per-exchange-account, or per-chain (e.g. a Ledger cold wallet vs. a Coinbase account might have different real jurisdictions)?`
- If PR raised but intent partial:
  - unmet criteria: `n/a — not started`
  - follow-up issue: `n/a`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
