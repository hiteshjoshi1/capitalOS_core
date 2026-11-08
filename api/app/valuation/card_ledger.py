"""Per-card ledger (#300, D-76): what each card owes, what was paid, and whether each
statement adds up.

A card's **dated balances** are its ``credit_balance`` snapshots (a statement balance,
a UOB "Previous Balance", a DBS limit-derived balance; owed is minus the stored
holder's-view balance). Between two of them the card's own transactions must explain
the change:

    expected = opening + charges + fees + interest - payments - credits
    difference = printed - expected

A difference above ``FLAG_THRESHOLD`` is flagged: positive means the bank says more is
owed than the transactions add up to (a charge, fee or interest you don't have, or a
missing upload), negative means less (a payment or refund not in your transactions, or
a transaction counted twice). After the newest balance, the running balance carries it
forward to today, as ``valuation.facts._credit_card_liability_details`` does.

Amounts are in the card's currency (a transaction in another currency is converted at
its date's rate). Transaction days are the user's calendar (#202): a date-only row is
its date, a timed row its local date.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.valuation import fx
from app.valuation.clock import _app_today, _is_utc_midnight, _local_date, _normalize_ts

FLAG_THRESHOLD = 1.0  # card currency: rounding and same-day ordering stay under this
BANK_PAYMENT = "BANK_PAYMENT"  # a payment to the card found on the bank side (#308)
# A balance this many days or more after the card's last own transaction can't be checked
# against transactions: the charges after it aren't uploaded (#308).
MISSING_TAIL_DAYS = 3
CARD_TYPES = ("EXPENSE", "FEE", "TAX", "INTEREST", "TRANSFER", "INCOME")


@dataclass
class Period:
    """The card between two dated balances (``to_date`` None: the newest, to today)."""

    from_date: date
    to_date: date | None
    opening: float
    charges: float = 0.0  # purchases and taxes, net of their reversals
    fees: float = 0.0
    interest: float = 0.0
    payments: float = 0.0  # positive: what was paid to the card
    credits: float = 0.0  # refunds and other credits (positive)
    transaction_count: int = 0
    printed: float | None = None  # the closing balance the bank printed
    bank_payments: float = 0.0  # payments found on the bank side only (#308), in ``payments``
    # Why a difference is left, when the ledger can tell (#308): e.g. no card transactions
    # after a date, or transactions dated on the closing day that the balance didn't count yet.
    note: str | None = None
    last_card_day: date | None = None  # the newest of the card's own transactions in it

    @property
    def expected(self) -> float:
        return round(self.opening + self.charges + self.fees + self.interest - self.payments - self.credits, 2)

    @property
    def difference(self) -> float | None:
        return None if self.printed is None else round(self.printed - self.expected, 2)

    @property
    def flagged(self) -> bool:
        return self.difference is not None and abs(self.difference) > FLAG_THRESHOLD

    @property
    def paid_in_full(self) -> bool | None:
        """Whether this period's payments covered the opening balance (None: nothing owed)."""
        if self.opening <= 0.005:
            return None
        return self.payments + self.credits >= self.opening - 0.005


@dataclass
class CardLedger:
    account_id: int
    currency: str
    method: str  # running | transactions (no dated balance yet)
    owed_now: float
    last_balance_date: date | None = None
    last_balance: float | None = None
    last_balance_source: str | None = None
    paid_since: float = 0.0  # payments + credits since the newest dated balance
    charges_since: float = 0.0  # charges + fees + interest since it
    fees_interest_ytd: float = 0.0
    last_transaction_date: date | None = None
    periods: list[Period] = field(default_factory=list)  # oldest first

    @property
    def paid_in_full(self) -> bool | None:
        """Whether what the newest dated balance said was owed has been paid since."""
        if self.last_balance is None or self.last_balance <= 0.005:
            return None
        return self.paid_since >= self.last_balance - 0.005

    @property
    def flagged_count(self) -> int:
        return sum(1 for period in self.periods if period.flagged)


def transaction_day(ts: Any) -> date:
    """The user's calendar day of a card transaction (#202)."""
    instant = _normalize_ts(ts) or ts
    if isinstance(instant, date) and not isinstance(instant, datetime):
        return instant
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    if _is_utc_midnight(instant):
        return instant.astimezone(timezone.utc).date()
    return _local_date(instant)


def _add(period: Period, kind: str, amount: float) -> None:
    """Book one transaction (holder's view: negative adds to what's owed)."""
    if kind == BANK_PAYMENT:  # a payment seen only on the paying bank account (#308)
        period.payments += amount
        period.bank_payments += amount
        return
    period.transaction_count += 1
    owed = -amount
    if kind == "FEE":
        period.fees += owed
    elif kind == "INTEREST":
        period.interest += owed
    elif kind == "TRANSFER":
        period.payments += amount
    elif kind == "INCOME":
        period.credits += amount
    elif owed >= 0:
        period.charges += owed
    else:  # a reversed purchase
        period.credits += amount


