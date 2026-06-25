"""
Canonical portfolio read services for Phase 3 dashboard migration.

Provides read-path functions that source facts from the canonical portfolio
tables (portfolio_position_snapshots, portfolio_cash_balance_snapshots,
portfolio_data_completeness) instead of the legacy positions / transactions
tables.

Design rules:
- IBKR Flex accounts are covered by NAV snapshots (latest_authoritative_nav_by_legacy_account).
  Position and cash reads here EXCLUDE those accounts to avoid double-counting.
- Sharekhan / DBS Vickers accounts have canonical position snapshots written by
  the upload adapter (Phase 2).  These are the primary targets for Phase 3.
- If broker_instruments.asset_id is set, asset metadata is pulled from assets.
  Otherwise a symbol-based fallback lookup is attempted so that geography and
  platform allocation remain equivalent to legacy reads.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql

# SQL fragment that tests whether a legacy account has any authoritative
# canonical position snapshots at/before a given anchor date.
# Bind params required: :anchor_date, :current_user_id  (plus p.account_id in context)
_CANONICAL_POSITION_EXISTS_SQL = """
    EXISTS (
        SELECT 1
        FROM broker_accounts _cba
        JOIN portfolio_position_snapshots _cps ON _cps.broker_account_id = _cba.id
        WHERE _cba.legacy_account_id = {account_id_col}
          AND _cps.report_date <= :anchor_date
          AND _cps.authority_status = 'authoritative'
    )
"""

# SQL fragment that tests whether a legacy account has any authoritative
# canonical NAV snapshots at/before a given anchor date.
# Used to exclude IBKR Flex accounts from the canonical position read.
_CANONICAL_NAV_EXISTS_SQL = """
    EXISTS (
        SELECT 1
        FROM broker_accounts _nba
        JOIN portfolio_nav_snapshots _nns ON _nns.broker_account_id = _nba.id
        WHERE _nba.legacy_account_id = {account_id_col}
          AND _nns.report_date <= :anchor_date
          AND _nns.authority_status = 'authoritative'
    )
