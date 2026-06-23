# Issue 175: Canonical portfolio model and IBKR Flex cutover architecture

## Objective
- Re-architect investment portfolio ingestion around one canonical broker-neutral domain model, with separated facts for instruments, position snapshots, cash snapshots, NAV snapshots, trades, cash ledgers, corporate actions, import lineage, and data completeness.
- Add first-party Interactive Brokers Flex Web Service ingestion as the first cutover source so IBKR portfolio data can refresh daily instead of relying on monthly manual uploads.
- Preserve existing broker upload formats by adapting their parsed outputs into the canonical model; do not break Sharekhan, DBS Vickers, or other current upload flows.
- Move dashboard and analytics reads to the canonical portfolio model after migration and validation, then retire or compatibility-freeze legacy portfolio tables.

## Executive Summary

The current CapitalOS portfolio ingestion path is upload-centric. It stores uploaded files in `DATA_DIR`, fingerprints the file shape, selects a parser from `parser_registry`, normalizes into a narrow `ParseResult(transactions, positions)`, and writes directly into `transactions`, `assets`, and `positions`.

That path is useful and should remain unchanged for Sharekhan, DBS Vickers, IBKR CSV, UOB, OCBC, Citi, and other existing uploads. It is not sufficient for IBKR Flex because Flex provides richer and more structured data: daily NAV, cash by currency, open positions, FX rates, activity ledgers, trades, and corporate actions. Forcing Flex into the old `ParseResult` contract would lose auditability, cash/NAV reconciliation, broker IDs, report lineage, and data-completeness metadata.

The recommended architecture is a single canonical investment portfolio model, not an IBKR-specific sidecar and not one giant transactions table:

- Immutable raw broker payloads and import metadata.
- Broker-neutral accounts, instruments, position snapshots, cash snapshots, NAV snapshots, trades, cash ledgers, corporate actions, FX rates, report metrics, reconciliation results, and data-completeness metadata.
- Existing upload parsers remain supported, but their outputs are adapted into the same canonical model instead of becoming separate portfolio truth.
- A temporary compatibility projection into legacy `positions` / `assets` is allowed only while dashboard/reporting is migrated, and it must be source-owned and collision-safe.
- No destructive changes to current upload ingestion until canonical writes, canonical reads, and non-regression tests prove equivalence.

READY FOR ARCHITECTURE REVIEW before implementation.

## Implementation Phase Issues

- [Issue 176: Canonical portfolio phase 1 - IBKR Flex cutover](./issue-176-canonical-portfolio-phase-1-ibkr-flex-cutover.md)
- [Issue 177: Canonical portfolio phase 2 - upload parser adapters](./issue-177-canonical-portfolio-phase-2-upload-parser-adapters.md)
- [Issue 178: Canonical portfolio phase 3 - dashboard and analytics read migration](./issue-178-canonical-portfolio-phase-3-dashboard-analytics-read-migration.md)
- Target data model documentation: [Canonical Portfolio Data Model](../docs/finance/canonical-portfolio-model.md)

## Current-State Assessment

### Existing database entities relevant to portfolio ingestion

| Entity | Current role | Notes |
|---|---|---|
| `accounts` | User-owned financial account | Has `platform` text and optional `platform_id`; used for scoping transactions, positions, and imports. |
| `platforms` | Reference table for platform/broker/bank metadata | Existing broker labels include values such as `IBKR`, `DBS_VICKERS`, and `SHAREKHAN`. |
| `import_jobs` | Upload import job state | Tracks uploaded file path, file hash, detected signature, parser key, status, report path, and error. |
| `parser_registry` | File-signature-to-parser mapping | Used by upload flow; includes IBKR CSV, Sharekhan XLS, DBS Vickers XLS, etc. |
| `assets` | Current security/cash instrument table | Identified by `(symbol, quote_currency)`. Used by positions, transactions, dashboard, dividends, and market-data refresh. |
| `positions` | Current point-in-time position snapshot table | Unique by `(account_id, asset_id, as_of)`. Holds quantity, average cost, and `cost_basis_base`. Currently also used for cash positions. |
| `transactions` | Current cash and trade event table | Used for spending, dividends, cash-flow, and synthetic position movement. Model uses `Float`; DB migration uses `NUMERIC`. |
| `prices` | Market price snapshots | Used by dashboard and holdings valuation. |
| `market_symbol_map` | Asset to provider/exchange symbol mapping | Important for market-data enrichment and geography inference. |
| `market_data_runs`, `market_data_run_items` | Market-data refresh observability | Scheduler uses APScheduler and writes run metadata. |
| `crypto_wallet_snapshots`, `crypto_wallet_snapshot_items` | Crypto snapshot layer | Useful precedent for immutable daily snapshot behavior, but crypto remains separate. |

### Existing upload data flow

1. `POST /ingest/upload?account_id=...` or `POST /ingest/ibkr?account_id=...` receives an uploaded file.
2. `create_import_job()` stores the raw file under `DATA_DIR/raw/{job_id}/...` and computes `file_sha256`.
3. `compute_format_signature()` fingerprints CSV, Excel, or HTML-table structure.
4. `lookup_parser_key()` selects a parser from `parser_registry` or conservative platform-specific inference.
5. Parser returns `ParseResult`:
   - `transactions`
   - `positions`
   - `section_counts`
   - `parser_meta`
6. `validate_transactions()` validates only the normalized transaction rows.
7. `run_ingestion()` inserts transactions after fingerprint-like duplicate detection.
8. `run_ingestion()` upserts `positions` by `(account_id, asset_id, as_of)`.
9. A JSON report is written to `DATA_DIR/reports/{job_id}.json`.

### Existing broker parsers that must not regress

| Parser | Current output | Non-regression requirement |
|---|---|---|
| `ibkr_activity_csv_v1` | IBKR CSV cash transactions, trades, open positions, forex balances | Keep existing historical uploaded IBKR data available as pre-cutover reference data. After the IBKR Flex cutover date, manual IBKR uploads are rejected for authoritative holdings, cash, NAV, and future IBKR activity. |
| `sharekhan_holdings_xls_v1` | Sharekhan holdings snapshots | Legacy upload remains authoritative until a future Sharekhan connector exists. Keep existing XLS/HTML-table detection, parser inference, and position behavior equivalent through the canonical adapter. |
| `dbs_vickers_holdings_xls_v1` | DBS Vickers holdings snapshots | Legacy upload remains authoritative until a future DBS Vickers connector exists. Keep stale-registry recovery behavior for DBS Vickers XLS uploads and keep output equivalent through the canonical adapter. |
| `dbs_transaction_history_csv_v1` | DBS bank/broker transaction history | Do not reinterpret DBS cash-flow rows through the IBKR activity taxonomy. |
| `uob_account_xls_v1`, `uob_credit_card_xls_v1`, `ocbc_account_csv_v1`, `citi_credit_card_csv_v1` | Bank and card transactions/cash balances | Keep the upload pipeline contract stable. |

### What should remain unchanged initially

