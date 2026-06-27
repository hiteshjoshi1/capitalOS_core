"""
Parity report for canonical portfolio phase 6.

Compares legacy ``positions`` reads against canonical table reads so that
the before/after equivalence can be verified before the read cutover in
phase 7.

Report sections
---------------
- net_worth        : total base-currency value per account and overall.
- stock_holdings   : quantity per symbol per account (legacy vs canonical).
- cash_balances    : cash balance per account/currency (legacy vs canonical).
- platform_alloc   : base-value share per platform.
- geography_alloc  : base-value share per home_country.

Usage (module script)::

    python -m app.portfolio.parity_report --user-id 1 --anchor-date 2026-01-31

Usage from Python::

    from app.portfolio.parity_report import generate_parity_report
    report = generate_parity_report(db, current_user_id=1, anchor_date=date(2026, 1, 31))
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.portfolio.legacy_backfill import (
    _historical_fx_rate,
    _legacy_cash_amounts,
    _legacy_stock_amounts,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _float(v: Any) -> float:
    if v is None:
        return 0.0
    return float(Decimal(str(v)))


def _delta(legacy: float, canonical: float) -> float:
    return round(canonical - legacy, 8)


# ---------------------------------------------------------------------------
# Legacy reads (from positions table)
# ---------------------------------------------------------------------------


def _legacy_stock_fund_values(
    db: Session, *, current_user_id: int, anchor_date: date
) -> dict[tuple[int, str], float]:
    """
    Return {(account_id, symbol): base_value} from legacy positions for
    STOCK/FUND rows at the latest as_of <= anchor_date per account.
    """
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT p.account_id, MAX(p.as_of) AS as_of
              FROM positions p
              JOIN assets a ON a.id = p.asset_id
              WHERE DATE(p.as_of) <= :anchor_date
                AND a.asset_class IN ('STOCK', 'FUND')
              GROUP BY p.account_id
            )
            SELECT
              p.account_id,
              a.symbol,
              a.asset_class,
              a.quote_currency,
              a.home_country,
              COALESCE(acc.platform, '') AS platform,
              COALESCE(acc.currency, a.quote_currency) AS account_currency,
              DATE(p.as_of) AS report_date,
              CAST(p.cost_basis_base AS REAL) AS base_value,
              CAST(p.avg_cost AS REAL) AS avg_cost,
              CAST(p.quantity AS REAL) AS quantity
            FROM positions p
            JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
            JOIN assets a ON a.id = p.asset_id
            JOIN accounts acc ON acc.id = p.account_id
            WHERE a.asset_class IN ('STOCK', 'FUND')
              AND ("""
            + account_scope_sql("acc")
            + """)
            """
        ),
        {"anchor_date": anchor_date, "current_user_id": current_user_id},
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        fx_rate = _historical_fx_rate(
            report_date=date.fromisoformat(str(item["report_date"])[:10]),
            base_currency=str(item["account_currency"] or item["quote_currency"]),
            quote_currency=str(item["quote_currency"]),
        )
        amounts = _legacy_stock_amounts(
            raw_value=item["base_value"],
            quantity=item["quantity"],
            avg_cost=item["avg_cost"],
            fx_rate_to_base=fx_rate,
            platform=str(item["platform"]),
        )
        item["base_value"] = amounts["market_value_base"]
        out.append(item)
    return out