def build_ledger(
    account_id: int,
    currency: str,
    balances: Iterable[tuple[date, float, str | None]],
    transactions: Iterable[tuple[date, str, float]],
    *,
    today: date,
) -> CardLedger:
    """One card's ledger from its dated balances (date, owed, source) and its
    transactions (day, type, amount in the card's currency, holder's view)."""
    anchors = sorted({day: (day, owed, source) for day, owed, source in balances}.values())
    rows = sorted(transactions)
    year_start = date(today.year, 1, 1)
    fees_interest_ytd = sum(-amount for day, kind, amount in rows if kind in ("FEE", "INTEREST") and year_start <= day <= today)
    last_tx = max((day for day, kind, _amount in rows if kind != BANK_PAYMENT), default=None)
    if not anchors:
        # No balance to start from: the month's net card transactions (an estimate).
        month_start = date(today.year, today.month, 1)
        # The card's own transactions only, as valuation.facts does without a balance.
        owed = sum(-amount for day, kind, amount in rows if month_start <= day <= today and kind != BANK_PAYMENT)
        return CardLedger(
            account_id=account_id, currency=currency, method="transactions", owed_now=round(max(owed, 0.0), 2),
            fees_interest_ytd=round(fees_interest_ytd, 2), last_transaction_date=last_tx,
        )

    def _period(index: int, deferred: set[date]) -> Period:
        """Period ``index``. A boundary day in ``deferred``: its transactions belong to the
        period after it (the balance on that day didn't count them yet)."""
        day, owed, _source = anchors[index]
        next_anchor = anchors[index + 1] if index + 1 < len(anchors) else None
        period = Period(
            from_date=day,
            to_date=next_anchor[0] if next_anchor else None,
            opening=owed,
            printed=next_anchor[1] if next_anchor else None,
        )
        end = next_anchor[0] if next_anchor else today
        for tx_day, kind, amount in rows:
            starts_after = tx_day > day or (tx_day == day and day in deferred)
            ends_by = tx_day < end or (tx_day == end and end not in deferred)
            if starts_after and ends_by:
                _add(period, kind, amount)
                if kind != BANK_PAYMENT and (period.last_card_day is None or tx_day > period.last_card_day):
                    period.last_card_day = tx_day
        return period

    # Same-day ordering (#308): a balance read on a day may not include that day's
    # transactions yet (a DBS limit-derived balance, a payment posted the next day). When a
    # period is flagged and moving its closing day's transactions to the next period makes
    # it add up, they move.
    deferred: set[date] = set()
    for index in range(len(anchors) - 1):
        boundary = anchors[index + 1][0]
        if not any(tx_day == boundary for tx_day, _kind, _amount in rows):
            continue
        if _period(index, deferred).flagged and not _period(index, deferred | {boundary}).flagged:
            deferred.add(boundary)

    periods: list[Period] = []
    for index in range(len(anchors)):
        period = _period(index, deferred)
        if period.to_date is not None and period.to_date in deferred:
            period.note = (
                f"Transactions dated {period.to_date.isoformat()} are counted in the next period: "
                "the balance on that day didn't include them yet."
            )
        if (
            period.flagged
            and period.difference is not None
            and period.difference > 0
            and period.to_date is not None
            and (period.last_card_day is None or (period.to_date - period.last_card_day).days >= MISSING_TAIL_DAYS)
        ):
            to_day = period.to_date.isoformat()
            period.note = (
                f"No card transactions after {period.last_card_day.isoformat()}: charges between then and {to_day} "
                "aren't uploaded, so the balance is higher than the transactions add up to."
                if period.last_card_day is not None
                else f"No card transactions uploaded between {period.from_date.isoformat()} and {to_day}: "
                "its charges are missing, so the balance is higher than the transactions add up to."
            )
        periods.append(period)

    newest = periods[-1]
    newest_day, newest_owed, newest_source = anchors[-1]
    return CardLedger(
        account_id=account_id,
        currency=currency,
        method="running",
        owed_now=newest.expected,
        last_balance_date=newest_day,
        last_balance=round(newest_owed, 2),
        last_balance_source=newest_source,
        paid_since=round(newest.payments + newest.credits, 2),
        charges_since=round(newest.charges + newest.fees + newest.interest, 2),
        fees_interest_ytd=round(fees_interest_ytd, 2),
        last_transaction_date=last_tx,
        periods=periods,
    )


