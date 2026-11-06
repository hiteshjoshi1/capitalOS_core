"""Frozen copy of the canonical readers as they were before #231 (main 3e2e26b).

The parity oracle for the canonical read layer (#231, #130 10.2): the SQL below is
copied verbatim from ``app/portfolio/canonical_reads.py``, ``ibkr_flex.py``
(``latest_authoritative_nav_by_legacy_account``), ``valuation/facts.py`` and
``valuation/account_status.py`` (card statement balances) and
``market_data/service.py`` (held positions), with only the caching decorators
removed. ``tests/test_canonical_read_parity.py`` checks that the live readers,
now built from ``app/portfolio/effective_facts.py``, return exactly what these
return.

Do not "fix" anything here. When a reader's rule changes on purpose, change this
copy in the same PR and list the change (before/after) in the PR and the
decision log, so the parity test keeps pinning everything else.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.portfolio.account_open import account_open_sql
from app.portfolio.authority import FLEX_FACT_SCOPE, FLEX_SOURCE_KIND, authoritative_sql, window_covers_sql
from app.valuation.clock import _date_only

_IBKR_FLEX_SOURCE_KIND = FLEX_SOURCE_KIND
_IBKR_FLEX_FACT_SCOPE = FLEX_FACT_SCOPE


def _flex_authority_accounts_cte() -> str:
    """Body of the ``flex_authority_accounts`` CTE: (legacy account, broker account)
    pairs where IBKR Flex is the authority at :anchor_date (its window covers the
    anchor) and has written a fact that counts at or before it (#140).

    The window only routes the legacy account to its Flex broker account; whether
    a row counts is its authority_status (``authoritative_sql``)."""
    return (
        """
          SELECT ba.legacy_account_id AS account_id, ba.id AS broker_account_id
          FROM portfolio_source_authority_windows aw
          JOIN broker_accounts ba ON ba.id = aw.broker_account_id
          JOIN broker_connections bc ON bc.id = ba.connection_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE aw.source_kind = :ibkr_flex_source_kind
            AND aw.fact_scope = :ibkr_flex_fact_scope
            AND """
        + window_covers_sql("aw", ":anchor_date")
        + """
            AND ba.legacy_account_id IS NOT NULL
            AND bc.platform_code = 'IBKR'
            AND (
              EXISTS (
                SELECT 1 FROM portfolio_nav_snapshots ns
                WHERE ns.broker_account_id = ba.id
                  AND ns.report_date <= :anchor_date
                  AND """
        + authoritative_sql("ns")
        + """
              )
              OR EXISTS (
                SELECT 1 FROM portfolio_position_snapshots ps
                WHERE ps.broker_account_id = ba.id
                  AND ps.report_date <= :anchor_date
                  AND """
        + authoritative_sql("ps")
        + """
              )
              OR EXISTS (
                SELECT 1 FROM portfolio_cash_balance_snapshots cs
                WHERE cs.broker_account_id = ba.id
                  AND cs.report_date <= :anchor_date
                  AND """
        + authoritative_sql("cs")
        + """
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
        """
    )

def ref_positions(
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
        WITH flex_authority_accounts AS (""" + _flex_authority_accounts_cte() + """),
        nav_covered_accounts AS (
          SELECT DISTINCT ba.legacy_account_id AS account_id
          FROM portfolio_nav_snapshots ns
          JOIN broker_accounts ba ON ba.id = ns.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE ns.report_date <= :anchor_date
            AND """ + authoritative_sql("ns") + """
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
            AND """ + authoritative_sql("ps") + """
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
                    AND """ + authoritative_sql("ns") + """
                )
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
            AND """ + account_open_sql("acc") + """
          GROUP BY ba.legacy_account_id
        ),
        sym_asset AS (
          SELECT LOWER(symbol) AS sym, MIN(id) AS asset_id
          FROM assets
          WHERE symbol IS NOT NULL AND symbol <> ''
          GROUP BY LOWER(symbol)
        ),
        norm_sym_asset AS (
          SELECT LOWER(REPLACE(REPLACE(REPLACE(symbol, ' ', ''), '-', ''), '.', '')) AS norm_sym, MIN(id) AS asset_id
          FROM assets
          WHERE symbol IS NOT NULL AND symbol <> ''
          GROUP BY LOWER(REPLACE(REPLACE(REPLACE(symbol, ' ', ''), '-', ''), '.', ''))
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
          COALESCE(a.id, a_sym.id, a_norm.id)  AS asset_id,
          COALESCE(a.symbol, a_sym.symbol, a_norm.symbol, bi.symbol) AS symbol,
          COALESCE(a.name, a_sym.name, a_norm.name, bi.description, bi.symbol) AS name,
          CASE
            WHEN COALESCE(CAST(a.asset_class AS TEXT), CAST(a_sym.asset_class AS TEXT), CAST(a_norm.asset_class AS TEXT)) IS NOT NULL
              THEN COALESCE(CAST(a.asset_class AS TEXT), CAST(a_sym.asset_class AS TEXT), CAST(a_norm.asset_class AS TEXT))
            WHEN UPPER(COALESCE(bi.security_type, '')) IN ('STK', 'STOCK') THEN 'STOCK'
            WHEN UPPER(COALESCE(bi.security_type, '')) IN ('FUND', 'ETF', 'MF') THEN 'FUND'
            ELSE COALESCE(NULLIF(UPPER(bi.security_type), ''), 'STOCK')
          END AS asset_class,
          COALESCE(a.quote_currency, a_sym.quote_currency, a_norm.quote_currency, bi.currency) AS quote_currency,
          COALESCE(a.home_country, a_sym.home_country, a_norm.home_country) AS home_country,
          COALESCE(mx.exchange_code, mx_sym.exchange_code, mx_norm.exchange_code) AS exchange_code,
          COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
          COALESCE(pl_by_code.platform_type, pl.platform_type) AS platform_type,
          COALESCE(pl_by_code.country, pl.country, acc.country) AS platform_country,
          EXISTS (
            SELECT 1
            FROM portfolio_nav_snapshots ns
            WHERE ns.broker_account_id = ba.id
              AND ns.report_date <= :anchor_date
              AND """ + authoritative_sql("ns") + """
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
          -- The real cost basis (#130 2.7: this used to repeat market_value_base,
          -- so a holding without a market value fell back to 0, not to its cost).
          CAST(ps.cost_basis_base AS DOUBLE PRECISION) AS cost_basis_base,
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
        LEFT JOIN norm_sym_asset nsa ON nsa.norm_sym = LOWER(REPLACE(REPLACE(REPLACE(bi.symbol, ' ', ''), '-', ''), '.', ''))
        LEFT JOIN assets a_norm ON a_norm.id = nsa.asset_id AND bi.asset_id IS NULL AND a_sym.id IS NULL
        LEFT JOIN map_exchange mx ON mx.asset_id = a.id
        LEFT JOIN map_exchange mx_sym ON mx_sym.asset_id = a_sym.id AND bi.asset_id IS NULL
        LEFT JOIN map_exchange mx_norm ON mx_norm.asset_id = a_norm.id AND bi.asset_id IS NULL AND a_sym.id IS NULL
        WHERE """ + authoritative_sql("ps") + """
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
                    AND """ + authoritative_sql("ns") + """
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


def ref_balances(
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
                           (IBKR: the Flex base currency, ``account_base_currency``;
                           uploads store the statement amount here unconverted)
    - ``account_base_currency`` — the currency ``balance_base`` is in, for broker
                           cash rows (NULL for ``account_balance_snapshots`` rows)
    - ``broker_account_id`` — the broker account of a broker cash row (else NULL)
    - ``fx_rate``        — FX rate used for the conversion
    - ``source``         — 'account_balance_snapshots' | 'portfolio_cash_balance_snapshots'
    - ``as_of_date``     — the snapshot date (DATE string)

    Ordering: account_id ASC, as_of_date DESC, currency ASC.
    """
    q = text(
        """
        WITH
        flex_authority_accounts AS (""" + _flex_authority_accounts_cte() + """),

        -- 1. Latest authoritative rows from the new canonical table.
        abs_latest AS (
          SELECT
            abs.account_id,
            MAX(abs.as_of_date) AS as_of_date
          FROM account_balance_snapshots abs
          JOIN accounts acc ON acc.id = abs.account_id
          WHERE abs.as_of_date <= :anchor_date
            AND """ + authoritative_sql("abs") + """
            AND NOT EXISTS (
              SELECT 1
              FROM flex_authority_accounts faa
              WHERE faa.account_id = abs.account_id
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
            AND """ + account_open_sql("acc") + """
          GROUP BY abs.account_id
        ),
        abs_rows AS (
          SELECT
            abs.account_id,
            acc.currency AS account_currency,
            CAST(NULL AS INTEGER) AS broker_account_id,
            CAST(NULL AS TEXT) AS account_base_currency,
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
          WHERE """ + authoritative_sql("abs") + """
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
            AND """ + authoritative_sql("cs") + """
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
            AND """ + account_open_sql("acc") + """
          GROUP BY cs.broker_account_id
        ),
        pcbs_rows AS (
          SELECT
            ba.legacy_account_id AS account_id,
            acc.currency AS account_currency,
            ba.id AS broker_account_id,
            ba.base_currency AS account_base_currency,
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
          WHERE """ + authoritative_sql("cs") + """
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


def ref_coverage(
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
              AND """ + authoritative_sql("ps") + """
              AND ba.legacy_account_id IS NOT NULL
              AND (
                NOT EXISTS (
                  SELECT 1
                  FROM portfolio_nav_snapshots ns_account
                  JOIN broker_accounts ba_account ON ba_account.id = ns_account.broker_account_id
                  WHERE ba_account.legacy_account_id = ba.legacy_account_id
                    AND ns_account.report_date <= :anchor_date
                    AND """ + authoritative_sql("ns_account") + """
                )
                OR EXISTS (
                  SELECT 1
                  FROM portfolio_nav_snapshots ns_same_broker
                  WHERE ns_same_broker.broker_account_id = ba.id
                    AND ns_same_broker.report_date <= :anchor_date
                    AND """ + authoritative_sql("ns_same_broker") + """
                )
              )
              AND ("""
            + account_scope_sql("acc")
            + """)
              AND """ + account_open_sql("acc") + """
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
              AND """ + authoritative_sql("ns") + """
              AND ba.legacy_account_id IS NOT NULL
              AND ("""
            + account_scope_sql("acc")
            + """)
              AND """ + account_open_sql("acc") + """
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
              AND """ + authoritative_sql("abs") + """
              -- A card statement balance is a liability, not cash coverage (#207).
              AND abs.balance_type <> 'credit_balance'
              AND ("""
            + account_scope_sql("acc")
            + """)
              AND """ + account_open_sql("acc") + """
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
              AND """ + authoritative_sql("cs") + """
              AND ba.legacy_account_id IS NOT NULL
              AND ("""
            + account_scope_sql("acc")
            + """)
              AND """ + account_open_sql("acc") + """
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


def ref_completeness(
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
            AND """ + account_open_sql("acc") + """
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


# ─── app/portfolio/ibkr_flex.py: latest_authoritative_nav_by_legacy_account ──


def ref_nav(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            WITH latest AS (
              SELECT ns.broker_account_id, MAX(ns.report_date) AS report_date
              FROM portfolio_nav_snapshots ns
              JOIN broker_accounts ba ON ba.id = ns.broker_account_id
              JOIN accounts acc ON acc.id = ba.legacy_account_id
              WHERE ns.report_date <= :anchor_date
                AND {authoritative_sql("ns")}
                AND ba.legacy_account_id IS NOT NULL
                AND (acc.user_id = :current_user_id OR acc.user_id IS NULL)
                AND {account_open_sql("acc")}
              GROUP BY ns.broker_account_id
            )
            SELECT
              ba.legacy_account_id,
              ns.broker_account_id,
              ns.report_date,
              ns.base_currency,
              ns.cash_base,
              ns.stock_base,
              ns.total_nav_base,
              COALESCE(pl.code, acc.platform) AS platform,
              pl.platform_type AS platform_type,
              COALESCE(pl.country, acc.country) AS country
            FROM portfolio_nav_snapshots ns
            JOIN latest l ON l.broker_account_id = ns.broker_account_id AND l.report_date = ns.report_date
            JOIN broker_accounts ba ON ba.id = ns.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            LEFT JOIN platforms pl ON pl.id = acc.platform_id
            """
        ),
        {"anchor_date": anchor_date, "current_user_id": current_user_id},
    ).mappings().all()
    return [dict(row) for row in rows]


# ─── app/valuation/facts.py: _credit_card_liability_details (statement part) ──

CARD_STATEMENT_MAX_AGE_DAYS = 45


def ref_card_statements(db: Session, *, current_user_id: int, anchor_date: date, base_currency: str = "SGD") -> Dict[int, tuple[date, list[tuple[str, float]]]]:
    """Per card: (newest statement date, [(currency, balance_local)]), exactly as
    _credit_card_liability_details derived them."""
    statement_rows = db.execute(
        text(
            """
            SELECT abs.account_id, abs.as_of_date, abs.currency, abs.balance_local
            FROM account_balance_snapshots abs
            JOIN accounts a ON a.id = abs.account_id
            WHERE a.account_type = 'CREDIT_CARD'
              AND abs.balance_type = 'credit_balance'
              AND """
            + authoritative_sql("abs")
            + """
              AND abs.as_of_date <= :anchor_date
              AND abs.as_of_date >= :oldest
              AND """
            + account_open_sql("a")
            + """
              AND """
            + account_scope_sql("a")
        ),
        {
            "anchor_date": anchor_date,
            "oldest": anchor_date - timedelta(days=CARD_STATEMENT_MAX_AGE_DAYS),
            "current_user_id": current_user_id,
        },
    ).mappings().all()
    newest_statement: dict[int, date] = {}
    for row in statement_rows:
        as_of = _date_only(row["as_of_date"])
        if as_of is None:
            continue
        account_id = int(row["account_id"])
        if account_id not in newest_statement or as_of > newest_statement[account_id]:
            newest_statement[account_id] = as_of
    statement_balances: dict[int, list[tuple[str, float]]] = {}
    for row in statement_rows:
        account_id = int(row["account_id"])
        if _date_only(row["as_of_date"]) == newest_statement.get(account_id):
            statement_balances.setdefault(account_id, []).append(
                (str(row["currency"] or base_currency).upper(), float(row["balance_local"] or 0.0))
            )
    return {account_id: (newest_statement[account_id], balances) for account_id, balances in statement_balances.items()}


# ─── app/valuation/account_status.py: _card_statement_dates ──────────────────


def ref_card_statement_dates(db: Session, anchor_date: date, current_user_id: int) -> Dict[int, date]:
    rows = db.execute(
        text(
            """
            SELECT abs.account_id, MAX(abs.as_of_date) AS as_of_date
            FROM account_balance_snapshots abs
            JOIN accounts a ON a.id = abs.account_id
            WHERE a.account_type = 'CREDIT_CARD'
              AND abs.balance_type = 'credit_balance'
              AND """
            + authoritative_sql("abs")
            + """
              AND abs.as_of_date <= :anchor_date
              AND abs.as_of_date >= :oldest
              AND """
            + account_open_sql("a")
            + """
              AND """
            + account_scope_sql("a")
            + """
            GROUP BY abs.account_id
            """
        ),
        {
            "anchor_date": anchor_date,
            "oldest": anchor_date - timedelta(days=CARD_STATEMENT_MAX_AGE_DAYS),
            "current_user_id": current_user_id,
        },
    ).mappings().all()
    out: Dict[int, date] = {}
    for row in rows:
        as_of = _date_only(row["as_of_date"])
        if as_of is not None:
            out[int(row["account_id"])] = as_of
    return out


# ─── app/market_data/service.py: unpriced_held_positions (the SQL part) ──────

_PRICEABLE_SECURITY_TYPES = ("STK", "STOCK", "FUND", "ETF", "MF")


def ref_held_positions(db: Session, *, today: date, user_id: int | None) -> list[dict[str, Any]]:
    scope = ""
    params: dict[str, Any] = {
        "today": today,
        **{f"st{i}": t for i, t in enumerate(_PRICEABLE_SECURITY_TYPES)},
    }
    if user_id is not None:
        scope = "AND " + account_scope_sql("acc")
        params["current_user_id"] = user_id
    security_types = ",".join(f":st{i}" for i in range(len(_PRICEABLE_SECURITY_TYPES)))
    rows = db.execute(
        text(
            f"""
            WITH latest AS (
              SELECT ps.broker_account_id, MAX(ps.report_date) AS report_date
              FROM portfolio_position_snapshots ps
              WHERE ps.authority_status = 'authoritative'
                AND ps.report_date <= :today
              GROUP BY ps.broker_account_id
            )
            SELECT DISTINCT
              bi.id AS instrument_id,
              bi.asset_id,
              COALESCE(a.symbol, bi.symbol) AS symbol,
              COALESCE(a.name, bi.description, bi.symbol) AS name,
              COALESCE(a.quote_currency, bi.currency) AS currency,
              COALESCE(a.home_country, bi.country) AS country,
              bi.platform_code
            FROM portfolio_position_snapshots ps
            JOIN latest l
              ON l.broker_account_id = ps.broker_account_id AND l.report_date = ps.report_date
            JOIN broker_accounts ba ON ba.id = ps.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            JOIN broker_instruments bi ON bi.id = ps.broker_instrument_id
            LEFT JOIN assets a ON a.id = bi.asset_id
            WHERE ps.authority_status = 'authoritative'
              AND ps.quantity IS NOT NULL
              AND CAST(ps.quantity AS DOUBLE PRECISION) <> 0
              AND (acc.closed_on IS NULL OR acc.closed_on >= :today)
              AND (
                CAST(a.asset_class AS TEXT) IN ('STOCK', 'FUND')
                OR (a.id IS NULL AND UPPER(COALESCE(bi.security_type, '')) IN ({security_types}))
              )
              {scope}
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]
