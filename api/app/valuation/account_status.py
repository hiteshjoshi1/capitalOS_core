"""Per-account data status for a month (#207, #130 finding 1.5): the date of the
newest fact the month's valuation reads for each account, and whether that value
is carried forward from before the month.

A month's anchor reads each account's newest snapshot on or before it, with no
age limit (cash, holdings, NAV); a card reads its newest statement balance within
CARD_STATEMENT_MAX_AGE_DAYS. When that snapshot is dated before the month began,
the month shows a value carried forward from an earlier month:
``carried_forward_from`` is that date. A closed account (``accounts.closed_on``
before the anchor) reads nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.portfolio.account_open import account_open_sql
from app.portfolio.authority import authoritative_sql
from app.portfolio.canonical_reads import canonical_account_balance_rows, canonical_position_rows_by_legacy_account
from app.portfolio.ibkr_flex import latest_authoritative_nav_by_legacy_account
from app.valuation.clock import _date_only
from app.valuation.facts import CARD_STATEMENT_MAX_AGE_DAYS
from app.valuation.state import _credit_card_account_ids


def _card_statement_dates(db: Session, anchor_date: date, current_user_id: int) -> Dict[int, date]:
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


def account_data_status(
    db: Session,
    *,
    current_user_id: int,
    anchor_ts: datetime,
    month_start: date,
) -> Dict[int, Dict[str, Any]]:
    """Per account id: ``last_data_as_of`` (ISO date of the newest fact the anchor
    reads for it, or None) and ``carried_forward_from`` (that date when it is
    before ``month_start``, else None). Accounts with nothing read are absent."""
    anchor_date = anchor_ts.date()
    newest: Dict[int, date] = {}

    def _note(account_id: Any, value: Any) -> None:
        as_of = _date_only(value)
        if account_id is None or as_of is None:
            return
        key = int(account_id)
        if key not in newest or as_of > newest[key]:
            newest[key] = as_of

    card_ids = _credit_card_account_ids(db, current_user_id)
    for row in canonical_account_balance_rows(db, current_user_id=current_user_id, anchor_date=anchor_date):
        # A card's statement balance counts only within its age limit (below).
        if row.get("account_id") is not None and int(row["account_id"]) not in card_ids:
            _note(row.get("account_id"), row.get("as_of_date"))
    for row in canonical_position_rows_by_legacy_account(
        db, current_user_id=current_user_id, anchor_date=anchor_date, include_nav_accounts=True
    ):
        _note(row.get("account_id"), row.get("report_date"))
    for row in latest_authoritative_nav_by_legacy_account(db, current_user_id=current_user_id, anchor_date=anchor_date):
        _note(row.get("legacy_account_id"), row.get("report_date"))
    for account_id, as_of in _card_statement_dates(db, anchor_date, current_user_id).items():
        _note(account_id, as_of)

    return {
        account_id: {
            "last_data_as_of": as_of.isoformat(),
            "carried_forward_from": as_of.isoformat() if as_of < month_start else None,
        }
        for account_id, as_of in newest.items()
    }