def _legacy_cash_values(
    db: Session, *, current_user_id: int, anchor_date: date
) -> list[dict[str, Any]]:
    """Return legacy cash positions at latest as_of <= anchor_date."""
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT p.account_id, MAX(p.as_of) AS as_of
              FROM positions p
              JOIN assets a ON a.id = p.asset_id
              WHERE DATE(p.as_of) <= :anchor_date
                AND a.asset_class = 'CASH'
              GROUP BY p.account_id
            )
            SELECT
              p.account_id,
              a.quote_currency AS currency,
              COALESCE(acc.platform, '') AS platform,
              COALESCE(acc.currency, a.quote_currency) AS account_currency,
              DATE(p.as_of) AS report_date,
              CAST(p.cost_basis_base AS REAL) AS base_value
            FROM positions p
            JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
            JOIN assets a ON a.id = p.asset_id
            JOIN accounts acc ON acc.id = p.account_id
            WHERE a.asset_class = 'CASH'
              AND ("""
            + account_scope_sql("acc")
            + """)
            """
        ),
        {"anchor_date": anchor_date, "current_user_id": current_user_id},
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        fx_rate = _historical_fx_rate(
            report_date=date.fromisoformat(str(item["report_date"])[:10]),
            base_currency=str(item["account_currency"] or item["currency"]),
            quote_currency=str(item["currency"]),
        )
        amounts = _legacy_cash_amounts(
            raw_value=item["base_value"],
            fx_rate_to_base=fx_rate,
            platform=str(item["platform"]),
        )
        item["base_value"] = amounts["balance_base"]
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Canonical reads (from portfolio tables)
# ---------------------------------------------------------------------------


def _canonical_stock_fund_values(
    db: Session, *, current_user_id: int, anchor_date: date
) -> list[dict[str, Any]]:
    """
    Return canonical position snapshot rows at the latest authoritative
    report_date <= anchor_date per broker_account.
    """
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT ps.broker_account_id, MAX(ps.report_date) AS report_date
              FROM portfolio_position_snapshots ps
              JOIN broker_accounts ba ON ba.id = ps.broker_account_id
              JOIN accounts acc ON acc.id = ba.legacy_account_id
              WHERE ps.report_date <= :anchor_date
                AND ps.authority_status = 'authoritative'
                AND ba.legacy_account_id IS NOT NULL
                AND ("""
            + account_scope_sql("acc")
            + """)
              GROUP BY ps.broker_account_id
            )
            SELECT
              ba.legacy_account_id AS account_id,
              bi.symbol,
              COALESCE(CAST(a.asset_class AS TEXT), bi.security_type, 'STOCK') AS asset_class,
              COALESCE(a.quote_currency, bi.currency) AS quote_currency,
              COALESCE(a.home_country, '') AS home_country,
              COALESCE(acc.platform, '') AS platform,
              CAST(ps.market_value_base AS REAL) AS base_value,
              CAST(ps.quantity AS REAL) AS quantity
            FROM portfolio_position_snapshots ps
            JOIN latest l ON l.broker_account_id = ps.broker_account_id AND l.report_date = ps.report_date
            JOIN broker_accounts ba ON ba.id = ps.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            JOIN broker_instruments bi ON bi.id = ps.broker_instrument_id
            LEFT JOIN assets a ON a.id = bi.asset_id
            WHERE ps.authority_status = 'authoritative'
            """
        ),
        {"anchor_date": anchor_date, "current_user_id": current_user_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _canonical_cash_values(
    db: Session, *, current_user_id: int, anchor_date: date
) -> list[dict[str, Any]]:
    """
    Return canonical cash balance rows (account_balance_snapshots) at the
    latest authoritative as_of_date <= anchor_date per account.
    """
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT abs.account_id, MAX(abs.as_of_date) AS as_of_date
              FROM account_balance_snapshots abs
              JOIN accounts acc ON acc.id = abs.account_id
              WHERE abs.as_of_date <= :anchor_date
                AND abs.authority_status = 'authoritative'
                AND ("""
            + account_scope_sql("acc")
            + """)
              GROUP BY abs.account_id
            )
            SELECT
              abs.account_id,
              abs.currency,
              COALESCE(acc.platform, '') AS platform,
              CAST(abs.balance_base AS REAL) AS base_value
            FROM account_balance_snapshots abs
            JOIN latest l ON l.account_id = abs.account_id AND l.as_of_date = abs.as_of_date
            JOIN accounts acc ON acc.id = abs.account_id
            WHERE abs.authority_status = 'authoritative'
            """
        ),
        {"anchor_date": anchor_date, "current_user_id": current_user_id},
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def generate_parity_report(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> dict[str, Any]:
    """
    Generate a before/after parity report comparing legacy ``positions``
    reads with canonical table reads.

    Returns a dict with keys:
    - ``net_worth``         : overall and per-account totals.
    - ``stock_holdings``    : per-(account, symbol) quantity/value comparison.
    - ``cash_balances``     : per-(account, currency) balance comparison.
    - ``platform_alloc``    : per-platform base-value comparison.
    - ``geography_alloc``   : per-country base-value comparison.
    - ``summary``           : high-level delta summary.
    """
    legacy_sf = _legacy_stock_fund_values(db, current_user_id=current_user_id, anchor_date=anchor_date)
    canonical_sf = _canonical_stock_fund_values(db, current_user_id=current_user_id, anchor_date=anchor_date)
    legacy_cash = _legacy_cash_values(db, current_user_id=current_user_id, anchor_date=anchor_date)
    canonical_cash = _canonical_cash_values(db, current_user_id=current_user_id, anchor_date=anchor_date)

    # ---- net worth ---------------------------------------------------

    legacy_sf_total = sum(_float(r["base_value"]) for r in legacy_sf)
    canonical_sf_total = sum(_float(r["base_value"]) for r in canonical_sf)
    legacy_cash_total = sum(_float(r["base_value"]) for r in legacy_cash)
    canonical_cash_total = sum(_float(r["base_value"]) for r in canonical_cash)

    net_worth = {
        "legacy_stock_fund": legacy_sf_total,
        "canonical_stock_fund": canonical_sf_total,
        "legacy_cash": legacy_cash_total,
        "canonical_cash": canonical_cash_total,
        "legacy_total": legacy_sf_total + legacy_cash_total,
        "canonical_total": canonical_sf_total + canonical_cash_total,
        "delta_stock_fund": _delta(legacy_sf_total, canonical_sf_total),
        "delta_cash": _delta(legacy_cash_total, canonical_cash_total),
        "delta_total": _delta(legacy_sf_total + legacy_cash_total, canonical_sf_total + canonical_cash_total),
    }

    # ---- per-account net worth ---------------------------------------

    legacy_by_acct: dict[int, float] = {}
    for r in legacy_sf:
        acct = int(r["account_id"])
        legacy_by_acct[acct] = legacy_by_acct.get(acct, 0.0) + _float(r["base_value"])
    for r in legacy_cash:
        acct = int(r["account_id"])
        legacy_by_acct[acct] = legacy_by_acct.get(acct, 0.0) + _float(r["base_value"])

    canonical_by_acct: dict[int, float] = {}
    for r in canonical_sf:
        acct = int(r["account_id"])
        canonical_by_acct[acct] = canonical_by_acct.get(acct, 0.0) + _float(r["base_value"])
    for r in canonical_cash:
        acct = int(r["account_id"])
        canonical_by_acct[acct] = canonical_by_acct.get(acct, 0.0) + _float(r["base_value"])

    all_accts = sorted(set(legacy_by_acct) | set(canonical_by_acct))
    net_worth["accounts"] = [
        {
            "account_id": acct,
            "legacy": legacy_by_acct.get(acct, 0.0),
            "canonical": canonical_by_acct.get(acct, 0.0),
            "delta": _delta(legacy_by_acct.get(acct, 0.0), canonical_by_acct.get(acct, 0.0)),
        }
        for acct in all_accts
    ]

    # ---- stock holdings ---------------------------------------------

    # Key: (account_id, symbol)
    legacy_sf_map: dict[tuple[int, str], dict] = {}
    for r in legacy_sf:
        k = (int(r["account_id"]), str(r["symbol"]))
        legacy_sf_map[k] = r

    canonical_sf_map: dict[tuple[int, str], dict] = {}
    for r in canonical_sf:
        k = (int(r["account_id"]), str(r["symbol"]))
        canonical_sf_map[k] = r

    all_sf_keys = sorted(set(legacy_sf_map) | set(canonical_sf_map))
    stock_holdings = [
        {
            "account_id": k[0],
            "symbol": k[1],
            "legacy_qty": _float((legacy_sf_map.get(k) or {}).get("quantity")),
            "canonical_qty": _float((canonical_sf_map.get(k) or {}).get("quantity")),
            "legacy_value": _float((legacy_sf_map.get(k) or {}).get("base_value")),
            "canonical_value": _float((canonical_sf_map.get(k) or {}).get("base_value")),
            "delta_qty": _delta(
                _float((legacy_sf_map.get(k) or {}).get("quantity")),
                _float((canonical_sf_map.get(k) or {}).get("quantity")),
            ),
            "delta_value": _delta(
                _float((legacy_sf_map.get(k) or {}).get("base_value")),
                _float((canonical_sf_map.get(k) or {}).get("base_value")),
            ),
        }
        for k in all_sf_keys
    ]

    # ---- cash balances ----------------------------------------------

    legacy_cash_map: dict[tuple[int, str], float] = {}
    for r in legacy_cash:
        k = (int(r["account_id"]), str(r["currency"]))
        legacy_cash_map[k] = legacy_cash_map.get(k, 0.0) + _float(r["base_value"])

    canonical_cash_map: dict[tuple[int, str], float] = {}
    for r in canonical_cash:
        k = (int(r["account_id"]), str(r["currency"]))
        canonical_cash_map[k] = canonical_cash_map.get(k, 0.0) + _float(r["base_value"])

    all_cash_keys = sorted(set(legacy_cash_map) | set(canonical_cash_map))
    cash_balances = [
        {
            "account_id": k[0],
            "currency": k[1],
            "legacy": legacy_cash_map.get(k, 0.0),
            "canonical": canonical_cash_map.get(k, 0.0),
            "delta": _delta(legacy_cash_map.get(k, 0.0), canonical_cash_map.get(k, 0.0)),
        }
        for k in all_cash_keys
    ]

    # ---- platform allocation ----------------------------------------

    legacy_plat: dict[str, float] = {}
    for r in legacy_sf + legacy_cash:
        p = str(r["platform"])
        legacy_plat[p] = legacy_plat.get(p, 0.0) + _float(r["base_value"])

    canonical_plat: dict[str, float] = {}
    for r in canonical_sf + canonical_cash:
        p = str(r["platform"])
        canonical_plat[p] = canonical_plat.get(p, 0.0) + _float(r["base_value"])

    all_plats = sorted(set(legacy_plat) | set(canonical_plat))
    platform_alloc = [
        {
            "platform": p,
            "legacy": legacy_plat.get(p, 0.0),
            "canonical": canonical_plat.get(p, 0.0),
            "delta": _delta(legacy_plat.get(p, 0.0), canonical_plat.get(p, 0.0)),
        }
        for p in all_plats
    ]

    # ---- geography allocation ---------------------------------------

    legacy_geo: dict[str, float] = {}
    for r in legacy_sf:
        g = str(r.get("home_country") or "UNKNOWN")
        legacy_geo[g] = legacy_geo.get(g, 0.0) + _float(r["base_value"])
    # Cash doesn't have country breakdown in legacy

    canonical_geo: dict[str, float] = {}
    for r in canonical_sf:
        g = str(r.get("home_country") or "UNKNOWN")
        canonical_geo[g] = canonical_geo.get(g, 0.0) + _float(r["base_value"])

    all_geos = sorted(set(legacy_geo) | set(canonical_geo))
    geography_alloc = [
        {
            "country": g,
            "legacy": legacy_geo.get(g, 0.0),
            "canonical": canonical_geo.get(g, 0.0),
            "delta": _delta(legacy_geo.get(g, 0.0), canonical_geo.get(g, 0.0)),
        }
        for g in all_geos
    ]

    # ---- summary ----------------------------------------------------

    mismatched_positions = sum(1 for s in stock_holdings if abs(s["delta_qty"]) > 1e-6)
    mismatched_cash = sum(1 for c in cash_balances if abs(c["delta"]) > 0.01)

    summary = {
        "anchor_date": str(anchor_date),
        "legacy_total": net_worth["legacy_total"],
        "canonical_total": net_worth["canonical_total"],
        "net_worth_delta": net_worth["delta_total"],
        "stock_holding_rows": len(stock_holdings),
        "mismatched_position_rows": mismatched_positions,
        "cash_balance_rows": len(cash_balances),
        "mismatched_cash_rows": mismatched_cash,
        "parity_ok": mismatched_positions == 0 and mismatched_cash == 0,
    }

    return {
        "net_worth": net_worth,
        "stock_holdings": stock_holdings,
        "cash_balances": cash_balances,
        "platform_alloc": platform_alloc,
        "geography_alloc": geography_alloc,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _cli() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    parser = argparse.ArgumentParser(description="Generate legacy/canonical parity report.")
    parser.add_argument("--user-id", type=int, default=1, help="User ID (default: 1).")
    parser.add_argument("--anchor-date", type=str, default=None, help="YYYY-MM-DD (default: today).")
    args = parser.parse_args()

    anchor = date.fromisoformat(args.anchor_date) if args.anchor_date else date.today()

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        report = generate_parity_report(session, current_user_id=args.user_id, anchor_date=anchor)
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    _cli()
