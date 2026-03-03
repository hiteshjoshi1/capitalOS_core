from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple


@dataclass
class DbsBalances:
    currency: str | None = None
    available: float | None = None
    ledger: float | None = None
    as_of: datetime | None = None


def _parse_amount(value: str) -> float | None:
    cleaned = value.strip().replace(",", "")
    if cleaned == "":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(value: str, fallback_year: int | None = None) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            continue
    if fallback_year and ("/" in text or "-" in text):
        parts = text.replace("-", "/").split("/")
        if len(parts) == 2:
            try:
                day = int(parts[0])
                month = int(parts[1])
                dt = datetime(fallback_year, month, day, tzinfo=timezone.utc)
                return dt.replace(hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                return None
    return None


def _extract_currency(text: str) -> str | None:
    parts = text.strip().split()
    if parts:
        return parts[0].upper()
    return None


def _is_transfer(stmt_code: str, description: str, supplementary: str) -> bool:
    code = stmt_code.strip().upper()
    if code in {"TRF"}:
        return True
    text = f"{description} {supplementary}".upper()
    keywords = [
        "TRF",
        "TRANSFER",
        "SRS",
        "CPF",
        "GIRO",
        "IBG",
        "BILL",
        "PAYNOW",
        "TOPUP",
        "TOP UP",
        "TAX",
        "IRAS",
    ]
    return any(k in text for k in keywords)


def parse_dbs_transaction_history_csv(file_path: str, delimiter: str = ",") -> Tuple[List[Dict], List[Dict], Dict[str, int]]:
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=delimiter))

    balances = DbsBalances()
    header_idx = None
    for idx, row in enumerate(rows):
        if not row:
            continue
        label = row[0].strip().lower()
        if label == "statement as at:" and len(row) > 1:
            balances.as_of = _parse_date(row[1]) or balances.as_of
        if label == "currency:" and len(row) > 1:
            balances.currency = _extract_currency(row[1]) or balances.currency
        if label == "available balance:" and len(row) > 1:
            amount = _parse_amount(row[1].replace(balances.currency or "", "").strip())
            balances.available = amount if amount is not None else balances.available
        if label == "ledger balance:" and len(row) > 1:
            amount = _parse_amount(row[1].replace(balances.currency or "", "").strip())
            balances.ledger = amount if amount is not None else balances.ledger
        if label == "transaction date":
            header_idx = idx
            break

    if header_idx is None:
        return [], [], {}

    headers = [h.strip() for h in rows[header_idx]]
    data_rows = rows[header_idx + 1 :]

    def row_to_dict(row: list[str]) -> Dict[str, str]:
        return {headers[i]: row[i].strip() if i < len(row) else "" for i in range(len(headers))}

    parsed: List[Dict] = []
    count = 0
    for row in data_rows:
        if not row or all(c.strip() == "" for c in row):
            continue
        count += 1
        record = row_to_dict(row)

        fallback_year = balances.as_of.year if balances.as_of else None
        tx_date = _parse_date(record.get("Transaction Date", ""), fallback_year) or _parse_date(record.get("Value Date", ""), fallback_year)
        if not tx_date:
            continue

        currency = record.get("Currency", "").strip().upper() or (balances.currency or "SGD")
        debit = _parse_amount(record.get("Debit Amount", ""))
        credit = _parse_amount(record.get("Credit Amount", ""))

        amount = 0.0
        tx_type = "EXPENSE"
        if credit is not None and credit > 0:
            amount = credit
            tx_type = "INCOME"
        elif debit is not None and debit > 0:
            amount = -debit
            tx_type = "EXPENSE"
        else:
            continue

        description = record.get("Description", "").strip()
        stmt_code = record.get("Statement Code", "").strip()
        supp_desc = record.get("Supplementary Code Description", "") or record.get("Supplementary Code", "")
        if _is_transfer(stmt_code, description, supp_desc):
            tx_type = "TRANSFER"
        category = "Bank::Transaction"
        if stmt_code:
            category = f"Bank::{stmt_code}"

        parsed.append(
            {
                "ts": tx_date,
                "type": tx_type,
                "amount": amount,
                "currency": currency,
                "category": category,
                "merchant_counterparty": description or "DBS",
                "notes": supp_desc,
            }
        )

    positions: List[Dict] = []
    balance_value = balances.available if balances.available is not None else balances.ledger
    if balance_value is not None and balances.currency:
        positions.append(
            {
                "symbol": balances.currency,
                "name": f"{balances.currency} Cash",
                "asset_class": "CASH",
                "currency": balances.currency,
                "quantity": balance_value,
                "avg_cost": 1.0,
                "cost_basis_base": balance_value,
                "as_of": balances.as_of,
            }
        )

    section_counts = {"transactions": count}
    return parsed, positions, section_counts