"""


def has_canonical_position_snapshot_sql(account_id_col: str = "p.account_id") -> str:
    """Return an EXISTS sub-expression testing for canonical position facts."""
    return _CANONICAL_POSITION_EXISTS_SQL.format(account_id_col=account_id_col)


def canonical_position_rows_by_legacy_account(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
    include_nav_accounts: bool = False,
) -> list[dict[str, Any]]:
    """
    Return position-like dicts from portfolio_position_snapshots for accounts
    that have canonical position data.

    IBKR Flex accounts have NAV snapshots (handled by
    latest_authoritative_nav_by_legacy_account) and are excluded by default to
    prevent double-counting in valuation/allocation read paths. Detail-only
    consumers, such as the stock holdings list, may opt in to include those
    accounts while still using NAV for account totals.

    Returned dicts match the shape produced by _synthetic_position_rows so that
    callers can merge them with the legacy row list without special-casing.
    """
    q = text(
        """
        WITH latest_canonical AS (
          SELECT ps.broker_account_id, MAX(ps.report_date) AS report_date
          FROM portfolio_position_snapshots ps
          JOIN broker_accounts ba ON ba.id = ps.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE ps.report_date <= :anchor_date
            AND ps.authority_status = 'authoritative'
            AND ba.legacy_account_id IS NOT NULL
            AND (
              :include_nav_accounts
              OR NOT EXISTS (
                SELECT 1
                FROM portfolio_nav_snapshots ns
                WHERE ns.broker_account_id = ba.id
                  AND ns.report_date <= :anchor_date
                  AND ns.authority_status = 'authoritative'
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
          GROUP BY ps.broker_account_id
        ),
        sym_asset AS (
          SELECT LOWER(symbol) AS sym, MIN(id) AS asset_id
          FROM assets
          WHERE symbol IS NOT NULL AND symbol <> ''
          GROUP BY LOWER(symbol)
        ),
        map_exchange AS (
          SELECT m.asset_id, MIN(UPPER(m.exchange_code)) AS exchange_code
          FROM market_symbol_map m
          WHERE m.is_active = TRUE
          GROUP BY m.asset_id
        )
        SELECT
          ba.id                      AS broker_account_id,
          ba.legacy_account_id AS account_id,
          COALESCE(a.id, a_sym.id)  AS asset_id,
          bi.symbol                  AS symbol,
          COALESCE(a.name, a_sym.name, bi.description, bi.symbol) AS name,
          COALESCE(CAST(a.asset_class AS TEXT), CAST(a_sym.asset_class AS TEXT), bi.security_type, 'STOCK') AS asset_class,
          COALESCE(a.quote_currency, a_sym.quote_currency, bi.currency) AS quote_currency,
          COALESCE(a.home_country, a_sym.home_country) AS home_country,
          COALESCE(mx.exchange_code, mx_sym.exchange_code) AS exchange_code,
          COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
          pl.platform_type AS platform_type,
          COALESCE(pl_by_code.country, pl.country, acc.country) AS platform_country,
          EXISTS (
            SELECT 1
            FROM portfolio_nav_snapshots ns
            WHERE ns.broker_account_id = ba.id
              AND ns.report_date <= :anchor_date
              AND ns.authority_status = 'authoritative'
          ) AS has_nav_snapshot,
          ps.report_date AS report_date,
          CAST(ps.quantity AS DOUBLE PRECISION) AS quantity,
          CAST(ps.market_price AS DOUBLE PRECISION) AS avg_cost,
          CAST(ps.market_value_base AS DOUBLE PRECISION) AS cost_basis_base,
          CAST(ps.market_price AS DOUBLE PRECISION) AS snapshot_market_price,
          CAST(ps.market_value_local AS DOUBLE PRECISION) AS snapshot_market_value_local,
          CAST(ps.market_value_base AS DOUBLE PRECISION) AS snapshot_market_value_base,
          CAST(ps.cost_basis_local AS DOUBLE PRECISION) AS snapshot_cost_basis_local,
          CAST(ps.cost_basis_base AS DOUBLE PRECISION) AS snapshot_cost_basis_base
        FROM portfolio_position_snapshots ps
        JOIN latest_canonical lc
          ON lc.broker_account_id = ps.broker_account_id
         AND lc.report_date = ps.report_date
        JOIN broker_accounts ba ON ba.id = ps.broker_account_id
        JOIN accounts acc ON acc.id = ba.legacy_account_id
        LEFT JOIN platforms pl ON pl.id = acc.platform_id
        LEFT JOIN platforms pl_by_code ON pl_by_code.code = acc.platform
        JOIN broker_instruments bi ON bi.id = ps.broker_instrument_id
        LEFT JOIN assets a ON a.id = bi.asset_id
        LEFT JOIN sym_asset sa ON sa.sym = LOWER(bi.symbol)
        LEFT JOIN assets a_sym ON a_sym.id = sa.asset_id AND bi.asset_id IS NULL
        LEFT JOIN map_exchange mx ON mx.asset_id = a.id
        LEFT JOIN map_exchange mx_sym ON mx_sym.asset_id = a_sym.id AND bi.asset_id IS NULL
        WHERE ps.authority_status = 'authoritative'
        """
    )
    rows = db.execute(
        q,
        {
            "anchor_date": anchor_date,
            "current_user_id": current_user_id,
            "include_nav_accounts": include_nav_accounts,
        },
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["has_nav_snapshot"] = bool(item.get("has_nav_snapshot"))
        out.append(item)
    return out


def canonical_cash_rows_by_legacy_account(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    """
    Return cash-like dicts from portfolio_cash_balance_snapshots.

    Unlike position snapshots, cash snapshots are written by IBKR Flex (Phase 1)
    as well as any future broker that provides currency-level cash detail.
    Upload adapters (Sharekhan, DBS Vickers) do NOT write cash snapshots.

    Returned dicts have keys: account_id, currency, value (in base currency).
    Callers must still FX-convert 'value' when base_currency is not the report base.

    Note: cash_balance_base is already in the broker account's base currency so
    it can be used directly after the caller's FX lookup.
    """
    q = text(
        """
        WITH latest AS (
          SELECT cs.broker_account_id, MAX(cs.report_date) AS report_date
          FROM portfolio_cash_balance_snapshots cs
          JOIN broker_accounts ba ON ba.id = cs.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE cs.report_date <= :anchor_date
            AND cs.authority_status = 'authoritative'
            AND ba.legacy_account_id IS NOT NULL
            AND ("""
        + account_scope_sql("acc")
        + """)
          GROUP BY cs.broker_account_id
        )
        SELECT
          ba.legacy_account_id AS account_id,
          cs.currency,
          CAST(cs.cash_balance AS DOUBLE PRECISION) AS balance_local,
          CAST(cs.cash_balance_base AS DOUBLE PRECISION) AS balance_base,
          CAST(cs.fx_rate_to_base AS DOUBLE PRECISION) AS fx_rate
        FROM portfolio_cash_balance_snapshots cs
        JOIN latest l
          ON l.broker_account_id = cs.broker_account_id
         AND l.report_date = cs.report_date
        JOIN broker_accounts ba ON ba.id = cs.broker_account_id
        WHERE cs.authority_status = 'authoritative'
        """
    )
    rows = db.execute(q, {"anchor_date": anchor_date, "current_user_id": current_user_id}).mappings().all()
    return [dict(r) for r in rows]


def get_data_completeness_status(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    """
    Return the latest completeness record per (broker_account, fact_scope)
    for all canonical accounts visible to this user.

    Incomplete scopes should be surfaced in dashboard responses as
    data-quality / completeness indicators rather than silently omitted.
    """
    q = text(
        """
        WITH latest AS (
          SELECT dc.broker_account_id, dc.fact_scope, MAX(dc.report_date) AS report_date
          FROM portfolio_data_completeness dc
          JOIN broker_accounts ba ON ba.id = dc.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE dc.report_date <= :anchor_date
            AND ("""
        + account_scope_sql("acc")
        + """)
          GROUP BY dc.broker_account_id, dc.fact_scope
        )
        SELECT
          ba.legacy_account_id AS account_id,
          COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
          dc.fact_scope,
          dc.completeness_status,
          dc.missing_reason,
          dc.report_date
        FROM portfolio_data_completeness dc
        JOIN latest l
          ON l.broker_account_id = dc.broker_account_id
         AND l.fact_scope = dc.fact_scope
         AND l.report_date = dc.report_date
        JOIN broker_accounts ba ON ba.id = dc.broker_account_id
        JOIN accounts acc ON acc.id = ba.legacy_account_id
        LEFT JOIN platforms pl ON pl.id = acc.platform_id
        WHERE dc.completeness_status <> 'complete'
        ORDER BY dc.fact_scope, acc.platform
        """
    )
    rows = db.execute(q, {"anchor_date": anchor_date, "current_user_id": current_user_id}).mappings().all()
    return [dict(r) for r in rows]