- Existing `/ingest/upload` and `/ingest/ibkr` endpoints.
- Existing parser registry behavior.
- Existing `ParseResult` contract for uploaded files.
- Existing dashboard, dividends, market-data, and spending APIs.
- Existing `positions`, `transactions`, `assets`, and `prices` write paths for uploaded files.
- Existing `SNAPSHOT_DAY` dashboard anchor behavior.

These remain unchanged only during the bridge period. The target state is that all investment-platform writes go through canonical portfolio services, and dashboard/analytics reads come from canonical snapshots and ledgers. The legacy tables either become projections owned by canonical code or are retired after validation.

### What is insufficient for Flex and broker-neutral support

- No broker connection/account identity separate from `accounts.platform`.
- No immutable raw report table with parser version, source type, report date, content hash, and import lineage.
- No canonical cash balance snapshots by currency.
- No portfolio NAV snapshot table.
- No canonical trade/execution ledger separate from generic spending `transactions`.
- No canonical cash ledger capable of classifying deposits, withdrawals, dividends, interest, fees, withholding tax, FX, and transfers without double-counting.
- No corporate action table.
- No broker security identifier mapping such as IBKR `conid`, exchange, ISIN, FIGI, or listing exchange.
- No first-class FX rate snapshots from broker reports.
- No reconciliation table or data-completeness status.
- Duplicate detection is application-level, not backed by stable natural keys in the database for every broker record type.
- The current Python model uses `Float` for money-like fields, even though production migrations use `NUMERIC`; new portfolio code must use exact decimal arithmetic end to end.

## Source Authority, Cutover, And Collision Rules

### Product authority rules

| Platform/source | Date window | Authority rule |
|---|---|---|
| IBKR manual CSV/upload | Before IBKR Flex cutover date | Existing uploaded IBKR rows remain historical/reference data. They may be migrated into canonical tables with `authority_status=reference` unless explicitly selected as the pre-cutover authoritative baseline. |
| IBKR Flex | On and after IBKR Flex cutover date | Flex is the only authoritative source for IBKR holdings, cash, NAV, FX rates, and future IBKR activity. |
| IBKR manual CSV/upload | On and after IBKR Flex cutover date | Manual IBKR uploads are rejected for that broker account. If an operator needs an emergency import, it must be a separate explicit admin override and stored as non-authoritative reference evidence. |
| Sharekhan upload | All current dates | Legacy upload remains authoritative for Sharekhan until a future connector is designed. No IBKR Flex code path may write or mutate Sharekhan portfolio facts. |
| DBS Vickers upload | All current dates | Legacy upload remains authoritative for DBS Vickers until a future connector is designed. No IBKR Flex code path may write or mutate DBS Vickers portfolio facts. |

### Database enforcement model

Do not rely only on prose or application discipline. The canonical schema needs explicit source authority columns and constraints.

Add a source-authority table:

```text
portfolio_source_authority_windows
- id
- broker_account_id
- platform_code
- source_kind              # ibkr_csv_upload | ibkr_flex_daily | ibkr_flex_backfill | sharekhan_upload | dbs_vickers_upload
- authority_scope          # holdings | cash | nav | trades | cash_activity | corporate_actions | fx | all
- effective_from_date
- effective_to_date
- authority_status         # authoritative | reference | disabled
- created_at
- metadata_json
```

Canonical fact tables then carry:

```text
source_authority_id
authority_status          # authoritative | reference | superseded
source_kind
source_document_id
import_run_id
source_row_hash
```

Use partial unique indexes to guarantee there is only one authoritative fact for a natural key:

```text
portfolio_position_snapshots:
  UNIQUE (broker_account_id, report_date, broker_instrument_id, currency)
  WHERE authority_status = 'authoritative'

portfolio_cash_balance_snapshots:
  UNIQUE (broker_account_id, report_date, currency)
  WHERE authority_status = 'authoritative'

portfolio_nav_snapshots:
  UNIQUE (broker_account_id, report_date)
  WHERE authority_status = 'authoritative'

portfolio_trades:
  UNIQUE (broker_account_id, broker_execution_id)
  WHERE broker_execution_id IS NOT NULL AND authority_status = 'authoritative'

portfolio_cash_ledger_entries:
  UNIQUE (broker_account_id, broker_transaction_id)
  WHERE broker_transaction_id IS NOT NULL AND authority_status = 'authoritative'

portfolio_corporate_action_events:
  UNIQUE (broker_account_id, broker_action_id)
  WHERE broker_action_id IS NOT NULL AND authority_status = 'authoritative'
```

Every importer must resolve exactly one matching authority window before writing authoritative canonical rows. If no matching authority window exists, the import either fails or writes reference-only rows. This prevents an IBKR CSV upload and an IBKR Flex import for the same account, asset, and date from both becoming authoritative.

The source authority row is also the cross-platform write gate. An IBKR Flex import run may only resolve authority rows where `platform_code='IBKR'` and `source_kind IN ('ibkr_flex_daily', 'ibkr_flex_backfill')`. Sharekhan and DBS Vickers authority rows use their own `platform_code` and upload `source_kind`, so Flex code has no valid authoritative foreign key for those accounts. Tests should assert this at the service layer, and the database should enforce it through foreign keys plus source-kind/platform check constraints where practical.

### Legacy table bridge enforcement

During the bridge period, legacy `positions` / `transactions` cannot safely distinguish authoritative Flex projections from uploaded broker rows unless source lineage exists. Add one of these before any Flex projection writes to legacy tables:

1. Add source lineage columns to legacy investment tables:
   - `source_kind`
   - `source_authority_id`
   - `source_import_run_id`
   - `source_document_id`
   - `projection_owner`

2. Or add a separate `portfolio_legacy_projection_claims` table that records which canonical run owns each projected `(target_table, account_id, asset_id, as_of/date)` key.

Preferred: migrate dashboard reads to canonical snapshots early and minimize writes back to legacy `positions`. If projection is needed, it must refuse to overwrite a row not already owned by the same canonical projection source.

## Architecture Decisions

- Decision 1: Build one canonical investment portfolio domain model for all broker/investment platforms. IBKR Flex is the first cutover source, not a separate IBKR-only model.
- Decision 2: Keep raw broker payloads immutable and separate from canonical broker-neutral records.
- Decision 3: Keep snapshots and ledgers distinct. Position snapshots, cash balance snapshots, NAV snapshots, trades, cash ledger entries, and corporate actions must not be collapsed into one transaction table.
- Decision 4: Preserve current upload formats during rollout, but adapt uploaded broker parser outputs into canonical portfolio services. The current `ParseResult` contract may remain as a parser boundary, but it should not remain the final portfolio storage model.
- Decision 5: Do not insert `BASE_SUMMARY` cash rows as spendable cash balances. Store them as broker summary/NAV evidence only.
- Decision 6: Use `reportDate` from Flex sections as the accounting date. `whenGenerated` is an import timestamp, not the portfolio snapshot date.
- Decision 7: Use `Decimal` in parser, normalization, and persistence code for all money, quantity, price, FX, cost basis, NAV, and P&L values.
- Decision 8: Do not compute contribution-adjusted returns, TWR, MWR, or closed-position P&L until historical activity backfill is available and classified.
- Decision 9: Enforce source authority windows in the database. At most one authoritative source may write a canonical fact for a broker account, natural key, and report/event date.
- Decision 10: After the IBKR cutover date, manual IBKR uploads are disabled for authoritative portfolio facts. Sharekhan and DBS Vickers uploads remain authoritative for their platforms and are isolated from IBKR Flex code.
- Decision 11: Dashboard total for an IBKR Flex account must read canonical NAV, including dividend and interest accruals. It must not display holdings plus cash as total portfolio value when broker NAV includes additional accrual components.
- Decision 12: Scheduler `max_instances=1` is not enough. Flex sync must acquire a database-backed lock or active-import uniqueness guard per broker account.

