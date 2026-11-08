from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from typing import Any

import pandas as pd

from app.ingestion.card_fees import CARD_FEE_CATEGORY, is_conversion_fee
from app.ingestion.masking import mask_account_numbers
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
    # A "Previous Balance" line (#299): a statement-period boundary, not a transaction.
    is_balance_marker: bool = False


# The shortest run of rows that counts as the export repeating itself (#299). Two identical
# same-day purchases in a row are real; three or more identical rows (dates, posting dates,
# descriptions and amounts) repeated back to back are the export printing a period twice.
_MIN_REPEATED_RUN = 3


def _row_signature(row: ParsedRow) -> tuple[Any, ...]:
    return (
        row.is_balance_marker,
        row.ts,
        row.posting_date,
        row.description,
        row.foreign_currency,
        row.foreign_amount,
        row.local_currency,
        row.local_amount,
    )


def _drop_repeated_runs(rows: list[ParsedRow]) -> list[ParsedRow]:
    """Remove a run of rows that repeats the run just before it (#299).

    UOB's card history export can print the latest statement period twice, back to back.
    The rows are identical, so the runner's per-occurrence fingerprint (two same-day coffees)
    kept both copies. A run of at least _MIN_REPEATED_RUN rows followed immediately by an
    identical copy keeps the first copy only; the longest repeat is removed first.
    """
    signatures = [_row_signature(row) for row in rows]
    changed = True
    while changed:
        changed = False
        n = len(signatures)
        for length in range(n // 2, _MIN_REPEATED_RUN - 1, -1):
            for start in range(0, n - 2 * length + 1):
                if signatures[start:start + length] == signatures[start + length:start + 2 * length]:
                    del rows[start + length:start + 2 * length]
                    del signatures[start + length:start + 2 * length]
                    changed = True
                    break
            if changed:
                break
    return rows


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


@dataclass
class CollapsedRows:
    rows: list[ParsedRow]
    # (index into ``rows`` where the period starts, the "Previous Balance" it opens with):
    # the rows from that index up to the next boundary are one statement period, newest
    # first, and the amount is what the statement before that period printed (#300).
    boundaries: list[tuple[int, float]] = field(default_factory=list)


def _is_previous_balance(description: str) -> bool:
    return _normalize_line(description).upper() == "PREVIOUS BALANCE"


def _collapse_rows(df: pd.DataFrame, col_map: dict[str, str]) -> CollapsedRows:
    grouped: list[ParsedRow] = []
    boundaries: list[tuple[int, float]] = []
    current: ParsedRow | None = None

    for row_index, row in df.iterrows():
        tx_date = _parse_date(row.get(col_map["transaction date"]))
        posting_date = _parse_date(row.get(col_map["posting date"]))
        description = _clean_text(row.get(col_map["description"]))
        foreign_currency = _clean_text(row.get(col_map["foreign currency type"])).upper() or None
        foreign_amount = _parse_amount(row.get(col_map["transaction amount(foreign)"]))
        local_currency = _clean_text(row.get(col_map["local currency type"])).upper() or None
        local_amount = _parse_amount(row.get(col_map["transaction amount(local)"]))

        if tx_date is None and _is_previous_balance(description):
            # A period boundary (#299). It used to be merged into the transaction above it,
            # replacing that row's amount with the previous balance.
            grouped.append(
                ParsedRow(
                    row_index=int(row_index),
                    ts=datetime.min,
                    posting_date=None,
                    description=description,
                    foreign_currency=None,
                    foreign_amount=None,
                    local_currency=local_currency,
                    local_amount=local_amount,
                    is_balance_marker=True,
                )
            )
            current = None
            continue

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

    # #299 first: a period the export printed twice is kept once (markers included), then
    # #300's boundaries are read from the cleaned rows, so balances aren't doubled either.
    rows: list[ParsedRow] = []
    for row in _drop_repeated_runs(grouped):
        if row.is_balance_marker:
            if row.local_amount is not None:
                boundaries.append((len(rows), row.local_amount))
            continue
        rows.append(row)
    return CollapsedRows(rows=rows, boundaries=boundaries)


def _statement_balances(
    collapsed: CollapsedRows, statement_balance: float | None, statement_date: datetime | None
) -> list[dict[str, Any]]:
    """The dated balances the file prints (#300). Each "Previous Balance" opens the
    rows after it (newest first) up to the next one: it is what the statement before
    that period said was owed, dated the day before the period's first transaction
    (that statement's own date isn't in the file). The header's "Statement Balance":
    - a statement (one "Statement Date"): what's owed on that date, the closing balance;
    - a history export (a date range, no single date): the newest statement, which
      opens the newest (unbilled) period, the rows before the first "Previous Balance",
      dated the day before them.
    Owed is positive. One per date; the first seen wins (a repeated block repeats them)."""
    rows = collapsed.rows
    starts = [index for index, _amount in collapsed.boundaries]
    periods: list[tuple[list[ParsedRow], float, str]] = []
    out: dict[str, dict[str, Any]] = {}
    if statement_balance is not None and statement_date is not None:
        as_of = statement_date.date().isoformat()
        out[as_of] = {"as_of_date": as_of, "owed": round(float(statement_balance), 2), "source": "statement_balance"}
    elif statement_balance is not None and starts:
        periods.append((rows[: starts[0]], statement_balance, "statement_balance"))
    for position, (start, amount) in enumerate(collapsed.boundaries):
        end = starts[position + 1] if position + 1 < len(starts) else len(rows)
        periods.append((rows[start:end], amount, "previous_balance"))
    for period_rows, owed, source in periods:
        if not period_rows:
            continue
        first_day = min(row.ts for row in period_rows)
        as_of = (first_day - timedelta(days=1)).date().isoformat()
        out.setdefault(as_of, {"as_of_date": as_of, "owed": round(float(owed), 2), "source": source})
    return [out[key] for key in sorted(out)]


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
    if is_conversion_fee(desc):  # a foreign transaction / conversion fee (#308)
        return "FEE", CARD_FEE_CATEGORY
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
        # The last 4 only (#301); the full number stays in parser_meta for the statement check (#180).
        notes_parts.append(f"card_number={mask_account_numbers(str(metadata['account_number']))}")
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
            "statement_balances": [],
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

    collapsed = _collapse_rows(df, col_map)
    grouped_rows = collapsed.rows
    transactions: list[dict[str, Any]] = []

    for row in grouped_rows:
        if row.is_balance_marker:
            continue
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
        "statement_balances": _statement_balances(collapsed, metadata["statement_balance"], metadata["statement_date"]),
    }
    return ParseResult(
        transactions=transactions,
        positions=[],
        section_counts={"transactions": len(transactions)},
        parser_meta=parser_meta,
    )
