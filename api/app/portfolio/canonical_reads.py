"""
Canonical portfolio read services for Phase 3/4 dashboard migration.

Provides read-path functions that source facts from the canonical portfolio
tables (portfolio_position_snapshots, portfolio_cash_balance_snapshots,
portfolio_data_completeness, account_balance_snapshots) instead of the legacy
positions / transactions tables.

Design rules:
- IBKR Flex accounts are covered by NAV snapshots (latest_authoritative_nav_by_legacy_account).
  Position and cash reads here EXCLUDE those accounts to avoid double-counting.
- Sharekhan / DBS Vickers accounts have canonical position snapshots written by
  the upload adapter (Phase 2).  These are the primary targets for Phase 3.
- If broker_instruments.asset_id is set, asset metadata is pulled from assets.
  Otherwise a symbol-based fallback lookup is attempted so that geography and
  platform allocation remain equivalent to legacy reads.

Phase 4 additions:
- account_balance_snapshots is the new canonical table for non-security cash
  balances (bank cash, broker cash, stablecoin cash, etc.).
- canonical_account_balance_rows() returns one normalized shape that surfaces
  both account_balance_snapshots rows and any portfolio_cash_balance_snapshots
  rows that have NOT yet been promoted, so dashboard/net-worth callers can read
  from a single abstraction without knowing the source.
- Future adapters writing cash facts MUST write to account_balance_snapshots,
  not to positions(asset_class='CASH').
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql

_IBKR_FLEX_SOURCE_KIND = "ibkr_flex_daily"
_IBKR_FLEX_FACT_SCOPE = "all"

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

    Returned dicts use the dashboard's canonical position shape so callers do
    not need to hand-write SQL against portfolio_position_snapshots.
    """
    q = text(
        """
        WITH flex_authority_accounts AS (
          SELECT ba.legacy_account_id AS account_id, ba.id AS broker_account_id
          FROM portfolio_source_authority_windows aw
          JOIN broker_accounts ba ON ba.id = aw.broker_account_id
          JOIN broker_connections bc ON bc.id = ba.connection_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE aw.source_kind = :ibkr_flex_source_kind
            AND aw.fact_scope = :ibkr_flex_fact_scope
            AND aw.authority_status = 'authoritative'
            AND aw.effective_from <= :anchor_date
            AND (aw.effective_to IS NULL OR aw.effective_to >= :anchor_date)
            AND ba.legacy_account_id IS NOT NULL
            AND bc.platform_code = 'IBKR'
            AND (
              EXISTS (
                SELECT 1
                FROM portfolio_nav_snapshots ns
                WHERE ns.broker_account_id = ba.id
                  AND ns.report_date <= :anchor_date
                  AND (
                    ns.authority_status = 'authoritative'
                    OR (
                      aw.effective_from <= ns.report_date
                      AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
                    )
                  )
              )
              OR EXISTS (
                SELECT 1
                FROM portfolio_position_snapshots ps
                WHERE ps.broker_account_id = ba.id
                  AND ps.report_date <= :anchor_date
                  AND (
                    ps.authority_status = 'authoritative'
                    OR (
                      aw.effective_from <= ps.report_date
                      AND (aw.effective_to IS NULL OR aw.effective_to >= ps.report_date)
                    )
                  )
              )
              OR EXISTS (
                SELECT 1
                FROM portfolio_cash_balance_snapshots cs
                WHERE cs.broker_account_id = ba.id
                  AND cs.report_date <= :anchor_date
                  AND (
                    cs.authority_status = 'authoritative'
                    OR (
                      aw.effective_from <= cs.report_date
                      AND (aw.effective_to IS NULL OR aw.effective_to >= cs.report_date)
                    )
                  )
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
        ),
        nav_covered_accounts AS (
          SELECT DISTINCT ba.legacy_account_id AS account_id
          FROM portfolio_nav_snapshots ns
          JOIN broker_accounts ba ON ba.id = ns.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE ns.report_date <= :anchor_date
            AND (
              ns.authority_status = 'authoritative'
              OR EXISTS (
                SELECT 1
                FROM portfolio_source_authority_windows aw
                WHERE aw.broker_account_id = ns.broker_account_id
                  AND aw.source_kind = :ibkr_flex_source_kind
                  AND aw.fact_scope = :ibkr_flex_fact_scope
                  AND aw.authority_status = 'authoritative'
                  AND aw.effective_from <= ns.report_date
                  AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
              )
            )
            AND ba.legacy_account_id IS NOT NULL
            AND ("""
        + account_scope_sql("acc")
        + """)
        ),
        latest_canonical AS (
          SELECT ba.legacy_account_id AS account_id, MAX(ps.report_date) AS report_date
          FROM portfolio_position_snapshots ps
          JOIN broker_accounts ba ON ba.id = ps.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE ps.report_date <= :anchor_date
            AND (
              ps.authority_status = 'authoritative'
              OR EXISTS (
                SELECT 1
                FROM portfolio_source_authority_windows aw
                WHERE aw.broker_account_id = ps.broker_account_id
                  AND aw.source_kind = :ibkr_flex_source_kind
                  AND aw.fact_scope = :ibkr_flex_fact_scope
                  AND aw.authority_status = 'authoritative'
                  AND aw.effective_from <= ps.report_date
                  AND (aw.effective_to IS NULL OR aw.effective_to >= ps.report_date)
              )
            )
            AND ba.legacy_account_id IS NOT NULL
            AND (
              NOT EXISTS (
                SELECT 1
                FROM flex_authority_accounts faa
                WHERE faa.account_id = ba.legacy_account_id
              )
              OR EXISTS (
                SELECT 1
                FROM flex_authority_accounts faa
                WHERE faa.account_id = ba.legacy_account_id
                  AND faa.broker_account_id = ba.id
              )
            )
            AND (
              NOT EXISTS (
                SELECT 1
                FROM nav_covered_accounts nca
                WHERE nca.account_id = ba.legacy_account_id
              )
              OR (
                :include_nav_accounts
                AND EXISTS (
                  SELECT 1
                  FROM portfolio_nav_snapshots ns
                  WHERE ns.broker_account_id = ba.id
                    AND ns.report_date <= :anchor_date
                    AND (
                      ns.authority_status = 'authoritative'
                      OR EXISTS (
                        SELECT 1
                        FROM portfolio_source_authority_windows aw
                        WHERE aw.broker_account_id = ns.broker_account_id
                          AND aw.source_kind = :ibkr_flex_source_kind
                          AND aw.fact_scope = :ibkr_flex_fact_scope
                          AND aw.authority_status = 'authoritative'
                          AND aw.effective_from <= ns.report_date
                          AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
                      )
                    )
                )
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
          GROUP BY ba.legacy_account_id
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
          ba.base_currency AS account_base_currency,
          acc.currency AS account_currency,
          COALESCE(a.id, a_sym.id)  AS asset_id,
          bi.symbol                  AS symbol,
          COALESCE(a.name, a_sym.name, bi.description, bi.symbol) AS name,
          COALESCE(CAST(a.asset_class AS TEXT), CAST(a_sym.asset_class AS TEXT), bi.security_type, 'STOCK') AS asset_class,
          COALESCE(a.quote_currency, a_sym.quote_currency, bi.currency) AS quote_currency,
          COALESCE(a.home_country, a_sym.home_country) AS home_country,
          COALESCE(mx.exchange_code, mx_sym.exchange_code) AS exchange_code,
          COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
          COALESCE(pl_by_code.platform_type, pl.platform_type) AS platform_type,
          COALESCE(pl_by_code.country, pl.country, acc.country) AS platform_country,
          EXISTS (
            SELECT 1
            FROM portfolio_nav_snapshots ns
            WHERE ns.broker_account_id = ba.id
              AND ns.report_date <= :anchor_date
              AND (
                ns.authority_status = 'authoritative'
                OR EXISTS (
                  SELECT 1
                  FROM portfolio_source_authority_windows aw
                  WHERE aw.broker_account_id = ns.broker_account_id
                    AND aw.source_kind = :ibkr_flex_source_kind
                    AND aw.fact_scope = :ibkr_flex_fact_scope
                    AND aw.authority_status = 'authoritative'
                    AND aw.effective_from <= ns.report_date
                    AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
                )
              )
          ) AS has_nav_snapshot,
          ps.report_date AS report_date,
          CAST(ps.quantity AS DOUBLE PRECISION) AS quantity,
          CASE
            WHEN ps.quantity IS NOT NULL
             AND CAST(ps.quantity AS DOUBLE PRECISION) != 0
             AND ps.cost_basis_local IS NOT NULL
              THEN CAST(ps.cost_basis_local AS DOUBLE PRECISION) / CAST(ps.quantity AS DOUBLE PRECISION)
            WHEN ps.quantity IS NOT NULL
             AND CAST(ps.quantity AS DOUBLE PRECISION) != 0
             AND ps.cost_basis_base IS NOT NULL
              THEN CAST(ps.cost_basis_base AS DOUBLE PRECISION) / CAST(ps.quantity AS DOUBLE PRECISION)
            ELSE NULL
          END AS avg_cost,
          CAST(ps.market_value_base AS DOUBLE PRECISION) AS cost_basis_base,
          CAST(ps.market_price AS DOUBLE PRECISION) AS snapshot_market_price,
          CAST(ps.market_value_local AS DOUBLE PRECISION) AS snapshot_market_value_local,
          CAST(ps.market_value_base AS DOUBLE PRECISION) AS snapshot_market_value_base,
          CAST(ps.cost_basis_local AS DOUBLE PRECISION) AS snapshot_cost_basis_local,
          CAST(ps.cost_basis_base AS DOUBLE PRECISION) AS snapshot_cost_basis_base
        FROM portfolio_position_snapshots ps
        JOIN latest_canonical lc
          ON lc.report_date = ps.report_date
        JOIN broker_accounts ba ON ba.id = ps.broker_account_id
         AND ba.legacy_account_id = lc.account_id
        JOIN accounts acc ON acc.id = ba.legacy_account_id
        LEFT JOIN platforms pl ON pl.id = acc.platform_id
        LEFT JOIN platforms pl_by_code ON pl_by_code.code = acc.platform
        JOIN broker_instruments bi ON bi.id = ps.broker_instrument_id
        LEFT JOIN assets a ON a.id = bi.asset_id
        LEFT JOIN sym_asset sa ON sa.sym = LOWER(bi.symbol)
        LEFT JOIN assets a_sym ON a_sym.id = sa.asset_id AND bi.asset_id IS NULL
        LEFT JOIN map_exchange mx ON mx.asset_id = a.id
        LEFT JOIN map_exchange mx_sym ON mx_sym.asset_id = a_sym.id AND bi.asset_id IS NULL
        WHERE (
            ps.authority_status = 'authoritative'
            OR EXISTS (
              SELECT 1
              FROM portfolio_source_authority_windows aw
              WHERE aw.broker_account_id = ps.broker_account_id
                AND aw.source_kind = :ibkr_flex_source_kind
                AND aw.fact_scope = :ibkr_flex_fact_scope
                AND aw.authority_status = 'authoritative'
                AND aw.effective_from <= ps.report_date
                AND (aw.effective_to IS NULL OR aw.effective_to >= ps.report_date)
            )
          )
          AND (
            NOT EXISTS (
              SELECT 1
              FROM flex_authority_accounts faa
              WHERE faa.account_id = ba.legacy_account_id
            )
            OR EXISTS (
              SELECT 1
              FROM flex_authority_accounts faa
              WHERE faa.account_id = ba.legacy_account_id
                AND faa.broker_account_id = ba.id
            )
          )
          AND (
            NOT EXISTS (
              SELECT 1
              FROM nav_covered_accounts nca
              WHERE nca.account_id = ba.legacy_account_id
            )
            OR (
              :include_nav_accounts
              AND EXISTS (
                SELECT 1
                FROM portfolio_nav_snapshots ns
                  WHERE ns.broker_account_id = ba.id
                    AND ns.report_date <= :anchor_date
                    AND (
                      ns.authority_status = 'authoritative'
                      OR EXISTS (
                        SELECT 1
                        FROM portfolio_source_authority_windows aw
                        WHERE aw.broker_account_id = ns.broker_account_id
                          AND aw.source_kind = :ibkr_flex_source_kind
                          AND aw.fact_scope = :ibkr_flex_fact_scope
                          AND aw.authority_status = 'authoritative'
                          AND aw.effective_from <= ns.report_date
                          AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
                      )
                    )
              )
            )
          )
        """
    )
    rows = db.execute(
        q,
        {
            "anchor_date": anchor_date,
            "current_user_id": current_user_id,
            "include_nav_accounts": include_nav_accounts,
            "ibkr_flex_source_kind": _IBKR_FLEX_SOURCE_KIND,
            "ibkr_flex_fact_scope": _IBKR_FLEX_FACT_SCOPE,
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
            AND (
              cs.authority_status = 'authoritative'
              OR EXISTS (
                SELECT 1
                FROM portfolio_source_authority_windows aw
                WHERE aw.broker_account_id = cs.broker_account_id
                  AND aw.source_kind = :ibkr_flex_source_kind
                  AND aw.fact_scope = :ibkr_flex_fact_scope
                  AND aw.authority_status = 'authoritative'
                  AND aw.effective_from <= cs.report_date
                  AND (aw.effective_to IS NULL OR aw.effective_to >= cs.report_date)
              )
            )
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


def canonical_account_balance_rows(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    """
    Return normalized cash/balance dicts for all accounts visible to this user.

    **Phase 4 canonical cash read abstraction.**

    Merges two source tables into one uniform shape so that dashboard and
    net-worth callers do not need to know where a balance originated:

    1. ``account_balance_snapshots`` — new canonical table; preferred source for
       any account that has rows here.
    2. ``portfolio_cash_balance_snapshots`` — broker-specific detail written by
       IBKR Flex (Phase 1).  Rows from this table are surfaced for accounts
       that do NOT already have a matching authoritative row in
       ``account_balance_snapshots`` for the same (account, date), preventing
       double-counting.

    Each returned dict has the keys:
    - ``account_id``     — legacy accounts.id
    - ``currency``       — ISO-4217 currency code
    - ``balance_type``   — one of: cash | broker_cash | bank_cash |
                           credit_balance | loan_balance | stablecoin_cash
    - ``balance_local``  — balance in the position currency
    - ``balance_base``   — balance converted to the account's base currency
    - ``fx_rate``        — FX rate used for the conversion
    - ``source``         — 'account_balance_snapshots' | 'portfolio_cash_balance_snapshots'
    - ``as_of_date``     — the snapshot date (DATE string)

    Ordering: account_id ASC, as_of_date DESC, currency ASC.
    """
    q = text(
        """
        WITH
        flex_authority_accounts AS (
          SELECT ba.legacy_account_id AS account_id, ba.id AS broker_account_id
          FROM portfolio_source_authority_windows aw
          JOIN broker_accounts ba ON ba.id = aw.broker_account_id
          JOIN broker_connections bc ON bc.id = ba.connection_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE aw.source_kind = :ibkr_flex_source_kind
            AND aw.fact_scope = :ibkr_flex_fact_scope
            AND aw.authority_status = 'authoritative'
            AND aw.effective_from <= :anchor_date
            AND (aw.effective_to IS NULL OR aw.effective_to >= :anchor_date)
            AND ba.legacy_account_id IS NOT NULL
            AND bc.platform_code = 'IBKR'
            AND (
              EXISTS (
                SELECT 1
                FROM portfolio_nav_snapshots ns
                WHERE ns.broker_account_id = ba.id
                  AND ns.report_date <= :anchor_date
                  AND (
                    ns.authority_status = 'authoritative'
                    OR (
                      aw.effective_from <= ns.report_date
                      AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
                    )
                  )
              )
              OR EXISTS (
                SELECT 1
                FROM portfolio_position_snapshots ps
                WHERE ps.broker_account_id = ba.id
                  AND ps.report_date <= :anchor_date
                  AND (
                    ps.authority_status = 'authoritative'
                    OR (
                      aw.effective_from <= ps.report_date
                      AND (aw.effective_to IS NULL OR aw.effective_to >= ps.report_date)
                    )
                  )
              )
              OR EXISTS (
                SELECT 1
                FROM portfolio_cash_balance_snapshots cs
                WHERE cs.broker_account_id = ba.id
                  AND cs.report_date <= :anchor_date
                  AND (
                    cs.authority_status = 'authoritative'
                    OR (
                      aw.effective_from <= cs.report_date
                      AND (aw.effective_to IS NULL OR aw.effective_to >= cs.report_date)
                    )
                  )
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
        ),

        -- 1. Latest authoritative rows from the new canonical table.
        abs_latest AS (
          SELECT
            abs.account_id,
            MAX(abs.as_of_date) AS as_of_date
          FROM account_balance_snapshots abs
          JOIN accounts acc ON acc.id = abs.account_id
          WHERE abs.as_of_date <= :anchor_date
            AND abs.authority_status = 'authoritative'
            AND NOT EXISTS (
              SELECT 1
              FROM flex_authority_accounts faa
              WHERE faa.account_id = abs.account_id
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
          GROUP BY abs.account_id
        ),
        abs_rows AS (
          SELECT
            abs.account_id,
            acc.currency AS account_currency,
            COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
            COALESCE(pl_by_code.platform_type, pl.platform_type) AS platform_type,
            COALESCE(pl_by_code.country, pl.country, acc.country) AS platform_country,
            abs.currency,
            abs.balance_type,
            CAST(abs.balance_local AS DOUBLE PRECISION) AS balance_local,
            CAST(abs.balance_base  AS DOUBLE PRECISION) AS balance_base,
            CAST(abs.fx_rate_to_base AS DOUBLE PRECISION) AS fx_rate,
            'account_balance_snapshots' AS source,
            CAST(abs.as_of_date AS TEXT) AS as_of_date
          FROM account_balance_snapshots abs
          JOIN accounts acc ON acc.id = abs.account_id
          LEFT JOIN platforms pl ON pl.id = acc.platform_id
          LEFT JOIN platforms pl_by_code ON pl_by_code.code = acc.platform
          JOIN abs_latest al
            ON al.account_id = abs.account_id
           AND al.as_of_date = abs.as_of_date
          WHERE abs.authority_status = 'authoritative'
        ),

        -- 2. Accounts already covered by the new canonical table.
        abs_covered_accounts AS (
          SELECT DISTINCT account_id FROM abs_rows
        ),

        -- 3. Latest authoritative portfolio_cash_balance_snapshots for accounts
        --    NOT yet covered by account_balance_snapshots.
        pcbs_latest AS (
          SELECT
            cs.broker_account_id,
            MAX(cs.report_date) AS report_date
          FROM portfolio_cash_balance_snapshots cs
          JOIN broker_accounts ba ON ba.id = cs.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE cs.report_date <= :anchor_date
            AND (
              cs.authority_status = 'authoritative'
              OR EXISTS (
                SELECT 1
                FROM portfolio_source_authority_windows aw
                WHERE aw.broker_account_id = cs.broker_account_id
                  AND aw.source_kind = :ibkr_flex_source_kind
                  AND aw.fact_scope = :ibkr_flex_fact_scope
                  AND aw.authority_status = 'authoritative'
                  AND aw.effective_from <= cs.report_date
                  AND (aw.effective_to IS NULL OR aw.effective_to >= cs.report_date)
              )
            )
            AND ba.legacy_account_id IS NOT NULL
            AND ba.legacy_account_id NOT IN (SELECT account_id FROM abs_covered_accounts)
            AND (
              NOT EXISTS (
                SELECT 1
                FROM flex_authority_accounts faa
                WHERE faa.account_id = ba.legacy_account_id
              )
              OR EXISTS (
                SELECT 1
                FROM flex_authority_accounts faa
                WHERE faa.account_id = ba.legacy_account_id
                  AND faa.broker_account_id = ba.id
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
          GROUP BY cs.broker_account_id
        ),
        pcbs_rows AS (
          SELECT
            ba.legacy_account_id AS account_id,
            acc.currency AS account_currency,
            COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
            COALESCE(pl_by_code.platform_type, pl.platform_type) AS platform_type,
            COALESCE(pl_by_code.country, pl.country, acc.country) AS platform_country,
            cs.currency,
            'broker_cash' AS balance_type,
            CAST(cs.cash_balance      AS DOUBLE PRECISION) AS balance_local,
            CAST(cs.cash_balance_base AS DOUBLE PRECISION) AS balance_base,
            CAST(cs.fx_rate_to_base   AS DOUBLE PRECISION) AS fx_rate,
            'portfolio_cash_balance_snapshots' AS source,
            CAST(cs.report_date AS TEXT) AS as_of_date
          FROM portfolio_cash_balance_snapshots cs
          JOIN pcbs_latest pcl
            ON pcl.broker_account_id = cs.broker_account_id
           AND pcl.report_date = cs.report_date
          JOIN broker_accounts ba ON ba.id = cs.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          LEFT JOIN platforms pl ON pl.id = acc.platform_id
          LEFT JOIN platforms pl_by_code ON pl_by_code.code = acc.platform
          WHERE (
              cs.authority_status = 'authoritative'
              OR EXISTS (
                SELECT 1
                FROM portfolio_source_authority_windows aw
                WHERE aw.broker_account_id = cs.broker_account_id
                  AND aw.source_kind = :ibkr_flex_source_kind
                  AND aw.fact_scope = :ibkr_flex_fact_scope
                  AND aw.authority_status = 'authoritative'
                  AND aw.effective_from <= cs.report_date
                  AND (aw.effective_to IS NULL OR aw.effective_to >= cs.report_date)
              )
            )
        )

        SELECT * FROM abs_rows
        UNION ALL
        SELECT * FROM pcbs_rows
        ORDER BY account_id ASC, as_of_date DESC, currency ASC
        """
    )
    rows = db.execute(
        q,
        {
            "anchor_date": anchor_date,
            "current_user_id": current_user_id,
            "ibkr_flex_source_kind": _IBKR_FLEX_SOURCE_KIND,
            "ibkr_flex_fact_scope": _IBKR_FLEX_FACT_SCOPE,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def canonical_snapshot_coverage_as_of(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
    include_positions: bool = True,
    include_nav: bool = True,
    include_cash: bool = True,
) -> date | None:
    """
    Return the effective canonical snapshot date at/before ``anchor_date``.

    This mirrors the old dashboard snapshot semantics from legacy
    ``positions``: if the dashboard can compute a boundary view from latest
    known component facts, the effective as-of date is the latest canonical
    fact date available at or before the boundary. Individual component
    staleness is exposed separately as freshness metadata; it should not make
    the whole net-worth snapshot disappear.
    """
    selected: list[str] = []
    if include_positions:
        selected.append(
            """
            SELECT ba.legacy_account_id AS account_id, MAX(ps.report_date) AS as_of_date
            FROM portfolio_position_snapshots ps
            JOIN broker_accounts ba ON ba.id = ps.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE ps.report_date <= :anchor_date
              AND (
                ps.authority_status = 'authoritative'
                OR EXISTS (
                  SELECT 1
                  FROM portfolio_source_authority_windows aw
                  WHERE aw.broker_account_id = ps.broker_account_id
                    AND aw.source_kind = :ibkr_flex_source_kind
                    AND aw.fact_scope = :ibkr_flex_fact_scope
                    AND aw.authority_status = 'authoritative'
                    AND aw.effective_from <= ps.report_date
                    AND (aw.effective_to IS NULL OR aw.effective_to >= ps.report_date)
                )
              )
              AND ba.legacy_account_id IS NOT NULL
              AND (
                NOT EXISTS (
                  SELECT 1
                  FROM portfolio_nav_snapshots ns_account
                  JOIN broker_accounts ba_account ON ba_account.id = ns_account.broker_account_id
                  WHERE ba_account.legacy_account_id = ba.legacy_account_id
                    AND ns_account.report_date <= :anchor_date
                    AND (
                      ns_account.authority_status = 'authoritative'
                      OR EXISTS (
                        SELECT 1
                        FROM portfolio_source_authority_windows aw
                        WHERE aw.broker_account_id = ns_account.broker_account_id
                          AND aw.source_kind = :ibkr_flex_source_kind
                          AND aw.fact_scope = :ibkr_flex_fact_scope
                          AND aw.authority_status = 'authoritative'
                          AND aw.effective_from <= ns_account.report_date
                          AND (aw.effective_to IS NULL OR aw.effective_to >= ns_account.report_date)
                      )
                    )
                )
                OR EXISTS (
                  SELECT 1
                  FROM portfolio_nav_snapshots ns_same_broker
                  WHERE ns_same_broker.broker_account_id = ba.id
                    AND ns_same_broker.report_date <= :anchor_date
                    AND (
                      ns_same_broker.authority_status = 'authoritative'
                      OR EXISTS (
                        SELECT 1
                        FROM portfolio_source_authority_windows aw
                        WHERE aw.broker_account_id = ns_same_broker.broker_account_id
                          AND aw.source_kind = :ibkr_flex_source_kind
                          AND aw.fact_scope = :ibkr_flex_fact_scope
                          AND aw.authority_status = 'authoritative'
                          AND aw.effective_from <= ns_same_broker.report_date
                          AND (aw.effective_to IS NULL OR aw.effective_to >= ns_same_broker.report_date)
                      )
                    )
                )
              )
              AND ("""
            + account_scope_sql("acc")
            + """)
            GROUP BY ba.legacy_account_id
            """
        )
    if include_nav:
        selected.append(
            """
            SELECT ba.legacy_account_id AS account_id, MAX(ns.report_date) AS as_of_date
            FROM portfolio_nav_snapshots ns
            JOIN broker_accounts ba ON ba.id = ns.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE ns.report_date <= :anchor_date
              AND (
                ns.authority_status = 'authoritative'
                OR EXISTS (
                  SELECT 1
                  FROM portfolio_source_authority_windows aw
                  WHERE aw.broker_account_id = ns.broker_account_id
                    AND aw.source_kind = :ibkr_flex_source_kind
                    AND aw.fact_scope = :ibkr_flex_fact_scope
                    AND aw.authority_status = 'authoritative'
                    AND aw.effective_from <= ns.report_date
                    AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
                )
              )
              AND ba.legacy_account_id IS NOT NULL
              AND ("""
            + account_scope_sql("acc")
            + """)
            GROUP BY ba.legacy_account_id
            """
        )
    if include_cash:
        selected.append(
            """
            SELECT abs.account_id AS account_id, MAX(abs.as_of_date) AS as_of_date
            FROM account_balance_snapshots abs
            JOIN accounts acc ON acc.id = abs.account_id
            WHERE abs.as_of_date <= :anchor_date
              AND abs.authority_status = 'authoritative'
              AND ("""
            + account_scope_sql("acc")
            + """)
            GROUP BY abs.account_id
            """
        )
        selected.append(
            """
            SELECT ba.legacy_account_id AS account_id, MAX(cs.report_date) AS as_of_date
            FROM portfolio_cash_balance_snapshots cs
            JOIN broker_accounts ba ON ba.id = cs.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE cs.report_date <= :anchor_date
              AND (
                cs.authority_status = 'authoritative'
                OR EXISTS (
                  SELECT 1
                  FROM portfolio_source_authority_windows aw
                  WHERE aw.broker_account_id = cs.broker_account_id
                    AND aw.source_kind = :ibkr_flex_source_kind
                    AND aw.fact_scope = :ibkr_flex_fact_scope
                    AND aw.authority_status = 'authoritative'
                    AND aw.effective_from <= cs.report_date
                    AND (aw.effective_to IS NULL OR aw.effective_to >= cs.report_date)
                )
              )
              AND ba.legacy_account_id IS NOT NULL
              AND ("""
            + account_scope_sql("acc")
            + """)
            GROUP BY ba.legacy_account_id
            """
        )
    if not selected:
        return None
    q = text(
        """
        WITH latest AS (
        """
        + "\nUNION ALL\n".join(selected)
        + """
        )
        SELECT MAX(as_of_date) AS as_of_date
        FROM latest
        """
    )
    row = db.execute(
        q,
        {
            "anchor_date": anchor_date,
            "current_user_id": current_user_id,
            "ibkr_flex_source_kind": _IBKR_FLEX_SOURCE_KIND,
            "ibkr_flex_fact_scope": _IBKR_FLEX_FACT_SCOPE,
        },
    ).mappings().one()
    return row["as_of_date"]


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