## Proposed Canonical Model

The table names below are proposed. Implementation may adjust names, but the ownership boundaries should remain.

### Broker identity and import lineage

| Entity | Source of truth? | Purpose | Key fields |
|---|---:|---|---|
| `broker_connections` | Source config | One configured broker integration for a user/platform. | `id`, `user_id`, `platform_code`, `connection_type` (`flex_api`, `upload`), `status`, `metadata_json`, timestamps. Secrets remain in env or secret store, not this table. |
| `broker_accounts` | Canonical identity | Maps broker account IDs to CapitalOS `accounts`. | `id`, `connection_id`, `account_id`, `broker_account_id`, `base_currency`, `account_name`, `status`, `flex_cutover_date`, `first_available_date`, `data_completeness_json`. Unique `(connection_id, broker_account_id)`. |
| `portfolio_source_authority_windows` | Source authority policy | Defines which source may write authoritative facts for an account/date/scope. | `id`, `broker_account_id`, `platform_code`, `source_kind`, `authority_scope`, `effective_from_date`, `effective_to_date`, `authority_status`, `metadata_json`. |
| `broker_import_runs` | Import audit | One retrieval/parse/normalize attempt. | `id`, `connection_id`, `broker_account_id`, `source_type` (`ibkr_flex_daily`, `ibkr_flex_backfill`, `upload`), `status`, `requested_at`, `started_at`, `finished_at`, `report_start_date`, `report_end_date`, `parser_version`, `error_code`, `error_message_redacted`, stats. |
| `raw_broker_documents` | Immutable raw evidence | Stores original XML/upload payload metadata and secure path/blob ref. | `id`, `import_run_id`, `document_type`, `content_sha256`, `byte_size`, `stored_path`, `content_type`, `broker_report_id`, `report_date`, `metadata_json`, created timestamp. Unique `content_sha256` where appropriate. |

### Instrument identity

The existing `assets` table is already used by dashboard, market-data, and dividends. In the canonical model, `assets` should become the display/security identity target, not the automatic truth source for broker contracts. A broker instrument is a tradable contract/listing; an asset is a mapped product/security representation used by product surfaces.

| Entity | Source of truth? | Purpose | Key fields |
|---|---:|---|---|
| `assets` | Display/security mapping target | Continue to represent displayable securities and cash assets. Existing fields remain initially. Mapping from broker instruments to assets must be deterministic or manually verified. |
| `asset_identifiers` | Canonical identifier map | Broker-independent and broker-specific identifiers. | `asset_id`, `identifier_namespace` (`IBKR`, `GLOBAL`, `YAHOO`, `EODHD`), `identifier_type` (`CONID`, `ISIN`, `FIGI`, `TICKER_EXCHANGE`, `CUSIP`), `identifier_value`, `metadata_json`. Unique `(identifier_namespace, identifier_type, identifier_value)`. |
| `broker_instruments` | Broker-specific security facts | Retains broker symbols/descriptions/exchanges even when not yet mapped to an asset. | `platform_code`, `broker_instrument_id`, `asset_id NULL`, `symbol`, `description`, `asset_category`, `currency`, `listing_exchange`, `metadata_json`. Unique `(platform_code, broker_instrument_id, listing_exchange, currency)`. |

Mapping rules:

- Do not auto-map purely from ticker plus currency.
- IBKR `conid + listingExchange + currency + assetCategory` defines the broker tradable contract.
- `broker_instruments.asset_id` starts nullable; map automatically only when a deterministic identifier match exists, otherwise require manual review.
- Related economic exposures, such as Tencent HK shares (`700` / HKD / SEHK) and Tencent ADR (`TCEHY` / USD / OTC), are separate broker instruments and should not be silently merged.

### Snapshots

| Entity | Source of truth? | Purpose | Key fields |
|---|---:|---|---|
| `portfolio_position_snapshots` | Canonical normalized snapshot | What was owned on a report date. | `broker_account_id`, `account_id`, `asset_id`, `broker_instrument_id`, `report_date`, `quantity`, `mark_price_native`, `market_value_native`, `cost_basis_price_native`, `cost_basis_native`, `unrealized_pnl_native`, `currency`, `fx_rate_to_base`, `market_value_base`, `percent_of_nav`, `source_document_id`, `source_row_hash`. Unique `(broker_account_id, report_date, broker_instrument_id, currency)`. |
| `portfolio_cash_balance_snapshots` | Canonical normalized snapshot | Cash balances by currency. | `broker_account_id`, `account_id`, `report_date`, `currency`, `ending_cash_native`, `ending_settled_cash_native`, `base_currency`, `fx_rate_to_base`, `ending_cash_base`, `source_document_id`, `source_row_hash`. Unique `(broker_account_id, report_date, currency)`. |
| `portfolio_nav_snapshots` | Canonical normalized snapshot | Broker-reported NAV in base currency. | `broker_account_id`, `account_id`, `report_date`, `base_currency`, `cash_base`, `stock_base`, `options_base`, `bonds_base`, `dividend_accruals_base`, `interest_accruals_base`, `total_nav_base`, `source_document_id`, `source_row_hash`. Unique `(broker_account_id, report_date)`. |
| `portfolio_report_metrics` | Canonical report-period summary | Period-level broker metrics that explain cash/NAV movement but are not individual ledger events. | `broker_account_id`, `report_date`, `period_start_date`, `period_end_date`, `report_section`, `metric_code`, `currency`, `amount_native`, `amount_base`, `source_document_id`, `source_row_hash`. Unique `(broker_account_id, report_date, report_section, metric_code, currency)`. |

### Ledgers and events

