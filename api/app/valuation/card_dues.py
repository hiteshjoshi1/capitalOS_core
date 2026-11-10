"""Card payment due dates (#352, D-94): what a statement says is due, by when, and
whether the card's payments since have covered it.

A due date is only ever one a statement printed: read by the card's parser
(``source='statement'``) or typed in from the statement by its owner (``'manual'``),
stored in ``card_statement_dues``. A card with no row has no known due date; nothing
here guesses one from a day of the month.

The card's **current due** is its newest row (by statement date) up to today. Payments
and credits after the statement date count towards it, bank-side payments included
(#308, via the card's ledger). Its status:

- ``paid``: what the statement says is owed is covered (or it said nothing was owed);
- ``overdue``: past the due date and not covered;
- ``due_soon``: due within ``REMIND_DAYS`` days and not covered;
- ``upcoming``: due later.

``minimum_paid`` says whether at least the minimum payment was made: the late fee is
avoided, but interest still runs on the rest (Citi, Sep 2026).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.valuation.card_ledger import CardLedger

REMIND_DAYS = 5  # the Inbox reminds this many days before the due date
TOLERANCE = 0.005


@dataclass(frozen=True)
class DueRecord:
    account_id: int
    statement_date: date
    due_date: date
    amount_due: float | None
    minimum_due: float | None
    source: str


@dataclass(frozen=True)
class DueState:
    account_id: int
    statement_date: date
    due_date: date
    amount_due: float | None  # what the statement says is owed (card currency)
    minimum_due: float | None
    source: str  # statement | manual
    paid: float  # payments and credits since the statement date
    status: str  # paid | overdue | due_soon | upcoming
    days_until: int  # negative once overdue

    @property
    def remaining(self) -> float | None:
        if self.amount_due is None:
            return None
        return round(max(self.amount_due - self.paid, 0.0), 2)

    @property
    def minimum_paid(self) -> bool | None:
        if self.minimum_due is None:
            return None
        return self.paid >= self.minimum_due - TOLERANCE


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _num(value: Any) -> float | None:
    return None if value is None else round(float(value), 2)


def load_due_records(db: Session, current_user_id: int, *, today: date) -> dict[int, DueRecord]:
    """Each card's newest due record whose statement is dated up to ``today``."""
    rows = db.execute(
        text(
            """
            SELECT d.account_id, d.statement_date, d.due_date, d.amount_due, d.minimum_due, d.source
            FROM card_statement_dues d
            JOIN accounts a ON a.id = d.account_id
            WHERE d.statement_date <= :today
              AND a.account_type = 'CREDIT_CARD' AND """
            + account_scope_sql("a")
            + " ORDER BY d.account_id, d.statement_date"
        ),
        {"today": today, "current_user_id": current_user_id},
    ).mappings().all()
    out: dict[int, DueRecord] = {}
    for row in rows:  # ascending: the newest per card wins
        out[int(row["account_id"])] = DueRecord(
            account_id=int(row["account_id"]),
            statement_date=_day(row["statement_date"]),
            due_date=_day(row["due_date"]),
            amount_due=_num(row["amount_due"]),
            minimum_due=_num(row["minimum_due"]),
            source=str(row["source"]),
        )
    return out


def due_state(record: DueRecord, ledger: CardLedger | None, *, today: date) -> DueState:
    """Where one statement's payment stands on ``today``."""
    amount_due = record.amount_due
    if amount_due is None and ledger is not None:
        # The statement's own balance, when the card has one dated that day.
        for period in ledger.periods:
            if period.from_date == record.statement_date:
                amount_due = round(period.opening, 2)
                break
    paid = ledger.paid_after(record.statement_date, through=today) if ledger is not None else 0.0
    days_until = (record.due_date - today).days
    if amount_due is not None and paid >= amount_due - TOLERANCE:
        status = "paid"
    elif days_until < 0:
        status = "overdue"
    elif days_until <= REMIND_DAYS:
        status = "due_soon"
    else:
        status = "upcoming"
    return DueState(
        account_id=record.account_id,
        statement_date=record.statement_date,
        due_date=record.due_date,
        amount_due=amount_due,
        minimum_due=record.minimum_due,
        source=record.source,
        paid=paid,
        status=status,
        days_until=days_until,
    )


def due_states(
    records: Mapping[int, DueRecord], ledgers: Iterable[CardLedger], *, today: date
) -> dict[int, DueState]:
    by_card = {ledger.account_id: ledger for ledger in ledgers}
    return {account_id: due_state(record, by_card.get(account_id), today=today) for account_id, record in records.items()}


def card_due_states(db: Session, current_user_id: int, *, today: date) -> dict[int, DueState]:
    """Every card's current due (cards with no due record are left out: unknown)."""
    from app.valuation.card_ledger import card_ledgers

    records = load_due_records(db, current_user_id, today=today)
    if not records:
        return {}
    return due_states(records, card_ledgers(db, current_user_id, today=today), today=today)


def write_due(
    db: Session,
    *,
    account_id: int,
    statement_date: date,
    due_date: date,
    amount_due: float | None,
    minimum_due: float | None,
    source: str,
    import_job_id: int | None = None,
) -> None:
    """Upsert one statement's due (one row per card and statement date). Doesn't commit.
    A typed-in due never replaces one a statement upload stated, and vice versa an upload
    replaces a typed-in one (the file is what the bank printed)."""
    if due_date < statement_date:
        raise ValueError("The due date can't be before the statement date")
    existing = db.execute(
        text("SELECT id, source FROM card_statement_dues WHERE account_id = :a AND statement_date = :d"),
        {"a": account_id, "d": statement_date},
    ).mappings().first()
    params = {
        "a": account_id,
        "d": statement_date,
        "due": due_date,
        "amt": amount_due,
        "min": minimum_due,
        "src": source,
        "job": import_job_id,
    }
    if existing is None:
        db.execute(
            text(
                "INSERT INTO card_statement_dues "
                "(account_id, statement_date, due_date, amount_due, minimum_due, source, import_job_id) "
                "VALUES (:a, :d, :due, :amt, :min, :src, :job)"
            ),
            params,
        )
        return
    if existing["source"] == "statement" and source == "manual":
        raise ValueError("This statement's due date was read from its upload; remove the upload to change it")
    db.execute(
        text(
            "UPDATE card_statement_dues SET due_date = :due, amount_due = :amt, minimum_due = :min, "
            "source = :src, import_job_id = :job, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
        ),
        {**params, "id": existing["id"]},
    )


def write_statement_due(
    db: Session, *, account_id: int, import_job_id: int | None, parser_meta: Mapping[str, Any] | None
) -> bool:
    """A parser that reads a due date puts it in ``parser_meta["payment_due"]``
    (``statement_date``, ``due_date``, optional ``amount_due`` / ``minimum_due``).
    None of the supported card exports print one today (UOB, DBS, Citi; #352)."""
    entry = (parser_meta or {}).get("payment_due")
    if not isinstance(entry, Mapping):
        return False
    try:
        statement_date = _day(entry["statement_date"])
        due_date = _day(entry["due_date"])
    except (KeyError, ValueError, TypeError):
        return False
    write_due(
        db,
        account_id=account_id,
        statement_date=statement_date,
        due_date=due_date,
        amount_due=_num(entry.get("amount_due")),
        minimum_due=_num(entry.get("minimum_due")),
        source="statement",
        import_job_id=import_job_id,
    )
    return True