def card_ledgers(db: Session, current_user_id: int, *, today: date | None = None) -> list[CardLedger]:
    """Every open card's ledger, by account id."""
    today = today or _app_today()
    cards = db.execute(
        text(
            """
            SELECT a.id AS account_id, UPPER(COALESCE(a.currency, 'SGD')) AS currency, a.closed_on
            FROM accounts a
            WHERE a.account_type = 'CREDIT_CARD' AND """
            + account_scope_sql("a")
            + " ORDER BY a.id"
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    if not cards:
        return []
    ids = [int(card["account_id"]) for card in cards]
    balance_rows = db.execute(
        text(
            """
            SELECT abs.account_id, abs.as_of_date, abs.currency, abs.balance_local, abs.metadata_json
            FROM account_balance_snapshots abs
            JOIN accounts a ON a.id = abs.account_id
            WHERE abs.balance_type = 'credit_balance'
              AND abs.authority_status = 'authoritative'
              AND abs.as_of_date <= :today
              AND a.account_type = 'CREDIT_CARD' AND """
            + account_scope_sql("a")
        ),
        {"today": today, "current_user_id": current_user_id},
    ).mappings().all()
    tx_rows = db.execute(
        text(
            """
            SELECT t.account_id, t.ts, t.type, t.amount, t.currency
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.account_type = 'CREDIT_CARD'
              AND t.type IN ('EXPENSE','FEE','TAX','INTEREST','TRANSFER','INCOME')
              AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()

    currency_of = {int(card["account_id"]): str(card["currency"]) for card in cards}
    foreign = [row for row in tx_rows if str(row["currency"] or "").upper() not in ("", currency_of.get(int(row["account_id"]), ""))]
    rates_by_card_currency: dict[str, Mapping[date, Mapping[str, float]]] = {}
    for card_currency in {currency_of[int(row["account_id"])] for row in foreign}:
        rows = [row for row in foreign if currency_of[int(row["account_id"])] == card_currency]
        rates_by_card_currency[card_currency] = fx.get_rates_by_date(
            [transaction_day(row["ts"]) for row in rows], card_currency, {str(row["currency"]).upper() for row in rows}
        )

    def _in_card_currency(row: Mapping[str, Any]) -> float:
        card_currency = currency_of[int(row["account_id"])]
        amount = float(row["amount"] or 0.0)
        tx_currency = str(row["currency"] or card_currency).upper()
        if tx_currency == card_currency:
            return amount
        rates = rates_by_card_currency.get(card_currency, {}).get(fx.rate_date(transaction_day(row["ts"])), {})
        return amount * rates.get(tx_currency, 0.0)

    # Payments made from a bank account that the card's own file doesn't list (#308).
    from app.valuation.card_payments import bank_card_payments, payments_missing_from_card

    card_paid = [
        (int(row["account_id"]), transaction_day(row["ts"]), _in_card_currency(row))
        for row in tx_rows
        if str(row["type"]).upper() in ("TRANSFER", "INCOME") and float(row["amount"] or 0.0) > 0
    ]
    from_bank: dict[int, list[tuple[date, str, float]]] = {}
    for payment in payments_missing_from_card(
        [p for p in bank_card_payments(db, current_user_id) if p.card_account_id in currency_of], card_paid
    ):
        card_currency = currency_of[payment.card_account_id]
        amount = payment.amount
        if payment.currency and payment.currency != card_currency:
            rates: Mapping[str, float] = fx.get_rates_by_date([payment.day], card_currency, {payment.currency}).get(
                fx.rate_date(payment.day), {}
            )
            amount = payment.amount * rates.get(payment.currency, 0.0)
        if amount > 0:
            from_bank.setdefault(payment.card_account_id, []).append((payment.day, BANK_PAYMENT, round(amount, 2)))

    out: list[CardLedger] = []
    for card in cards:
        account_id = int(card["account_id"])
        closed_on = card["closed_on"]
        if closed_on is not None and (closed_on if isinstance(closed_on, date) else date.fromisoformat(str(closed_on)[:10])) < today:
            continue
        balances: dict[date, list[Any]] = {}
        for row in balance_rows:
            if int(row["account_id"]) != account_id:
                continue
            day = row["as_of_date"] if isinstance(row["as_of_date"], date) else date.fromisoformat(str(row["as_of_date"])[:10])
            entry = balances.setdefault(day, [0.0, None])
            entry[0] += -float(row["balance_local"] or 0.0)  # owed is minus the holder's-view balance
            meta = row["metadata_json"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except ValueError:
                    meta = None
            if isinstance(meta, dict) and meta.get("source"):
                entry[1] = str(meta["source"])
        transactions = [
            (transaction_day(row["ts"]), str(row["type"]).upper(), _in_card_currency(row))
            for row in tx_rows
            if int(row["account_id"]) == account_id
        ] + from_bank.get(account_id, [])
        out.append(
            build_ledger(
                account_id,
                currency_of[account_id],
                [(day, round(owed, 2), source) for day, (owed, source) in balances.items()],
                transactions,
                today=today,
            )
        )
    return out
