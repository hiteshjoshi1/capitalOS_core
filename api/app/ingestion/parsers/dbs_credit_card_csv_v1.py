from __future__ import annotations

import csv
from datetime import datetime, timezone
import re
from typing import Any

from app.ingestion.parsers import ParseResult


DBS_CREDIT_CARD_CSV_HEADERS = (
    "transaction date",
    "transaction posting date",
    "transaction description",
    "transaction type",
    "payment type",
    "transaction status",
    "debit amount",
    "credit amount",
)

_DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")
_CARD_DIGITS_RE = re.compile(r"(?:\d{4}[- ]?){3}\d{4}")
_PAYMENT_KEYWORDS = (
    "PAYMENT",
    "GIRO",
    "IBG",
    "AXS",
    "BILL PAYMENT",
)
_REFUND_KEYWORDS = (
    "REFUND",
    "REVERSAL",
    "REBATE",
    "CREDIT ADJUSTMENT",
    "CREDIT",
)
_INTEREST_KEYWORDS = (
    "FINANCE CHARGE",
    "FINANCE CHARGES",
    "INTEREST",
)


def _parse_date(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            continue
    return None


def _parse_amount(value: str) -> float | None:
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_money(value: str) -> float | None:
    cleaned = value.strip().upper().replace("SGD", "").replace(",", "").strip()
    return _parse_amount(cleaned)


def _normalize_header(row: list[str]) -> list[str]:
    return [cell.strip().lower() for cell in row]


def _find_header_row(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        normalized = _normalize_header(row)
        if normalized[: len(DBS_CREDIT_CARD_CSV_HEADERS)] == list(DBS_CREDIT_CARD_CSV_HEADERS):
            return idx
    return None


def _safe_card_metadata(value: str) -> tuple[str | None, str | None, str | None]:
    text = value.strip()
    if not text:
        return None, None, None

    match = _CARD_DIGITS_RE.search(text)
    if not match:
        return text, None, None

    digits = re.sub(r"\D", "", match.group(0))
    last_four = digits[-4:] if len(digits) >= 4 else None
    display_name = text[: match.start()].strip(" -") or None
    masked = f"****-****-****-{last_four}" if last_four else None
    return display_name, last_four, masked


def _extract_metadata(rows: list[list[str]], header_row: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "card_display_name": None,
        "card_last_four": None,
        "card_masked": None,
        "credit_limit": None,
        "available_limit": None,
        "transactions_as_at": None,
        "currency": "SGD",
    }

    for row in rows[:header_row]:
        if not row or all(not cell.strip() for cell in row):
            continue
        label = row[0].strip().lower().rstrip(":")
        value = row[1].strip() if len(row) > 1 else ""

        if label == "card transaction details for":
            card_display_name, last_four, masked = _safe_card_metadata(value)
            metadata["card_display_name"] = card_display_name
            metadata["card_last_four"] = last_four
            metadata["card_masked"] = masked
        elif label == "transactions as at":
            parsed = _parse_date(value)
            metadata["transactions_as_at"] = parsed.isoformat() if parsed else None
        elif label == "credit limit":
            metadata["credit_limit"] = _parse_money(value)
        elif label == "available limit":
            metadata["available_limit"] = _parse_money(value)

    return metadata


def _row_to_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    return {headers[i]: row[i].strip() if i < len(row) else "" for i in range(len(headers))}


def _classify(description: str, transaction_type: str, amount: float) -> tuple[str, str]:
    desc = description.upper()
    row_type = transaction_type.upper()

    if "GOODS AND SERVICES TAX" in row_type or "GST" in desc:
        return "TAX", "CreditCard::Tax"
    if any(keyword in desc for keyword in _INTEREST_KEYWORDS):
        return "INTEREST", "CreditCard::Interest"
    if "FEES" in row_type or "CHARGES" in row_type:
        return "FEE", "CreditCard::Fee"
    if any(keyword in desc for keyword in _PAYMENT_KEYWORDS):
        return "TRANSFER", "CreditCard::Payment"
    if "PAYMENT" in row_type:
        return "TRANSFER", "CreditCard::Payment"
    if amount > 0 and any(keyword in desc for keyword in _REFUND_KEYWORDS):
        return "INCOME", "CreditCard::Refund"
    if amount > 0:
        return "INCOME", "CreditCard::Credit"
    return "EXPENSE", "CreditCard::Purchase"


def _build_notes(record: dict[str, str], metadata: dict[str, Any], posting_date: datetime | None) -> str | None:
    parts: list[str] = []
    if posting_date is not None:
        parts.append(f"posting_date={posting_date.date().isoformat()}")
    if metadata.get("card_last_four"):
        parts.append(f"card_last4={metadata['card_last_four']}")
    if metadata.get("card_masked"):
        parts.append(f"card_masked={metadata['card_masked']}")
    if record.get("Payment Type"):
        parts.append(f"payment_type={record['Payment Type']}")
    if record.get("Transaction Status"):
        parts.append(f"status={record['Transaction Status']}")
    return "; ".join(parts) if parts else None


def parse_dbs_credit_card_csv(file_path: str, delimiter: str = ",") -> ParseResult:
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=delimiter))

    header_row = _find_header_row(rows)
    if header_row is None:
        return ParseResult(
            transactions=[],
            positions=[],
            section_counts={"transactions": 0},
            parser_meta={},
        )

    headers = [cell.strip() for cell in rows[header_row]]
    metadata = _extract_metadata(rows, header_row)
    transactions: list[dict[str, Any]] = []
    row_count = 0

    for row in rows[header_row + 1 :]:
        if not row or all(not cell.strip() for cell in row):
            continue
        row_count += 1
        record = _row_to_dict(headers, row)
        tx_date = _parse_date(record.get("Transaction Date", ""))
        if tx_date is None:
            continue

        debit = _parse_amount(record.get("Debit Amount", ""))
        credit = _parse_amount(record.get("Credit Amount", ""))
        if debit is not None and debit > 0:
            amount = -debit
        elif credit is not None and credit > 0:
            amount = credit
        else:
            continue

        description = record.get("Transaction Description", "").strip()
        tx_type, category = _classify(description, record.get("Transaction Type", ""), amount)
        posting_date = _parse_date(record.get("Transaction Posting Date", ""))
        transactions.append(
            {
                "ts": tx_date,
                "type": tx_type,
                "amount": amount,
                "currency": metadata["currency"],
                "category": category,
                "merchant_counterparty": description or "DBS",
                "notes": _build_notes(record, metadata, posting_date),
            }
        )

    return ParseResult(
        transactions=transactions,
        positions=[],
        section_counts={"transactions": row_count},
        parser_meta=metadata,
    )
