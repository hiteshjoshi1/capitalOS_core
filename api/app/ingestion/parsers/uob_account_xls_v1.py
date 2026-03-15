from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

import pandas as pd

from app.ingestion.parsers import ParseResult


UOB_ACCOUNT_XLS_HEADERS = (
    "transaction date",
    "transaction description",
    "withdrawal",
    "deposit",
    "available balance",
)
UOB_DEFAULT_CURRENCY = "SGD"
_HEADER_COLUMNS = set(UOB_ACCOUNT_XLS_HEADERS)
_TRANSFER_KEYWORDS = (
    "PAYNOW",
    "FAST TRANSFER",
    "OWN ACCOUNT",
    "INTERNAL TRANSFER",
    "CARD CENTRE",
    "CARD PAYMENT",
    "CREDIT CARD",
    " TRF ",
)


@dataclass
class ParsedRow:
    row_index: int
    ts: datetime
    description: str
    withdrawal: float | None
    deposit: float | None
    balance: float | None


def _pick_engine(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            magic = f.read(8)
        # Some bank exports have .xls extension but are actually XLSX (ZIP container).
        if magic.startswith(b"PK\x03\x04"):
            return "openpyxl"
        if magic.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
            return "xlrd"
    except OSError:
        pass
    lower = path.lower()
    if lower.endswith(".xls"):
        return "xlrd"
    if lower.endswith(".xlsx"):
        return "openpyxl"
    return None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _parse_amount(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace(",", "")
    if cleaned == "":
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if isinstance(value, (int, float)) and not pd.isna(value):
        try:
            dt = pd.to_datetime(value, unit="D", origin="1899-12-30").to_pydatetime()
            return dt.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)
        except (TypeError, ValueError, OverflowError):
            return None
    text = _clean_text(value)
    if text == "":
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            continue
    return None


def _parse_statement_period(value: str) -> tuple[datetime | None, datetime | None]:
    text = value.strip()
    if not text:
        return None, None
    parts = re.split(r"\s+to\s+", text, flags=re.IGNORECASE)
    if len(parts) != 2:
        dt = _parse_date(text)
        return dt, dt
    return _parse_date(parts[0]), _parse_date(parts[1])


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
    statement_period = None

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
        elif label == "statement period:":
            statement_period = first_value or statement_period
        elif not currency:
            for value in row_values:
                if re.fullmatch(r"[A-Z]{3}", value):
                    currency = value
                    break

    start, end = _parse_statement_period(statement_period or "")
    return {
        "account_number": account_number,
        "account_type": account_type,
        "currency": (currency or UOB_DEFAULT_CURRENCY).upper(),
        "statement_period": statement_period,
        "statement_period_start": start,
        "statement_period_end": end,
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
        date_value = _parse_date(row.get(col_map["transaction date"]))
        description = _clean_text(row.get(col_map["transaction description"]))
        withdrawal = _parse_amount(row.get(col_map["withdrawal"]))
        deposit = _parse_amount(row.get(col_map["deposit"]))
        balance = _parse_amount(row.get(col_map["available balance"]))

        if date_value is None:
            if current is None:
                continue
            if description:
                current.description = _append_description(current.description, description)
            if withdrawal is not None:
                current.withdrawal = withdrawal
            if deposit is not None:
                current.deposit = deposit
            if balance is not None:
                current.balance = balance
            continue

        current = ParsedRow(
            row_index=int(row_index),
            ts=date_value,
            description=description,
            withdrawal=withdrawal,
            deposit=deposit,
            balance=balance,
        )
        grouped.append(current)

    return grouped


def _classify_transaction(amount: float, description: str) -> tuple[str, str]:
    text = description.upper()
    if amount > 0:
        if "SALARY" in text:
            return "INCOME", "Bank::Deposit"
        if any(keyword in text for keyword in _TRANSFER_KEYWORDS):
            return "TRANSFER", "Bank::Transfer"
        return "INCOME", "Bank::Deposit"

    if any(keyword in text for keyword in _TRANSFER_KEYWORDS):
        return "TRANSFER", "Bank::Transfer"
    return "EXPENSE", "Bank::Withdrawal"


def _transaction_fields(description: str) -> tuple[str, str | None]:
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    if not lines:
        return "UOB", None
    counterparty = lines[-1]
    notes = " | ".join(lines)
    return counterparty, notes


def _select_balance_row(rows: list[ParsedRow]) -> ParsedRow | None:
    candidates = [row for row in rows if row.balance is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (row.ts, row.row_index))


def parse_uob_account_xls(file_path: str) -> ParseResult:
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
            "statement_period": None,
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

    required = _HEADER_COLUMNS
    if not required.issubset(col_map):
        return ParseResult(
            transactions=[],
            positions=[],
            section_counts={"transactions": 0},
            parser_meta={**metadata, "sheet_name": sheet_name, "header_row_index": header_row},
        )

    grouped_rows = _collapse_rows(df, col_map)
    transactions: list[dict[str, Any]] = []

    for row in grouped_rows:
        withdrawal = row.withdrawal or 0.0
        deposit = row.deposit or 0.0
        if withdrawal <= 0 and deposit <= 0:
            continue
        amount = deposit if deposit > 0 else -withdrawal
        tx_type, category = _classify_transaction(amount, row.description)
        merchant_counterparty, notes = _transaction_fields(row.description)
        transactions.append(
            {
                "ts": row.ts,
                "type": tx_type,
                "amount": amount,
                "currency": metadata["currency"],
                "category": category,
                "merchant_counterparty": merchant_counterparty,
                "notes": notes,
            }
        )

    positions: list[dict[str, Any]] = []
    balance_row = _select_balance_row(grouped_rows)
    if balance_row is not None and balance_row.balance is not None:
        as_of = metadata["statement_period_end"] or balance_row.ts
        positions.append(
            {
                "symbol": metadata["currency"],
                "name": f"{metadata['currency']} Cash",
                "asset_class": "CASH",
                "currency": metadata["currency"],
                "quantity": balance_row.balance,
                "avg_cost": 1.0,
                "cost_basis_base": balance_row.balance,
                "as_of": as_of,
            }
        )

    parser_meta = {
        "sheet_name": sheet_name,
        "header_row_index": header_row,
        "account_number": metadata["account_number"],
        "account_type": metadata["account_type"],
        "currency": metadata["currency"],
        "statement_period": metadata["statement_period"],
        "statement_period_start": metadata["statement_period_start"].isoformat() if metadata["statement_period_start"] else None,
        "statement_period_end": metadata["statement_period_end"].isoformat() if metadata["statement_period_end"] else None,
    }
    return ParseResult(
        transactions=transactions,
        positions=positions,
        section_counts={"transactions": len(grouped_rows)},
        parser_meta=parser_meta,
    )