| Entity | Source of truth? | Purpose | Key fields |
|---|---:|---|---|
| `portfolio_event_groups` | Event relationship | Groups related trade, cash, fee, tax, and corporate-action rows that represent one economic event. | `id`, `broker_account_id`, `event_date`, `event_type`, `broker_trade_id`, `broker_execution_id`, `broker_transaction_id`, `source_document_id`, `metadata_json`. |
| `portfolio_trades` | Canonical event ledger | Executions/trades independent from spending `transactions`. | `broker_account_id`, `event_group_id`, `trade_date`, `settle_date`, `broker_trade_id`, `broker_execution_id`, `broker_order_id`, `asset_id`, `broker_instrument_id`, `side`, `quantity`, `price_native`, `gross_amount_native`, `commission_native`, `tax_native`, `net_cash_native`, `currency`, `fx_rate_to_base`, `source_document_id`, `source_row_hash`. Unique prefers broker execution/trade IDs; fallback stable business fingerprint. |
| `portfolio_cash_ledger_entries` | Canonical event ledger | Cash activity and running balances. | `broker_account_id`, `event_group_id`, `related_trade_id`, `date`, `settle_date`, `currency`, `activity_code`, `activity_type`, `description`, `amount_native`, `balance_native`, `external_flow_flag`, `asset_id`, `broker_transaction_id`, `broker_trade_id`, `fx_rate_to_base`, `amount_base`, `source_document_id`, `source_row_hash`. |
| `portfolio_corporate_action_events` | Canonical event ledger | Splits, mergers, spin-offs, symbol changes, stock dividends, transferred-in securities. | `broker_account_id`, `effective_date`, `asset_id`, `broker_instrument_id`, `action_type`, `quantity_before`, `quantity_after`, `ratio`, `cash_component_native`, `currency`, `broker_action_id`, `description`, `source_document_id`, `source_row_hash`. |
| `portfolio_transfers` | Canonical event grouping | Links cash/security transfers across accounts when both sides are known. | `broker_account_id`, `date`, `transfer_type`, `currency`, `amount_native`, `asset_id`, `quantity`, `linked_account_id`, `confidence`, `source_entry_id`. |

Trade/cash relationship rule:

- Trades explain security changes.
- Cash ledger entries explain cash movements.
- Report metrics explain period totals.
- Related rows should share `event_group_id` and/or `related_trade_id`.
- These rows must not be summed together as independent performance flows.

### FX, reconciliation, and completeness

| Entity | Source of truth? | Purpose | Key fields |
|---|---:|---|---|
| `portfolio_fx_rates` | Canonical snapshot | Broker-provided FX rates for report date. | `report_date`, `from_currency`, `to_currency`, `rate`, `source_platform`, `source_document_id`. Unique `(report_date, from_currency, to_currency, source_platform)`. |
| `portfolio_reconciliations` | Derived/audit | Records NAV and cash reconciliation outcomes. | `broker_account_id`, `report_date`, `reconciliation_type`, `expected_amount_base`, `actual_amount_base`, `difference_base`, `tolerance_base`, `status`, `details_json`. |
| `portfolio_data_quality_events` | Derived/audit | Missing sections, partial backfills, low-confidence mappings. | `broker_account_id`, `import_run_id`, `severity`, `code`, `message`, `metadata_json`. |
| `portfolio_data_completeness` | Derived/audit | Explicit history coverage by account and record type. | `broker_account_id`, `record_type`, `coverage_start_date`, `coverage_end_date`, `status`, `source`, `notes`. |

## IBKR Flex Source-To-Model Mapping

### EquitySummaryInBase

| Property | Assessment |
|---|---|
| Present in current sample | Yes. Contains `EquitySummaryByReportDateInBase` rows for report dates 2026-06-18 and 2026-06-19. |
| Authority | Authoritative broker NAV/base-currency reconciliation anchor. |
| Data kind | Snapshot. |
| Canonical target | `portfolio_nav_snapshots`. |
| Important fields | `accountId`, `reportDate`, `cash`, `stock`, `options`, `bonds`, `dividendAccruals`, `interestAccruals`, `total`. |
| Dedup key | `(broker_account_id, report_date)`. |
| Reconciles against | Position market values, per-currency cash snapshots, accruals, and broker total NAV. |
| Missing/empty behavior | Ingest other sections as partial if available, but mark NAV reconciliation unavailable and emit a data quality event. |

### CashReport

| Property | Assessment |
|---|---|
| Present in current sample | Yes. Includes `BASE_SUMMARY`, HKD, SGD, and USD rows. |
| Authority | Authoritative cash balance snapshot by currency. `BASE_SUMMARY` is a summary row, not a currency balance to double count. |
| Data kind | Snapshot plus report-period summary metrics. |
| Canonical target | Individual currencies to `portfolio_cash_balance_snapshots`; `BASE_SUMMARY` to reconciliation details/report metrics only; period metrics to `portfolio_report_metrics`. |
| Important fields | `currency`, `endingCash`, `endingSettledCash`, and when enabled: starting cash, deposits, withdrawals, account transfers, internal transfers, dividends, commissions, transaction tax, withholding tax, other fees, net trades sales, net trades purchases, ending cash, ending settled cash. |
| Dedup key | `(broker_account_id, report_date, currency)` for non-`BASE_SUMMARY` rows. |
| Reconciles against | Individual cash rows converted with `ConversionRates` should reconcile to `EquitySummaryInBase.cash`, within tolerance. |
| Missing/empty behavior | Do not fabricate cash from NAV. Mark cash snapshot missing; position-only NAV may still be stored as partial. |

Do not put Cash Report period totals into `portfolio_cash_ledger_entries`. They are aggregate report metrics, not individual cash events. Store them in `portfolio_report_metrics` with `report_section='cash_report'`.

### StmtFunds

| Property | Assessment |
|---|---|
| Present in current sample | Yes. One FX translation P&L row. |
| Authority | Authoritative cash activity/running balance ledger when report includes the relevant activity range. |
| Data kind | Event/ledger. |
| Canonical target | `portfolio_cash_ledger_entries`; optionally grouped into `portfolio_transfers` later. |
| Important fields | `accountId`, `currency`, `activityCode`, `activityDescription`, `reportDate`, `date`, `settleDate`, `tradeID`, `transactionID`, `debit`, `credit`, `amount`, `balance`. |
| Dedup key | Prefer `transactionID`; fallback `(broker_account_id, date, currency, activityCode, activityDescription, tradeID, amount, balance, source_row_hash)`. |
| Reconciles against | Cash balance change from prior report date to current report date, after including trades, fees, dividends, taxes, transfers, and FX translation entries. |
| Missing/empty behavior | Empty in daily report means no listed cash activity for that report period, not no history. Historical backfill is required before returns are trusted. |

When a StmtFunds row is related to a trade, commission, or tax leg, it should share `event_group_id` and carry `related_trade_id` or broker trade/execution IDs where available. This lets cash movement explain settlement without being misclassified as an external flow.

### OpenPositions

