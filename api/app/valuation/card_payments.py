"""Payments to the user's own cards, seen from the bank side (#308, D-77).

A bank statement names the card it pays: DBS bill payments carry the card's number
("BILL <code>-<card number> ..."), a UOB GIRO to the card centre its masked number
("COLL ************1234"). A bank outflow whose text holds a card number ending in one of
the user's cards' last 4 is a payment to that card:

- **Cash flow** doesn't count it as spending: the card's own charges already are, so the
  payment is a move between the user's own accounts (it was counted twice).
- **The card's ledger** (#300) counts it as a payment when the card's own file doesn't list
  it (a DBS card export lists only its last statement's transactions): a card payment of the
  same amount within ``MATCH_DAYS`` days means the card file has it, so it isn't added again.

A card's last 4 come from its own transactions' notes (``card_last4=``, ``card_number=``,
``card_masked=``, written by the card parsers). A full digit run must be a valid card number
(Luhn) of 15 or 16 digits; a masked run (``*``/``X``) is matched on its last 4 alone.
Ambiguous last 4 (two cards share them) match nothing.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql

MATCH_DAYS = 5  # as the Overview bridge's transfer matching (bridge.TRANSFER_MATCH_DAYS)

_LAST4_IN_NOTES = re.compile(r"card_(?:last4=|number=[*X]+|masked=[*X-]+)(\d{4})", re.IGNORECASE)
# A card number in a bank line: 4-4-4-4 (spaces or dashes allowed) or a run of 15-16, either
# all digits or masked with * / X, not part of a longer number.
_CARD_RUN = re.compile(r"(?<![0-9*X])((?:[0-9*X]{4}[- ]?){3}[0-9]{3,4}|[0-9*X]{8,12}[0-9]{4})(?![0-9])", re.IGNORECASE)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def card_numbers_in(text_value: str | None) -> list[str]:
    """The last 4 of each card number a bank line mentions."""
    out: list[str] = []
    for match in _CARD_RUN.finditer(str(text_value or "")):
        token = re.sub(r"[- ]", "", match.group(1))
        if token.isdigit():
            if len(token) not in (15, 16) or not _luhn_ok(token):
                continue
        elif not re.search(r"[*X]{4,}", token, re.IGNORECASE):
            continue
        out.append(token[-4:])
    return out


def _text_of(row: Mapping[str, Any]) -> str:
    notes = str(row.get("notes") or "").split(" | fp:", 1)[0]
    return f"{row.get('merchant_counterparty') or ''} {notes}"


def card_last4s(db: Session, current_user_id: int) -> dict[str, int]:
    """Last 4 -> the user's card account, from each card's own transaction notes.
    Last 4 shared by two cards are left out (ambiguous)."""
    rows = db.execute(
        text(
            """
            SELECT t.account_id, t.notes
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.account_type = 'CREDIT_CARD' AND t.notes IS NOT NULL AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    per_card: dict[int, Counter[str]] = {}
    for row in rows:
        match = _LAST4_IN_NOTES.search(str(row["notes"]))
        if match:
            per_card.setdefault(int(row["account_id"]), Counter())[match.group(1)] += 1
    owners: dict[str, set[int]] = {}
    for account_id, counts in per_card.items():
        for last4 in counts:
            owners.setdefault(last4, set()).add(account_id)
    return {last4: next(iter(ids)) for last4, ids in owners.items() if len(ids) == 1}


def paid_card(row: Mapping[str, Any], last4s: Mapping[str, int]) -> int | None:
    """The card a bank outflow pays, or None."""
    if str(row.get("account_type") or "").upper() != "BANK" or float(row.get("amount") or 0.0) >= 0:
        return None
    cards = {last4s[last4] for last4 in card_numbers_in(_text_of(row)) if last4 in last4s}
    return next(iter(cards)) if len(cards) == 1 else None


def mark_own_card_payments(rows: Iterable[Mapping[str, Any]], last4s: Mapping[str, int]) -> list[dict[str, Any]]:
    """Cash-flow rows with ``own_card_payment``: the card a bank outflow pays, or None."""
    out = []
    for row in rows:
        item = dict(row)
        item["own_card_payment"] = paid_card(item, last4s) if last4s else None
        out.append(item)
    return out


@dataclass(frozen=True)
class BankCardPayment:
    bank_transaction_id: int
    card_account_id: int
    day: date
    amount: float  # paid to the card, positive, in ``currency``
    currency: str


def bank_card_payments(db: Session, current_user_id: int, last4s: Mapping[str, int] | None = None) -> list[BankCardPayment]:
    """Every bank outflow that pays one of the user's cards."""
    from app.valuation.card_ledger import transaction_day  # avoid a cycle

    last4s = card_last4s(db, current_user_id) if last4s is None else last4s
    if not last4s:
        return []
    rows = db.execute(
        text(
            """
            SELECT t.id, t.ts, t.amount, t.currency, t.merchant_counterparty, t.notes, a.account_type
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.account_type = 'BANK' AND t.amount < 0 AND """
            + account_scope_sql("a")
            + " ORDER BY t.ts, t.id"
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    out = []
    for row in rows:
        card = paid_card(row, last4s)
        if card is not None:
            out.append(
                BankCardPayment(
                    bank_transaction_id=int(row["id"]),
                    card_account_id=card,
                    day=transaction_day(row["ts"]),
                    amount=round(-float(row["amount"]), 2),
                    currency=str(row["currency"] or "").upper(),
                )
            )
    return out


def payments_missing_from_card(
    bank_payments: Iterable[BankCardPayment],
    card_payments: Iterable[tuple[int, date, float]],
) -> list[BankCardPayment]:
    """The bank-side payments the card's own file doesn't list. ``card_payments``:
    (card account, day, amount paid, positive). Each card-side payment explains one bank
    payment of the same amount within MATCH_DAYS days, nearest first."""
    bank = sorted(bank_payments, key=lambda p: (p.day, p.bank_transaction_id))
    card = [(int(account_id), day, round(float(amount), 2)) for account_id, day, amount in card_payments]
    # Closest pairs first, so two same-amount payments a few days apart each find their own.
    pairs = sorted(
        (abs((day - payment.day).days), b, c)
        for b, payment in enumerate(bank)
        for c, (account_id, day, amount) in enumerate(card)
        if account_id == payment.card_account_id
        and abs(amount - payment.amount) < 0.005
        and abs((day - payment.day).days) <= MATCH_DAYS
    )
    matched_bank: set[int] = set()
    used_card: set[int] = set()
    for _distance, b, c in pairs:
        if b in matched_bank or c in used_card:
            continue
        matched_bank.add(b)
        used_card.add(c)
    return [payment for b, payment in enumerate(bank) if b not in matched_bank]


def missing_bank_payments(db: Session, current_user_id: int) -> list[BankCardPayment]:
    """Bank-side payments to the user's cards that the cards' own files don't list (#308),
    matched on the amount as stored (a card and the account paying it share a currency)."""
    from app.valuation.card_ledger import transaction_day  # avoid a cycle

    bank = bank_card_payments(db, current_user_id)
    if not bank:
        return []
    rows = db.execute(
        text(
            """
            SELECT t.account_id, t.ts, t.amount
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.account_type = 'CREDIT_CARD' AND t.type IN ('TRANSFER', 'INCOME') AND t.amount > 0 AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    return payments_missing_from_card(
        bank, [(int(row["account_id"]), transaction_day(row["ts"]), float(row["amount"])) for row in rows]
    )
