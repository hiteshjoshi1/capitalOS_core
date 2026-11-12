"""What an upload changed (#410, UX U28, D-114): "balance S$ X on 31 Oct; net worth for
Oct changed by +S$ Y".

The runner measures the statement's month just before it writes anything and again after
the rows are committed, and the import report carries the difference (``effect``). The
month is the newest date the statement carries (its rows, its holdings date, its statement
date, or the date the user gave). Measuring never fails an upload: any error leaves
``effect`` out.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import use_timezone

logger = logging.getLogger(__name__)

_META_DATE_KEYS = ("statement_date", "as_of_date", "report_date", "balance_date", "transactions_as_at")


def _as_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def statement_day(
    transactions: Iterable[dict[str, Any]],
    positions: Iterable[dict[str, Any]],
    parser_meta: Optional[dict[str, Any]],
    user_as_of: Optional[date],
) -> Optional[date]:
    """The date the upload's figures count from: for a file with balances or holdings, the
    snapshot date they're written with (``resolve_upload_as_of``: the file's date, else the
    user's, else today); otherwise the newest date its rows carry. None: nothing dated."""
    positions = list(positions)
    if positions:
        from app.ingestion.as_of import resolve_upload_as_of

        return resolve_upload_as_of(parser_meta, user_as_of, positions)[0]
    days = [d for d in (_as_date(tx.get("ts") or tx.get("date")) for tx in transactions) if d]
    days += [d for d in (_as_date((parser_meta or {}).get(k)) for k in _META_DATE_KEYS) if d]
    if user_as_of:
        days.append(user_as_of)
    return max(days) if days else None


def _base_currency(db: Session, user_id: int) -> str:
    row = db.execute(text("SELECT base_currency FROM user_preferences WHERE user_id = :uid"), {"uid": user_id}).fetchone()
    return str(row[0]).upper() if row and row[0] else "SGD"


def measure(db: Session, user_id: int, account_id: int, day: date) -> Optional[dict[str, Any]]:
    """Net worth for ``day``'s month (live when it's the open month, as Overview shows it)
    and the account's cash balance there, in the user's base currency."""
    from app.services.user_preferences import effective_timezone
    from app.valuation.clock import _month_view_anchor, _parse_month
    from app.valuation.facts import _networth_components
    from app.valuation.state import _cash_positions
    from app.valuation_cache import request_scope

    try:
        with use_timezone(effective_timezone(db, user_id)), request_scope():
            month = day.strftime("%Y-%m")
            anchor, live = _month_view_anchor(_parse_month(month))
            base = _base_currency(db, user_id)
            total = Decimal(str(_networth_components(db, anchor, base, user_id, price_overlay=live)["total"]))
            balance: Optional[Decimal] = None
            balance_day: Optional[date] = None
            for entry in _cash_positions(db, anchor, base, user_id):
                if entry.get("account_id") is not None and int(entry["account_id"]) == int(account_id):
                    balance = (balance or Decimal("0")) + Decimal(str(entry.get("value") or 0))
                    seen = _as_date(entry.get("as_of_date"))
                    if seen and (balance_day is None or seen > balance_day):
                        balance_day = seen
            return {"month": month, "live": live, "base_currency": base, "net_worth": total,
                    "balance": balance, "balance_date": balance_day}
    except Exception:  # noqa: BLE001 - measuring must never fail an upload
        logger.exception("upload_effect_measure_failed", extra={"event": "upload_effect_measure_failed"})
        db.rollback()
        return None


def effect(before: Optional[dict[str, Any]], after: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The report's ``effect``: the month, the account's balance after, and net worth before,
    after and the change (floats, the report is JSON)."""
    if not before or not after or before["month"] != after["month"]:
        return None
    change = after["net_worth"] - before["net_worth"]
    return {
        "month": after["month"],
        "live": bool(after["live"]),
        "base_currency": after["base_currency"],
        "balance": float(after["balance"]) if after["balance"] is not None else None,
        "balance_date": after["balance_date"].isoformat() if after["balance_date"] else None,
        "net_worth_before": float(before["net_worth"]),
        "net_worth_after": float(after["net_worth"]),
        "net_worth_change": float(change),
    }