| Property | Assessment |
|---|---|
| Present in current sample | Yes. Contains HKD and USD stock positions with IBKR `conid`. |
| Authority | Authoritative current holdings snapshot for report date. |
| Data kind | Snapshot. |
| Canonical target | `broker_instruments`, `asset_identifiers`, `portfolio_position_snapshots`; later controlled projection to existing `assets` and `positions`. |
| Important fields | `accountId`, `currency`, `assetCategory`, `symbol`, `description`, `conid`, `listingExchange`, `position`, `markPrice`, `positionValue`, `costBasisPrice`, `costBasisMoney`, `fifoPnlUnrealized`, `fxRateToBase`, `reportDate`, `percentOfNAV`, `side`. |
| Dedup key | `(broker_account_id, report_date, conid, currency, listingExchange)`; fallback includes `symbol` and `assetCategory` if `conid` is missing. |
| Reconciles against | Sum of `positionValue * fxRateToBase` should reconcile to `EquitySummaryInBase.stock` for stock positions, by report date. |
| Missing/empty behavior | If account has non-zero broker stock NAV but no `OpenPositions`, fail or partial-fail the import; do not clear positions silently. |

### Trades

| Property | Assessment |
|---|---|
| Present in current sample | Section exists but empty. |
| Authority | Authoritative execution ledger when the report covers trade history and the query includes execution identifiers. |
| Data kind | Event/ledger. |
| Canonical target | `portfolio_trades`, with cash impact linked to `portfolio_cash_ledger_entries` where possible. |
| Important fields | Query-dependent. Require trade date, settle date, side, quantity, price, gross amount, commission, tax, net cash, currency, broker execution/trade/order IDs when enabled. |
| Dedup key | Prefer broker execution/trade ID. Fallback `(broker_account_id, trade_date, asset_id/conid, side, quantity, price, net_cash, currency, source_row_hash)`. |
| Reconciles against | Position deltas, cash ledger trade lines, and realized P&L once history is complete. |
| Missing/empty behavior | Empty means no trades in the daily report period. It does not mean historical trades are unavailable. Historical Flex backfill is required. |

### CorporateActions

| Property | Assessment |
|---|---|
| Present in current sample | Section exists but empty. |
| Authority | Authoritative non-trade event ledger when included in the relevant report period. |
| Data kind | Event/ledger. |
| Canonical target | `portfolio_corporate_action_events`. |
| Important fields | Query-dependent. Need action type, effective date, conid, symbol, description, ratio, cash component, old/new quantity when available. |
| Dedup key | Prefer broker corporate action ID. Fallback `(broker_account_id, effective_date, conid, action_type, description, ratio, source_row_hash)`. |
| Reconciles against | Position changes not explained by trades and cash ledger entries. |
| Missing/empty behavior | Empty means no listed corporate action in the report period, not no historical corporate actions. |

### ConversionRates

| Property | Assessment |
|---|---|
| Present in current sample | Yes. Includes many currencies to SGD. |
| Authority | Authoritative broker FX rates for base-currency reconciliation on the report date. |
| Data kind | Snapshot/reference. |
| Canonical target | `portfolio_fx_rates`. |
| Important fields | `reportDate`, `fromCurrency`, `toCurrency`, `rate`. |
| Dedup key | `(report_date, from_currency, to_currency, source_platform)`. |
| Reconciles against | Position native values, cash native values, NAV components, and base-currency ledger amounts. |
| Missing/empty behavior | Do not silently use app FX rates for broker reconciliation. If fallback app FX rates are used for display, mark reconciliation as approximate. |

### ChangeInNAV / Future Report Metrics

| Property | Assessment |
|---|---|
| Present in current sample | Not currently present, but likely to be enabled later. |
| Authority | Broker-provided period summary and attribution evidence. |
| Data kind | Report-period summary metrics, not individual ledger events. |
| Canonical target | `portfolio_report_metrics` with `report_section='change_in_nav'`. |
| Important fields | Starting NAV, ending NAV, change in NAV, deposits, withdrawals, dividends, interest, fees, taxes, realized/unrealized components, FX components where available. |
| Dedup key | `(broker_account_id, report_date, report_section, metric_code, currency)`. |
| Reconciles against | NAV snapshot deltas and classified cash/trade/corporate-action ledgers. |
| Missing/empty behavior | Do not infer attribution from incomplete metrics. Store data-completeness status and only compute performance metrics from complete enough ledgers/snapshots. |

## IBKR Flex Client Design

### Configuration

Use environment/configuration conventions, but never log or return secrets:

- `IBKR_FLEX_TOKEN`
- `IBKR_QUERY_ID`
- `IBKR_FLEX_BASE`
- `IBKR_USER_AGENT`
- Proposed: `IBKR_FLEX_SCHEDULER_ENABLED`
- Proposed: `IBKR_FLEX_DAILY_CRON`
- Proposed: `IBKR_FLEX_MAX_ATTEMPTS`
- Proposed: `IBKR_FLEX_INITIAL_BACKOFF_SECONDS`
- Proposed: `IBKR_FLEX_MAX_BACKOFF_SECONDS`

Secrets must not be persisted in `broker_connections.metadata_json`, import error messages, logs, reports, task files, test snapshots, or API responses.

### Retrieval flow

1. Call `GET {IBKR_FLEX_BASE}/SendRequest?t=...&q=...&v=3`.
2. Parse XML with a real XML parser. Prefer `defusedxml.ElementTree` for untrusted XML; do not parse with regex.
3. Extract `ReferenceCode`.
4. Call `GET {IBKR_FLEX_BASE}/GetStatement?t=...&q={ReferenceCode}&v=3`.
5. If IBKR returns a documented "statement still generating" response, retry with bounded exponential backoff and jitter.
6. Persist the raw XML as an immutable `raw_broker_documents` row before normalization.
7. Parse into canonical records using a parser version recorded on `broker_import_runs`.

Use an application HTTP client such as `httpx`, not shell commands or `curl`, in production code.

### Scheduling

Use the existing APScheduler pattern from `api/app/market_data/scheduler.py`:

- Add a separate IBKR Flex scheduler module rather than mixing broker imports into stock price refresh.
- `max_instances=1` is necessary but not sufficient because it only protects one process. Flex sync must also acquire a database-backed lock, such as a PostgreSQL advisory lock, a row-level lock on `broker_accounts`, or a unique active-import constraint per broker account.
- Schedule after IBKR daily report availability, not exactly at local midnight.
- Make the scheduler report-date-driven. If the latest successful authoritative canonical `report_date` is greater than or equal to the returned Flex report date, no-op safely instead of assuming calendar day equals new broker report.
- Provide an authenticated/admin manual trigger endpoint for testing and catch-up.
- Publish portfolio refresh events only after successful canonical ingest/projection.

## Reconciliation Rules

### Daily NAV invariant

For a report date:

```text
sum(OpenPositions.positionValue * OpenPositions.fxRateToBase)
+ sum(non-BASE_SUMMARY CashReport.endingCash * ConversionRates.rate)
+ EquitySummaryInBase.dividendAccruals
+ EquitySummaryInBase.interestAccruals
+ other supported asset buckets
= EquitySummaryInBase.total
```

For the current sample, `EquitySummaryInBase.stock` should reconcile to the base value of open stock positions, and `EquitySummaryInBase.cash` should reconcile to individual currency cash rows converted to base currency. `BASE_SUMMARY` must not be included in the individual-currency cash sum.

### Date invariant

