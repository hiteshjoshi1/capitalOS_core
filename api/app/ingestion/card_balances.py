"""Card statement balances as dated snapshots (#207, #130 finding 1.6).

Every card statement that states what the card owes writes one
``account_balance_snapshots`` row (``balance_type='credit_balance'``) dated by the
statement, so an anchor reads the newest balance on or before it, like a bank
balance, and a newer statement never changes an earlier month. The balance is
the holder's view, like the card's transactions: negative while money is owed.

What each card parser gives:
- ``dbs_credit_card_csv_v1``: credit limit and available limit "as at" a date
  (the export date); the balance is available - limit on that date (what the
  liability used before #207, from ``credit_card_accounts``).
- ``uob_credit_card_xls_v1``: the statement balance on the statement date
  (positive = owed). A value the parser can't read (e.g. a "CR" suffix) gives none.
- ``citi_credit_card_csv_v1``: no balance or date; the card keeps the
  transaction method.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio.upload_canonical import _write_account_balance_snapshot
from app.wealth_rollup_dirty import mark_rollups_dirty

CARD_BALANCE_TYPE = "credit_balance"
CARD_BALANCE_PARSERS = frozenset({"dbs_credit_card_csv_v1", "uob_credit_card_xls_v1"})


@dataclass(frozen=True)
class CardStatementBalance:
    as_of_date: date
    balance: float  # the holder's view: negative while money is owed
    metadata: dict[str, Any]


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return _as_date(parsed)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def card_statement_balance(parser_key: str | None, parser_meta: dict[str, Any] | None) -> CardStatementBalance | None:
    """The dated balance a card statement states, or None when it states none."""
    meta = parser_meta or {}
    if parser_key == "dbs_credit_card_csv_v1":
        credit_limit = _number(meta.get("credit_limit"))
        available = _number(meta.get("available_limit"))
        as_of = _as_date(meta.get("transactions_as_at"))
        if credit_limit is None or available is None or as_of is None:
            return None
        return CardStatementBalance(
            as_of_date=as_of,
            balance=round(available - credit_limit, 2),
            metadata={"source": "available_limit", "credit_limit": credit_limit, "available_limit": available},
        )
    if parser_key == "uob_credit_card_xls_v1":
        owed = _number(meta.get("statement_balance"))
        as_of = _as_date(meta.get("statement_date"))
        if owed is None or as_of is None:
            return None
        return CardStatementBalance(
            as_of_date=as_of,
            balance=round(-owed, 2),
            metadata={"source": "statement_balance", "statement_balance": owed},
        )
    return None


def _account_currency(db: Session, account_id: int) -> str | None:
    row = db.execute(text("SELECT currency FROM accounts WHERE id = :id"), {"id": account_id}).fetchone()
    return str(row[0]).upper() if row and row[0] else None


def _row_hash(account_id: int, statement: CardStatementBalance, currency: str) -> str:
    raw = f"card|{account_id}|{statement.as_of_date.isoformat()}|{currency}|{statement.balance}"
    return hashlib.sha256(raw.encode()).hexdigest()


def write_card_statement_balance(
    db: Session,
    *,
    account_id: int,
    import_job_id: int | None,
    parser_key: str | None,
    parser_meta: dict[str, Any] | None,
    undo: dict[str, Any] | None = None,
    mark_dirty: bool = True,
) -> CardStatementBalance | None:
    """Write the statement's dated balance for a card account (upsert per date).

    In the account's currency (the liability's currency before #207). With
    ``undo``, the row it replaces is kept so removing the upload restores it.
    Marks History dirty from the statement's date (D-29): no earlier anchor
    reads it. Doesn't commit. Returns what was written, or None.
    """
    statement = card_statement_balance(parser_key, parser_meta)
    if statement is None:
        return None
    currency = _account_currency(db, account_id) or str((parser_meta or {}).get("currency") or "SGD").upper()
    metadata = {**statement.metadata, "parser_key": parser_key}
    statement_currency = (parser_meta or {}).get("currency")
    if statement_currency:
        metadata["statement_currency"] = str(statement_currency).upper()
    _write_account_balance_snapshot(
        db,
        account_id=account_id,
        import_job_id=import_job_id,
        as_of_date=statement.as_of_date,
        currency=currency,
        balance_local=statement.balance,
        balance_base=statement.balance,
        balance_type=CARD_BALANCE_TYPE,
        source_row_hash=_row_hash(account_id, statement, currency),
        metadata=metadata,
        undo=undo,
    )
    if undo is not None:
        undo.setdefault("affected_dates", []).append(statement.as_of_date.isoformat())
    if mark_dirty:
        mark_rollups_dirty(db, statement.as_of_date, account_id=account_id, reason="card_statement_balance")
    return statement
