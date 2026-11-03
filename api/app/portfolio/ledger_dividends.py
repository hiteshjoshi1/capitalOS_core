"""Dividend and withholding-tax rows from the broker cash ledger (#113).

IBKR Flex imports write every Statement of Funds line to
`portfolio_cash_ledger_entries`. The Dividends page used to read only the
legacy `transactions` table, which Flex never writes, so IBKR dividends never
showed. This module returns ledger dividend lines shaped like the rows
`app.routers.dividends._fetch_dividend_rows` builds from `transactions`, so
the page's aggregation treats both sources the same way.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql

# IBKR Statement of Funds activity codes.
DIVIDEND_CODES = frozenset({"DIV", "PIL"})  # cash dividend, payment in lieu of dividend
WITHHOLDING_CODES = frozenset({"FRTAX", "WHT"})  # withholding tax on a dividend
LEDGER_CODES = DIVIDEND_CODES | WITHHOLDING_CODES

# Listing exchange -> country, for a security that has no CapitalOS asset yet.
_EXCHANGE_COUNTRY = {
    "SEHK": "HK",
    "HKEX": "HK",
    "SGX": "SG",
    "NYSE": "US",
    "NASDAQ": "US",
    "ARCA": "US",
    "AMEX": "US",
    "BATS": "US",
    "NSE": "IN",
    "BSE": "IN",
}


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def ledger_covered_since(db: Session, current_user_id: int) -> dict[int, date]:
    """Legacy account id -> first date the broker cash ledger has lines for it.
    From that date the ledger is the account's dividend source, so dividend rows
    in `transactions` for the same account (e.g. an old CSV upload) are skipped
    rather than counted twice."""
    rows = db.execute(
        text(
            """
            SELECT ba.legacy_account_id AS account_id, MIN(l.activity_date) AS first_date
            FROM portfolio_cash_ledger_entries l
            JOIN broker_accounts ba ON ba.id = l.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE """
            + account_scope_sql("acc")
            + """
            GROUP BY ba.legacy_account_id
            """
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    return {int(row["account_id"]): _as_date(row["first_date"]) for row in rows if row["first_date"] is not None}


def _instruments_by_conid(db: Session, conids: set[str]) -> dict[str, dict[str, Any]]:
    if not conids:
        return {}
    params = {f"c{i}": conid for i, conid in enumerate(sorted(conids))}
    placeholders = ", ".join(f":{key}" for key in params)
    rows = db.execute(
        text(
            f"""
            SELECT
              bi.broker_instrument_id AS conid,
              bi.asset_id,
              bi.symbol,
              bi.description,
              bi.listing_exchange,
              bi.country,
              a.symbol AS asset_symbol,
              a.name AS asset_name,
              a.home_country
            FROM broker_instruments bi
            LEFT JOIN assets a ON a.id = bi.asset_id
            WHERE bi.platform_code = 'IBKR'
              AND bi.broker_instrument_id IN ({placeholders})
            ORDER BY bi.asset_id IS NULL, bi.id
            """
        ),
        params,
    ).mappings().all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out.setdefault(str(row["conid"]), dict(row))
    return out


def fetch_ledger_dividend_rows(
    db: Session,
    start: datetime,
    end: datetime,
    current_user_id: int,
    *,
    asset_id: int | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Dividend / withholding ledger lines with activity_date in [start, end)."""
    codes = sorted(LEDGER_CODES)
    code_params = {f"code{i}": code for i, code in enumerate(codes)}
    code_list = ", ".join(f":{key}" for key in code_params)
    rows = db.execute(
        text(
            f"""
            SELECT
              l.id,
              l.activity_date,
              l.amount,
              l.currency,
              l.activity_code,
              l.description,
              l.metadata_json,
              acc.id AS account_id,
              acc.country AS account_country
            FROM portfolio_cash_ledger_entries l
            JOIN broker_accounts ba ON ba.id = l.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE l.activity_date >= :start_date
              AND l.activity_date < :end_date
              AND UPPER(COALESCE(l.activity_code, '')) IN ({code_list})
              AND """
            + account_scope_sql("acc")
            + """
            ORDER BY l.activity_date ASC, l.id ASC
            """
        ),
        {
            "start_date": start.date(),
            "end_date": end.date(),
            "current_user_id": current_user_id,
            **code_params,
        },
    ).mappings().all()

    securities = [(_metadata(row["metadata_json"]).get("security") or {}) for row in rows]
    instruments = _instruments_by_conid(db, {str(s["conid"]) for s in securities if s.get("conid")})

    wanted_symbol = symbol.strip().upper() if symbol and symbol.strip() else None
    out: list[dict[str, Any]] = []
    for row, security in zip(rows, securities):
        code = str(row["activity_code"] or "").upper()
        instrument = instruments.get(str(security.get("conid") or ""), {})
        row_asset_id = instrument.get("asset_id")
        row_symbol = str(instrument.get("asset_symbol") or security.get("symbol") or instrument.get("symbol") or "").strip()
        exchange = str(instrument.get("listing_exchange") or security.get("listing_exchange") or "").upper()
        country = (
            instrument.get("home_country")
            or instrument.get("country")
            or _EXCHANGE_COUNTRY.get(exchange)
            or row["account_country"]
        )
        if asset_id is not None and row_asset_id != asset_id:
            continue
        if wanted_symbol is not None and row_symbol.upper() != wanted_symbol:
            continue
        is_dividend = code in DIVIDEND_CODES
        out.append(
            {
                "id": f"ledger:{row['id']}",
                "ts": datetime.combine(_as_date(row["activity_date"]), time.min, tzinfo=timezone.utc),
                "amount": float(row["amount"] or 0.0),
                "currency": row["currency"],
                "type": "INCOME" if is_dividend else "TAX",
                "category": "Dividend" if is_dividend else "Withholding tax",
                "asset_id": row_asset_id,
                "merchant_counterparty": row_symbol or row["description"],
                "asset_symbol": row_symbol or None,
                "asset_name": instrument.get("asset_name")
                or security.get("security_description")
                or instrument.get("description")
                or row_symbol
                or None,
                "country": country,
                "resolved_category_code": "income_dividends" if is_dividend else "taxes_withholding",
                "source": "broker_cash_ledger",
            }
        )
    return out