- Use `reportDate` as the snapshot date.
- Store `whenGenerated` as import/report metadata only.
- If multiple `EquitySummaryByReportDateInBase` rows are returned, normalize each report date independently or select the intended latest report date explicitly for daily projection.
- Do not replace a newer projected dashboard snapshot with an older report unless running an explicit backfill.

### Idempotency invariant

Re-running the same Flex XML must:

- create at most one raw document row per content hash where dedupe is enabled,
- not duplicate position snapshots,
- not duplicate cash snapshots,
- not duplicate NAV snapshots,
- not duplicate trades,
- not duplicate cash ledger entries,
- not duplicate corporate actions,
- update reconciliation rows deterministically.

Event idempotency must prefer stable broker identity over source row hashes:

1. Broker-native stable IDs, such as IB execution ID, trade ID, transaction ID, or corporate action ID.
2. Stable business fingerprint, such as broker account, date/time, conid, side, quantity, price, and currency.
3. Source row hash only as final fallback and evidence.

This matters because the same trade or cash event can appear in a historical backfill report, a daily report, and a regenerated report with different surrounding metadata.

### Double-counting rules

- `BASE_SUMMARY` is summary evidence, not spendable cash.
- `EquitySummaryInBase.total` is NAV evidence, not a separate asset.
- Cash activity in `StmtFunds` should not be added to cash snapshots; it explains the change between snapshots.
- Trades can appear both as execution rows and cash movement rows; link or classify them rather than double-counting as external cash flow.
- FX translation P&L is not a deposit or withdrawal.
- Transfers are external cash/security flows only when they cross the portfolio boundary; internal account transfers must not distort performance.
- Corporate actions may change quantity/cost basis without ordinary buy/sell trades.

## Canonical Dashboard Read Model

Target state: dashboard and analytics read investment-platform data from canonical portfolio tables only.

For IBKR Flex accounts, total portfolio value must use `portfolio_nav_snapshots.total_nav_base`, because broker NAV includes components such as dividend accruals and interest accruals that may not appear as ordinary holdings or cash balances. Holdings plus cash is a breakdown, not necessarily total account value.

Compatibility bridge rule:

- During migration, legacy dashboard rows may be projected from canonical snapshots only as a temporary bridge.
- The bridge must either include explicit accrued-income snapshot records or clearly defer to canonical NAV for account totals.
- The product must not label `holdings + cash` as `Total Portfolio Value` for Flex accounts when canonical NAV includes accruals.

## Return And Performance Methodology

### What the current daily Flex report can support

- Current holdings by security, account, quantity, cost basis, mark price, native value, base value, and unrealized P&L.
- Current cash by currency and settled cash by currency.
- Broker-reported total NAV and NAV components.
- Daily snapshot-to-snapshot NAV movement once multiple daily reports exist.
- Reconciliation between positions, cash, FX rates, accruals, and broker NAV.

### What requires historical backfill

- Realized P&L.
- Complete trade chronology.
- Closed positions.
- Dividends and withholding tax history.
- External capital flows.
- Contribution-adjusted returns.
- Time-weighted return.
- Money-weighted return.
- Correct attribution of NAV changes to market movement, FX movement, deposits/withdrawals, dividends, interest, fees, taxes, and corporate actions.

### Recommended phases

1. **Snapshot correctness phase**
   - Ingest daily Flex current-state report.
   - Persist raw XML, NAV snapshots, cash snapshots, position snapshots, and FX rates.
   - Run NAV reconciliation.
   - Project positions/cash into existing dashboard tables only after reconciliation passes or passes with an explicit tolerance warning.

2. **Historical activity backfill phase**
   - Add separate historical Flex query for trades, cash activity, transfers, corporate actions, dividends, withholding tax, interest, and fees.
   - Populate ledgers and data-completeness coverage.
   - Do not compute return metrics until coverage is explicit.

3. **Attribution phase**
   - Classify ledger rows into external flows, investment income, taxes, fees, trades, FX, and internal transfers.
   - Reconcile cash ledger deltas to cash snapshots.
   - Reconcile trade and corporate action events to position deltas.

4. **Performance phase**
   - Total portfolio value: source from `portfolio_nav_snapshots`.
   - Unrealized P&L: source from broker snapshots initially; later recompute from canonical lots if needed.
   - Realized P&L: require trades/corporate actions.
   - External-flow-adjusted return: require classified deposits/withdrawals and internal transfer handling.
   - TWR: require subperiod valuations around external cash flows.
   - MWR/XIRR: require dated external cash flows and ending NAV.
   - Closed positions: require trade history and corporate actions; do not infer from missing open positions alone.

## Migration And Rollout Plan

### Phase 0: Architecture review

- Review this issue and approve table boundaries, source-of-truth decisions, and rollout order.
- Approve the canonical model as the target write/read model for all investment platforms, not only IBKR.
- Decide whether the first implementation creates all canonical tables at once or starts with import lineage, authority windows, snapshots, report metrics, and reconciliation first.
- Confirm where raw XML should be stored: filesystem under `DATA_DIR`, database bytea, object storage, or encrypted local storage.

### Phase 1: Schema and migrations

Add migrations only after review. Minimum first migration set:

- `broker_connections`
- `broker_accounts`
- `portfolio_source_authority_windows`
- `broker_import_runs`
- `raw_broker_documents`
- `broker_instruments`
- `asset_identifiers`
- `portfolio_nav_snapshots`
- `portfolio_cash_balance_snapshots`
- `portfolio_position_snapshots`
- `portfolio_report_metrics`
- `portfolio_fx_rates`
- `portfolio_reconciliations`
- `portfolio_data_quality_events`
- `portfolio_data_completeness`

Defer unless needed immediately:

- `portfolio_trades`
- `portfolio_cash_ledger_entries`
- `portfolio_corporate_action_events`
- `portfolio_transfers`
- `portfolio_event_groups`

Migration safety:

- Additive-only migrations.
- No destructive changes to existing `transactions`, `positions`, `assets`, `import_jobs`, or `parser_registry`.
- If legacy projection is needed, add source-lineage columns or projection-claims tables before any canonical writer can touch legacy `positions`.
- Add unique indexes for idempotency.
- Add partial unique indexes for authoritative canonical facts.
- Use `NUMERIC(38, 18)` or similar exact decimal types for money, quantity, prices, FX, and NAV.

### Phase 1b: Upload adapter to canonical model

- Keep existing upload parsers and `ParseResult` output stable.
- Add adapter code that converts parser outputs into canonical snapshots/ledgers with source authority windows.
- For Sharekhan and DBS Vickers, uploads remain authoritative and write canonical portfolio snapshots through this adapter.
- For IBKR manual uploads, writes are allowed only for pre-cutover reference/history according to the authority window.
- Verify canonical output and legacy dashboard output match before changing read paths.

### Phase 2: Raw import/run tracking

- Implement `broker_import_runs` lifecycle.
- Persist raw XML document before parsing canonical records.
- Store parser version and content hash.
- Redact all secret-bearing URLs and query params from logs/errors.
- Add unit tests for idempotent raw document persistence.

