from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

import pandas as pd

from app.ingestion.parsers import ParseResult
from app.ingestion.parsers.uob_account_xls_v1 import (
    _clean_text,
    _parse_amount,
    _parse_date,
    _pick_engine,
)


UOB_CREDIT_CARD_XLS_HEADERS = (
    "transaction date",
    "posting date",
    "description",
    "foreign currency type",
    "transaction amount(foreign)",
    "local currency type",
    "transaction amount(local)",
)
UOB_DEFAULT_CURRENCY = "SGD"
_HEADER_COLUMNS = set(UOB_CREDIT_CARD_XLS_HEADERS)
_FOREIGN_CURRENCY_RE = re.compile(r"\b([A-Z]{3})\s+([+-]?\d+(?:\.\d+)?)\s*$")
_REFERENCE_RE = re.compile(r"REF\s+NO:\s*([A-Z0-9]+)", re.IGNORECASE)
_PAYMENT_KEYWORDS = (
    "GIRO PAYMENT",
    "PAYMENT - THANK YOU",
    "AUTO PAYMENT",
    "CARD PAYMENT",
)
_FEE_KEYWORDS = (
    "ANNUAL FEE",
    "LATE CHARGE FEE",
    "SERVICE FEE",
)
_INTEREST_KEYWORDS = (
    "FINANCE CHARGE",
    "FINANCE CHARGES",
    "INTEREST",
)


@dataclass
class ParsedRow:
    row_index: int
    ts: datetime
    posting_date: datetime | None
    description: str
    foreign_currency: str | None
    foreign_amount: float | None
    local_currency: str | None
    local_amount: float | None


def _find_header_row(df: pd.DataFrame) -> int | None:
    for idx, row in df.iterrows():
        values = {_clean_text(value).lower() for value in row.tolist() if _clean_text(value)}
        if _HEADER_COLUMNS.issubset(values):
            return int(idx)
    return None


def _extract_metadata(df: pd.DataFrame, header_row: int) -> dict[str, Any]:
    currency = None
    account_number = None
    account_type = None
    statement_date = None
    statement_balance = None

    for idx in range(header_row):
        row_values = [_clean_text(value) for value in df.iloc[idx].tolist()]
        if not any(row_values):
            continue
        label = row_values[0].lower()
        non_empty = [value for value in row_values[1:] if value]
        first_value = non_empty[0] if non_empty else None

        if label == "account number:":
            account_number = first_value or account_number
            if len(non_empty) > 1 and re.fullmatch(r"[A-Z]{3}", non_empty[1]):
                currency = non_empty[1]
        elif label == "account type:":
            account_type = first_value or account_type
        elif label == "statement date:":
            statement_date = _parse_date(first_value)
        elif label == "statement balance:":
            statement_balance = _parse_amount(first_value)
            if len(non_empty) > 1 and re.fullmatch(r"[A-Z]{3}", non_empty[1]):
                currency = non_empty[1]
        elif not currency:
            for value in row_values:
                if re.fullmatch(r"[A-Z]{3}", value):
                    currency = value
                    break

    return {
        "account_number": account_number,
        "account_type": account_type,
        "currency": (currency or UOB_DEFAULT_CURRENCY).upper(),
        "statement_date": statement_date,
        "statement_balance": statement_balance,
    }


