"""
Canonical portfolio read services: the readers every page values accounts with.

Each reader is a thin select over ``app.portfolio.effective_facts`` (#231, #130
10.2), which defines once which fact rows count at an anchor: authority, owner
and open account, latest per account, carry-forward, Flex routing and NAV
coverage. A reader adds only its own columns and joins (platforms, assets).

- IBKR Flex accounts are valued by their NAV (``latest_authoritative_nav_by_legacy_account``);
  position reads exclude them unless a detail view opts in (``include_nav_accounts``).
- Sharekhan / DBS Vickers accounts have canonical position snapshots written by
  the upload adapter.
- If broker_instruments.asset_id is set, asset metadata is pulled from assets.
  Otherwise a symbol-based fallback lookup is attempted so that geography and
  platform allocation remain equivalent to legacy reads.
- account_balance_snapshots is the canonical table for non-security cash
  balances (bank cash, broker cash, stablecoin cash, card statement balances).
  canonical_account_balance_rows() returns one normalized shape over it and any
  portfolio_cash_balance_snapshots rows not covered by it.
- Future adapters writing cash facts MUST write to account_balance_snapshots,
  not to positions(asset_class='CASH').
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio import effective_facts as ef
from app.portfolio.effective_facts import CARD_STATEMENT_MAX_AGE_DAYS
from app.valuation_cache import valuation_cached


@valuation_cached(shared=True)
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
        WITH flex_authority_accounts AS (""" + ef.flex_authority_accounts_cte() + """),
        effective_positions AS (""" + ef.effective_positions_sql() + """),
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
          """ + ef.has_nav_sql("ba") + """ AS has_nav_snapshot,
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
        FROM effective_positions ps
        JOIN broker_accounts ba ON ba.id = ps.broker_account_id
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
        """
    )
    rows = db.execute(
        q,
        {
            "anchor_date": anchor_date,
            "current_user_id": current_user_id,
            "include_nav_accounts": include_nav_accounts,
            **ef.flex_binds(),
        },
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["has_nav_snapshot"] = bool(item.get("has_nav_snapshot"))
        out.append(item)
    return out


@valuation_cached(shared=True)
def latest_authoritative_nav_by_legacy_account(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    """Each broker account's NAV at the anchor (``effective_nav_sql``), with its
    legacy account and platform. (Also importable from ``app.portfolio.ibkr_flex``,
    where it used to live.)"""
    rows = db.execute(
        text(
            """
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
            FROM ("""
            + ef.effective_nav_sql()
            + """) ns
            JOIN broker_accounts ba ON ba.id = ns.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            LEFT JOIN platforms pl ON pl.id = acc.platform_id
            """
        ),
        {"anchor_date": anchor_date, "current_user_id": current_user_id},
    ).mappings().all()
    return [dict(row) for row in rows]


@valuation_cached(shared=True)
def canonical_account_balance_rows(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    """
    Return normalized cash/balance dicts for all accounts visible to this user.

    Merges two source tables into one uniform shape so that dashboard and
    net-worth callers do not need to know where a balance originated:

    1. ``account_balance_snapshots``: each account's newest balances at the
       anchor (``effective_uploaded_balances_sql``), unless IBKR Flex owns the
       account at the anchor.
    2. ``portfolio_cash_balance_snapshots``: broker cash written by IBKR Flex,
       each broker account's newest at the anchor (``effective_broker_cash_sql``),
       for accounts with no rows from (1), preventing double-counting.

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
        flex_authority_accounts AS (""" + ef.flex_authority_accounts_cte() + """),

        -- 1. The newest balances per account, unless Flex owns the account.
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
          FROM (""" + ef.effective_uploaded_balances_sql() + """) abs
          JOIN accounts acc ON acc.id = abs.account_id
          LEFT JOIN platforms pl ON pl.id = acc.platform_id
          LEFT JOIN platforms pl_by_code ON pl_by_code.code = acc.platform
        ),

        -- 2. Accounts already covered by (1).
        abs_covered_accounts AS (
          SELECT DISTINCT account_id FROM abs_rows
        ),

        -- 3. The newest broker cash per broker account, for accounts not in (2).
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
          FROM (""" + ef.effective_broker_cash_sql(
            extra_where=["ba.legacy_account_id NOT IN (SELECT account_id FROM abs_covered_accounts)"]
        ) + """) cs
          JOIN broker_accounts ba ON ba.id = cs.broker_account_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          LEFT JOIN platforms pl ON pl.id = acc.platform_id
          LEFT JOIN platforms pl_by_code ON pl_by_code.code = acc.platform
        )

        SELECT * FROM abs_rows
        UNION ALL
        SELECT * FROM pcbs_rows
        ORDER BY account_id ASC, as_of_date DESC, currency ASC
        """
    )
    rows = db.execute(
        q,
        {"anchor_date": anchor_date, "current_user_id": current_user_id, **ef.flex_binds()},
    ).mappings().all()
    return [dict(r) for r in rows]


@valuation_cached(shared=True)
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
    Return the effective canonical snapshot date at/before ``anchor_date``: the
    newest of the accounts' latest fact dates (positions of accounts not valued
    by a NAV, plus a NAV account's own positions; NAV; balances except card
    statements, which are liabilities, not cash coverage (#207); broker cash).

    This mirrors the old dashboard snapshot semantics from legacy
    ``positions``: if the dashboard can compute a boundary view from latest
    known component facts, the effective as-of date is the latest canonical
    fact date available at or before the boundary. Individual component
    staleness is exposed separately as freshness metadata; it should not make
    the whole net-worth snapshot disappear.

    Flex-routed like the value readers (rule 5, D-62): only the facts a value
    reader counts can set the date. Positions and broker cash of a legacy account
    Flex owns come from its Flex broker account, and that account's uploaded
    balances don't count.
    """
    selected: list[str] = []
    if include_positions:
        selected.append(
            ef.latest_per_account_sql(
                ef.POSITIONS,
                ef.BROKER_ACCOUNT_OWNER,
                where=[ef.flex_routed_sql("ba"), ef.nav_rule_sql("ba", include_nav_accounts="TRUE")],
            )
        )
    if include_nav:
        selected.append(ef.latest_per_account_sql(ef.NAV, ef.BROKER_ACCOUNT_OWNER))
    if include_cash:
        selected.append(
            ef.latest_per_account_sql(
                ef.BALANCES,
                ef.BALANCE_OWNER,
                where=["abs.balance_type <> 'credit_balance'", ef.not_flex_owned_sql("acc.id")],
            )
        )
        selected.append(ef.latest_per_account_sql(ef.BROKER_CASH, ef.BROKER_ACCOUNT_OWNER, where=[ef.flex_routed_sql("ba")]))
    if not selected:
        return None
    q = text(
        "WITH flex_authority_accounts AS ("
        + ef.flex_authority_accounts_cte()
        + "),\nlatest AS (\n"
        + "\nUNION ALL\n".join(f"SELECT as_of_date FROM ({sql}) _component_{i}" for i, sql in enumerate(selected))
        + "\n)\nSELECT MAX(as_of_date) AS as_of_date FROM latest"
    )
    row = db.execute(
        q, {"anchor_date": anchor_date, "current_user_id": current_user_id, **ef.flex_binds()}
    ).mappings().one()
    return row["as_of_date"]


@valuation_cached(shared=True)
def get_data_completeness_status(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    """
    Return the latest completeness record per (broker_account, fact_scope)
    for all canonical accounts visible to this user, where it isn't complete.

    Incomplete scopes should be surfaced in dashboard responses as
    data-quality / completeness indicators rather than silently omitted.
    """
    q = text(
        """
        SELECT
          ba.legacy_account_id AS account_id,
          COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
          dc.fact_scope,
          dc.completeness_status,
          dc.missing_reason,
          dc.report_date
        FROM (""" + ef.effective_completeness_sql() + """) dc
        JOIN broker_accounts ba ON ba.id = dc.broker_account_id
        JOIN accounts acc ON acc.id = ba.legacy_account_id
        LEFT JOIN platforms pl ON pl.id = acc.platform_id
        WHERE dc.completeness_status <> 'complete'
        ORDER BY dc.fact_scope, acc.platform
        """
    )
    rows = db.execute(q, {"anchor_date": anchor_date, "current_user_id": current_user_id}).mappings().all()
    return [dict(r) for r in rows]


@valuation_cached(shared=True)
def canonical_card_statement_rows(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
    max_age_days: int | None = CARD_STATEMENT_MAX_AGE_DAYS,
) -> list[dict[str, Any]]:
    """Each card's statement balance at the anchor (``effective_card_statements_sql``):
    its newest ``credit_balance`` snapshots (#207), at most CARD_STATEMENT_MAX_AGE_DAYS
    old (D-52), one row per currency. ``max_age_days=None``: however old (the running
    balance's anchor, #300, which carries it forward with the card's transactions)."""
    rows = db.execute(
        text(
            """
            SELECT abs.account_id, abs.as_of_date, abs.currency, abs.balance_local
            FROM (""" + ef.effective_card_statements_sql() + """) abs
            ORDER BY abs.account_id, abs.currency
            """
        ),
        {
            "anchor_date": anchor_date,
            "oldest": anchor_date - timedelta(days=max_age_days) if max_age_days is not None else date(1900, 1, 1),
            "current_user_id": current_user_id,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


@valuation_cached(shared=True)
def canonical_latest_fact_dates(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    """Each open account's newest counting fact date on or before the anchor
    (``account_id``, ``as_of_date``), for the source freshness table (#252).

    The same facts ``valuation.account_status.account_data_status`` reports, from
    one grouped query instead of the full readers: positions (Flex-routed, a NAV
    account's own included), NAV, uploaded balances (not of an account Flex owns;
    not a card's), broker cash (Flex-routed; only for an account without an
    uploaded balance, as ``canonical_account_balance_rows`` merges them) and a
    card's statement balance. One difference: the card statement has **no age
    limit** here. Valuation stops carrying it after CARD_STATEMENT_MAX_AGE_DAYS
    (D-52), but "when was the last statement" needs it however old it is.
    Accounts with no counting fact are absent."""
    by_account = ("ba.id", "acc.id")  # the broker account's newest (D-62), reported per account
    parts = [
        (
            "owner_1",
            ef.latest_per_account_sql(
                ef.POSITIONS,
                by_account,
                where=[ef.flex_routed_sql("ba"), ef.nav_rule_sql("ba", include_nav_accounts="TRUE")],
            ),
        ),
        ("owner_1", ef.latest_per_account_sql(ef.NAV, by_account)),
        (
            "owner_0",
            ef.latest_per_account_sql(
                ef.BALANCES,
                ef.BALANCE_OWNER,
                where=["acc.account_type <> 'CREDIT_CARD'", ef.not_flex_owned_sql("acc.id")],
            ),
        ),
        (
            "owner_1",
            ef.latest_per_account_sql(
                ef.BROKER_CASH,
                by_account,
                where=[
                    ef.flex_routed_sql("ba"),
                    "ba.legacy_account_id NOT IN (SELECT account_id FROM balance_covered)",
                ],
            ),
        ),
        (
            "owner_0",
            ef.latest_per_account_sql(
                ef.BALANCES,
                ef.BALANCE_OWNER,
                where=["acc.account_type = 'CREDIT_CARD'", "abs.balance_type = 'credit_balance'"],
            ),
        ),
    ]
    q = text(
        "WITH flex_authority_accounts AS ("
        + ef.flex_authority_accounts_cte()
        + "),\nbalance_covered AS (SELECT DISTINCT account_id FROM ("
        + ef.effective_uploaded_balances_sql()
        + ") _abs),\nlatest AS (\n"
        + "\nUNION ALL\n".join(
            f"SELECT {owner} AS account_id, as_of_date FROM ({sql}) _component_{i}"
            for i, (owner, sql) in enumerate(parts)
        )
        + "\n)\nSELECT account_id, MAX(as_of_date) AS as_of_date FROM latest GROUP BY account_id ORDER BY account_id"
    )
    rows = db.execute(
        q, {"anchor_date": anchor_date, "current_user_id": current_user_id, **ef.flex_binds()}
    ).mappings().all()
    return [dict(r) for r in rows]