### Phase 3: Flex client

- Implement `SendRequest` and `GetStatement` using `httpx`.
- Use bounded exponential backoff for "statement still generating".
- Parse XML with a real XML parser.
- Add unit tests with mocked HTTP responses:
  - success,
  - still-generating then success,
  - authentication/config error,
  - malformed XML,
  - missing reference code,
  - network timeout.

### Phase 4: Flex parser and canonical normalization

- Parse the sample sections:
  - `EquitySummaryInBase`
  - `CashReport`
  - `StmtFunds`
  - `OpenPositions`
  - `Trades`
  - `CorporateActions`
  - `ConversionRates`
  - future Change in NAV / Cash Report metrics when enabled
- Convert numeric values to `Decimal`.
- Compute source row hashes.
- Upsert canonical snapshots/ledgers by stable natural keys.
- Preserve source-specific metadata without requiring every field to be first-class on day one.

### Phase 5: Reconciliation and projection

- Implement NAV reconciliation and cash reconciliation.
- Store reconciliation results with tolerance and status.
- Only after canonical rows exist, add projection code from canonical IBKR snapshots to existing:
  - `assets`
  - `asset_identifiers`
  - `positions`
  - optionally `market_symbol_map` where mapping is deterministic.
- Projection must be idempotent and must not delete or overwrite positions from other brokers.
- Projection must honor source authority windows and must refuse same-key collisions with non-owned legacy rows.
- Projection must not rely on `SNAPSHOT_DAY`; it uses Flex `reportDate` for daily current-state snapshots.

### Phase 5b: Dashboard canonical read migration

- Move dashboard account totals for Flex accounts to `portfolio_nav_snapshots`.
- Move holdings/cash breakdowns to canonical position and cash snapshots.
- Preserve legacy dashboard results for Sharekhan and DBS Vickers until their uploads are adapted and validated through canonical snapshots.
- After equivalence tests pass, dashboard and analytics should read only from canonical portfolio tables for investment platforms.

### Phase 6: Scheduler and manual trigger

- Add IBKR Flex scheduler with feature flag disabled by default until reviewed.
- Add authenticated/admin manual trigger endpoint.
- Prevent overlapping imports.
- Publish portfolio refresh event after successful projection.
- Add run status endpoint or reuse import run reporting.

### Phase 7: Historical backfill

- Add separate Flex query/config for historical trades, cash activity, transfers, dividends, interest, withholding tax, fees, and corporate actions.
- Populate ledgers and completeness coverage.
- Do not backfill from the daily current-state query alone.

### Phase 8: UI/API exposure

- Initially expose import run status and reconciliation status only.
- Keep existing dashboard behavior unchanged until canonical data is projected or read safely.
- Later retire or compatibility-freeze legacy portfolio tables after dashboard and analytics read only from canonical snapshots and ledgers.

## Acceptance Criteria

- [ ] Existing upload ingestion continues to pass for pre-cutover IBKR CSV, Sharekhan XLS/HTML-table, DBS Vickers XLS/HTML-table, DBS transactions, UOB, OCBC, and Citi.
- [ ] After the configured IBKR Flex cutover date, manual IBKR uploads are rejected for authoritative holdings, cash, NAV, and future activity.
- [ ] Before the configured IBKR Flex cutover date, existing uploaded IBKR data remains available as historical/reference data and does not collide with authoritative Flex facts.
- [ ] Sharekhan uploads remain authoritative for Sharekhan accounts; no IBKR Flex code path writes to or mutates Sharekhan portfolio data.
- [ ] DBS Vickers uploads remain authoritative for DBS Vickers accounts; no IBKR Flex code path writes to or mutates DBS Vickers portfolio data.
- [ ] No Flex implementation changes the `ParseResult` contract or parser registry behavior for existing uploads unless explicitly reviewed.
- [ ] Existing upload parser outputs are adapted into canonical portfolio records without changing their current parsed semantics.
- [ ] Source authority windows and partial unique indexes prevent two authoritative records for the same broker account, natural key, and report/event date.
- [ ] IBKR Flex credentials are read from configuration and are never logged, returned, committed, included in reports, or stored in task/docs output.
- [ ] Flex retrieval uses application HTTP code, not shell commands or `curl`.
- [ ] Flex XML is parsed with a real XML parser, not regex/string extraction.
- [ ] Raw Flex XML is persisted immutably with content hash, parser version, report date, source type, and import metadata before canonical normalization.
- [ ] Daily Flex ingestion is idempotent across repeated runs of the same report.
- [ ] Same Flex XML imported twice produces exactly one authoritative position snapshot set, one cash snapshot set, one NAV snapshot, and one reconciliation result per report date.
- [ ] Overlapping historical and daily reports produce exactly one authoritative trade, cash, or corporate-action event for each stable broker event identity.
- [ ] `BASE_SUMMARY` cash is not double-counted with individual-currency cash rows.
- [ ] Position, cash, FX, and NAV snapshots use exact decimal arithmetic.
- [ ] `reportDate` drives snapshot dates; `whenGenerated` is stored only as metadata.
- [ ] Reconciliation results are stored and queryable for each daily Flex import.
- [ ] Missing FX rate for a held currency marks the import partial/failed and does not create fake base valuation.
- [ ] Non-zero IBKR stock NAV with empty `OpenPositions` fails safely and leaves the displayed portfolio unchanged.
- [ ] Dashboard total for a Flex account equals canonical NAV, including dividend and interest accruals.
- [ ] Cash Report period metrics and Change in NAV metrics are stored in `portfolio_report_metrics`, not as individual cash ledger events.
- [ ] Trade rows and related cash movement rows are linked through `event_group_id`, `related_trade_id`, or stable broker event IDs so they are not double-counted as independent flows.
- [ ] Missing or empty Flex sections create explicit data-quality/completeness statuses instead of fabricated records.
- [ ] Historical trades, cash activity, corporate actions, and return metrics are not claimed complete until a backfill query populates the required ledgers.
- [ ] Scheduler is feature-flagged, bounded, observable, manually triggerable, and protected by a database lock or active-import constraint.
- [ ] Scheduler and manual trigger overlap creates only one successful import run for a broker account/report date.
- [ ] Sharekhan upload before/after canonical adapter migration produces identical positions and dashboard output.
- [ ] DBS Vickers upload before/after canonical adapter migration produces identical positions and dashboard output.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

- [ ] Review and approve this architecture.
- [ ] Add additive schema migrations for canonical broker import lineage, source authority, snapshot, metric, ledger, reconciliation, and completeness tables.
- [ ] Add ORM models or typed SQL helpers using exact decimal fields.
- [ ] Add source authority windows and cutover enforcement for IBKR, Sharekhan, and DBS Vickers.
- [ ] Add canonical adapter for existing upload parser outputs.
- [ ] Implement raw import/run tracking.
- [ ] Implement IBKR Flex client with redacted logging and retry/backoff.
- [ ] Implement Flex XML parser and canonical normalizer.
- [ ] Add reconciliation checks and data quality events.
- [ ] Add controlled projection into existing `assets`/`positions` only if needed, with source-lineage or projection-claim enforcement.
- [ ] Move dashboard totals and investment analytics to canonical snapshots/ledgers after equivalence tests pass.
- [ ] Add scheduler and manual trigger.
- [ ] Add historical backfill support.
- [ ] Add focused unit/integration tests and non-regression tests for existing upload parsers.
- [ ] Run deterministic safety gates.