def _normalize_columns(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for column in columns:
        key = column.strip().lower()
        if key in _HEADER_COLUMNS:
            mapping[key] = column
    return mapping


def _append_description(existing: str, extra: str) -> str:
    if not extra:
        return existing
    if not existing:
        return extra
    return f"{existing}\n{extra}"


def _collapse_rows(df: pd.DataFrame, col_map: dict[str, str]) -> list[ParsedRow]:
    grouped: list[ParsedRow] = []
    current: ParsedRow | None = None

    for row_index, row in df.iterrows():
        tx_date = _parse_date(row.get(col_map["transaction date"]))
        posting_date = _parse_date(row.get(col_map["posting date"]))
        description = _clean_text(row.get(col_map["description"]))
        foreign_currency = _clean_text(row.get(col_map["foreign currency type"])).upper() or None
        foreign_amount = _parse_amount(row.get(col_map["transaction amount(foreign)"]))
        local_currency = _clean_text(row.get(col_map["local currency type"])).upper() or None
        local_amount = _parse_amount(row.get(col_map["transaction amount(local)"]))

        if tx_date is None:
            if current is None:
                continue
            if description:
                current.description = _append_description(current.description, description)
            if posting_date is not None:
                current.posting_date = posting_date
            if foreign_currency:
                current.foreign_currency = foreign_currency
            if foreign_amount is not None:
                current.foreign_amount = foreign_amount
            if local_currency:
                current.local_currency = local_currency
            if local_amount is not None:
                current.local_amount = local_amount
            continue

        current = ParsedRow(
            row_index=int(row_index),
            ts=tx_date,
            posting_date=posting_date,
            description=description,
            foreign_currency=foreign_currency,
            foreign_amount=foreign_amount,
            local_currency=local_currency,
            local_amount=local_amount,
        )
        grouped.append(current)

    return grouped


def _extract_foreign_currency(row: ParsedRow) -> tuple[str, str] | None:
    if row.foreign_currency and row.foreign_amount not in (None, 0):
        return row.foreign_currency, f"{row.foreign_amount:.2f}"
    match = _FOREIGN_CURRENCY_RE.search(row.description)
    if not match:
        return None
    return match.group(1), match.group(2)


def _classify(description: str, amount: float, merchant_counterparty: str | None = None) -> tuple[str, str]:
    from app.ingestion.parsers.merchant_categorizer import classify_merchant

    desc = description.upper()
    if any(keyword in desc for keyword in _PAYMENT_KEYWORDS):
        return "TRANSFER", "CreditCard::Payment"
    if any(keyword in desc for keyword in _FEE_KEYWORDS):
        return "FEE", "CreditCard::Fee"
    if any(keyword in desc for keyword in _INTEREST_KEYWORDS):
        return "INTEREST", "CreditCard::Interest"
    if amount > 0:
        return "INCOME", "CreditCard::Refund"
    return "EXPENSE", classify_merchant(description, merchant_counterparty)


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _transaction_fields(description: str) -> tuple[str, str | None]:
    lines = [_normalize_line(line) for line in description.splitlines() if line.strip()]
    if not lines:
        return "UOB", None
    merchant_counterparty = lines[0]
    notes = " | ".join(lines)
    return merchant_counterparty, notes


def _build_notes(row: ParsedRow, metadata: dict[str, Any]) -> str | None:
    _, description_notes = _transaction_fields(row.description)
    notes_parts: list[str] = []
    if metadata["account_number"]:
        notes_parts.append(f"card_number={metadata['account_number']}")
    if row.posting_date is not None:
        notes_parts.append(f"posting_date={row.posting_date.date().isoformat()}")
    reference_match = _REFERENCE_RE.search(row.description)
    if reference_match:
        notes_parts.append(f"reference={reference_match.group(1)}")
    foreign_currency = _extract_foreign_currency(row)
    if foreign_currency:
        notes_parts.append(f"foreign_currency={foreign_currency[0]} {foreign_currency[1]}")
    if description_notes:
        notes_parts.append(f"description={description_notes}")
    return "; ".join(notes_parts) if notes_parts else None


def parse_uob_credit_card_xls(file_path: str) -> ParseResult:
    empty_result = ParseResult(
        transactions=[],
        positions=[],
        section_counts={"transactions": 0},
        parser_meta={
            "sheet_name": None,
            "header_row_index": None,
            "account_number": None,
            "account_type": None,
            "currency": None,
            "statement_date": None,
            "statement_balance": None,
        },
    )

    try:
        xls = pd.ExcelFile(file_path, engine=_pick_engine(file_path))
        sheet_name = xls.sheet_names[0]
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    except Exception:
        return empty_result

    raw = raw.dropna(how="all")
    if raw.empty:
        return empty_result

    header_row = _find_header_row(raw)
    if header_row is None:
        return ParseResult(
            transactions=[],
            positions=[],
            section_counts={"transactions": 0},
            parser_meta={**empty_result.parser_meta, "sheet_name": sheet_name},
        )

    metadata = _extract_metadata(raw, header_row)
    df = pd.read_excel(xls, sheet_name=sheet_name, header=header_row).dropna(how="all")
    columns = [str(column).strip() for column in df.columns.tolist()]
    col_map = _normalize_columns(columns)

    if not _HEADER_COLUMNS.issubset(col_map):
        return ParseResult(
            transactions=[],
            positions=[],
            section_counts={"transactions": 0},
            parser_meta={**metadata, "sheet_name": sheet_name, "header_row_index": header_row},
        )

    grouped_rows = _collapse_rows(df, col_map)
    transactions: list[dict[str, Any]] = []

    for row in grouped_rows:
        merchant_counterparty, _ = _transaction_fields(row.description)
        local_amount = row.local_amount or 0.0
        if merchant_counterparty.upper() == "PREVIOUS BALANCE" or local_amount == 0.0:
            continue
        amount = -local_amount
        tx_type, category = _classify(row.description, amount, merchant_counterparty)
        transactions.append(
            {
                "ts": row.ts,
                "type": tx_type,
                "amount": amount,
                "currency": row.local_currency or metadata["currency"],
                "category": category,
                "merchant_counterparty": merchant_counterparty,
                "notes": _build_notes(row, metadata),
            }
        )

    parser_meta = {
        "sheet_name": sheet_name,
        "header_row_index": header_row,
        "account_number": metadata["account_number"],
        "account_type": metadata["account_type"],
        "currency": metadata["currency"],
        "statement_date": metadata["statement_date"].isoformat() if metadata["statement_date"] else None,
        "statement_balance": metadata["statement_balance"],
    }
    return ParseResult(
        transactions=transactions,
        positions=[],
        section_counts={"transactions": len(transactions)},
        parser_meta=parser_meta,
    )
