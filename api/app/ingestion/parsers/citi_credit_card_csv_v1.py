from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from typing import Any

from app.ingestion.parsers import ParseResult

_DATE_FMT = "%d/%m/%Y"
_FOREIGN_CURRENCY_RE = re.compile(r"\b([A-Z]{3})\s+([+-]?\d+(?:\.\d+)?)\s*$")


def _parse_date(value: str) -> datetime:
    dt = datetime.strptime(value.strip(), _DATE_FMT)
    return dt.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)


def _parse_amount(value: str) -> float:
    return float(value.strip().replace(",", ""))


def _normalize_card_number(value: str) -> str:
    return value.strip().strip("'").strip('"')


def _extract_foreign_currency(description: str) -> tuple[str, str] | None:
    match = _FOREIGN_CURRENCY_RE.search(description)
    if not match:
        return None
    return match.group(1), match.group(2)


def _classify(description: str, amount: float) -> tuple[str, str]:
    desc = description.upper()
    if "PAYMENT - THANK YOU" in desc:
        return "TRANSFER", "CreditCard::Payment"
    if "LATE CHARGE FEE" in desc:
        return "FEE", "CreditCard::Fee"
    if "BILLED FINANCE CHARGES" in desc or "RTL INT CRED ADJ" in desc:
        return "INTEREST", "CreditCard::Interest"
    if amount > 0:
        return "INCOME", "CreditCard::Refund"
    return "EXPENSE", "CreditCard::Purchase"


def parse_citi_credit_card_csv(file_path: str, delimiter: str) -> ParseResult:
    transactions: list[dict[str, Any]] = []

    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            if len(row) < 5:
                continue

            tx_date = _parse_date(row[0])
            description = row[1].strip()
            amount = _parse_amount(row[2])
            card_number = _normalize_card_number(row[4])

            tx_type, category = _classify(description, amount)

            notes_parts = []
            if card_number:
                notes_parts.append(f"card_number={card_number}")
            foreign = _extract_foreign_currency(description)
            if foreign:
                notes_parts.append(f"foreign_currency={foreign[0]} {foreign[1]}")

            transactions.append(
                {
                    "ts": tx_date,
                    "type": tx_type,
                    "amount": amount,
                    "currency": "SGD",
                    "category": category,
                    "merchant_counterparty": description,
                    "notes": "; ".join(notes_parts) if notes_parts else None,
                }
            )

    return ParseResult(
        transactions=transactions,
        positions=[],
        section_counts={"transactions": len(transactions)},
    )