## Verification Plan

Minimum command gates after implementation begins:

- `make api-rebuild`
- `make api-test`
- `make api-smoke`
- Focused tests:
  - `api/tests/test_ingest.py`
  - `api/tests/test_ingest_sharekhan.py`
  - `api/tests/test_ingest_dbs_vickers.py`
  - new `api/tests/test_portfolio_source_authority.py`
  - new `api/tests/test_portfolio_upload_canonical_adapter.py`
  - new `api/tests/test_ibkr_flex_client.py`
  - new `api/tests/test_ibkr_flex_parser.py`
  - new `api/tests/test_ibkr_flex_reconciliation.py`
  - new `api/tests/test_ibkr_flex_cutover.py`
  - new `api/tests/test_ibkr_flex_scheduler_lock.py`
  - new `api/tests/test_dashboard_canonical_portfolio.py`

Required scenario tests:

- Sharekhan upload before/after canonical adapter migration: identical `positions` rows and dashboard output.
- DBS Vickers upload before/after canonical adapter migration: identical `positions` rows and dashboard output.
- Same Flex XML imported twice: exactly one authoritative canonical snapshot set and one reconciliation result.
- Overlapping historical and daily reports: exactly one authoritative trade/cash/corporate-action event.
- Missing FX rate for held currency: import partial/failed; no fake base valuation.
- Non-zero IBKR stock NAV with empty `OpenPositions`: import fails safely; displayed portfolio unchanged.
- Scheduler/manual trigger overlap: only one successful import run.
- Flex account dashboard total: equals canonical NAV including accruals.

Manual verification:

- Trigger one IBKR Flex daily import against configured env.
- Confirm raw XML content hash is stored.
- Confirm canonical snapshots exist for report date.
- Confirm `BASE_SUMMARY` is not inserted as cash.
- Confirm reconciliation status and difference are visible.
- Confirm existing dashboard still loads.
- Confirm existing upload endpoints still import sample files.

## Open Decisions

- Where should raw broker documents live long term: local filesystem, database, encrypted local storage, or object storage?
- Should `broker_connections` store only non-secret metadata, with all secrets kept in env, or should a local secret-store abstraction be introduced?
- What exact IBKR Flex cutover date should be configured for each IBKR broker account?
- Should the first migration create all ledger tables now, or defer inactive ledgers until the historical backfill query is defined?
- What tolerance is acceptable for NAV reconciliation: exact to cents, small decimal epsilon, or broker-report-currency dependent?
- Should daily Flex data ever project into existing `positions`, or should dashboard read canonical snapshots first for IBKR accounts?
- If legacy projection is needed, should we add source-lineage columns to `positions` or use a separate projection-claims table?
- Should IBKR cash balances project into existing `positions` as cash assets during the bridge, or should dashboard read canonical cash snapshots first?
- What is the desired scheduler time and timezone relative to IBKR report availability?
- How many historical years should be backfilled for trades, dividends, cash activity, transfers, and corporate actions?
- What is the product treatment for transferred-in securities with missing acquisition history?
- Should closed positions appear in a new portfolio history UI before full performance attribution is complete?
- Should Sharekhan and DBS Vickers be migrated to canonical writes before or after IBKR Flex daily sync ships?

## Risks

- Flex query shape can change when fields are added; parser must tolerate missing optional fields and store source metadata.
- IBKR activity sections can be empty on quiet days; implementation must not mark history complete from a daily report.
- Double-counting cash, trades, and NAV is easy if snapshots and ledgers are mixed.
- Existing dashboard currently derives current state from `positions`, `transactions`, and `prices`; direct replacement would be high-risk.
- Existing `assets` uniqueness by `(symbol, quote_currency)` is weaker than broker/security identity and can collide for multi-listing instruments.
- Float use in existing Python models/parsers can leak into new code if not isolated.
- Projection into existing tables can overwrite other broker snapshots if keyed incorrectly.
- Logging full Flex URLs can leak tokens unless redaction is enforced.
- Widening scope from IBKR-only to canonical domain migration is architecturally cleaner but substantially larger. It must be phased so daily IBKR sync does not wait for every future analytics feature.

## Recommended Decisions

- Approve the canonical portfolio model as the target write/read model for all investment platforms, with separated facts rather than one giant transactions table.
- Keep current upload formats supported, but route their parsed outputs through canonical adapters after equivalence tests are in place.
- Use source authority windows and partial unique indexes to enforce cutover/collision rules in the database.
- Use existing `assets` as the dashboard-facing mapping target for now, plus nullable `broker_instruments.asset_id` and namespaced `asset_identifiers` for stronger identity.
- Implement import lineage, source authority, snapshots, report metrics, FX, and reconciliation first; then historical ledgers.
- Keep scheduler disabled by default until one manual Flex import reconciles successfully.
- Treat daily Flex as current-state truth, not historical performance truth.
- Prefer moving dashboard reads to canonical snapshots over long-term projection into legacy `positions`.

## Execution Journal (Codex Mutable)
- Current Stage: `architecture-plan-created`
- Workflow Status: `running`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-20T09:03:51Z`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` - documentation/task-file-only change.
- `typecheck`: `skip` - documentation/task-file-only change.
- `tests`: `skip` - documentation/task-file-only change.
- `e2e`: `skip` - documentation/task-file-only change.
- `api-smoke`: `skip` - documentation/task-file-only change.
- `policy-checks`: `pass` - no `.env` secret values read or copied into this issue.

## Extra Files Changed (Codex Mutable)
- None.

## Permanently Failed / Gave Up (Codex Mutable)
- Stop reason: `n/a`
- Attempted mitigations: `n/a`
- Suggested human action: `review architecture and approve implementation sequence`

## Human Action Summary (Codex Mutable)
- Next expected action: review this issue and approve or revise the canonical model/migration sequence.
- Open questions:
  - See "Open Decisions" above.

## Automation Log (Mutable)
- 2026-06-20T08:01:39Z - Created design-first issue from attached prompt after inspecting current upload ingestion, parser registry, broker parsers, dashboard position synthesis, migrations, and scheduler patterns.
- 2026-06-20T08:35:56Z - Revised architecture to make the canonical portfolio model the target write/read model for all investment platforms; added IBKR cutover authority rules, database collision enforcement, report metrics, tighter instrument identity, trade/cash event grouping, scheduler locking, canonical dashboard NAV rules, and expanded acceptance tests.
- 2026-06-20T09:03:51Z - Split implementation into phase issues 176, 177, and 178; added canonical portfolio data model documentation under docs/finance.

READY FOR ARCHITECTURE REVIEW
