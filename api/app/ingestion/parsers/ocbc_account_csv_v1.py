from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from typing import Dict, List

from app.ingestion.parsers import ParseResult
from app.ingestion.parsers.dbs_transaction_history_csv_v1 import _parse_amount, _parse_date

_CURRENCY_RE = re.compile(r"\(([^)]+)\)")
_TRANSFER_KEYWORDS = (
    "TRANSFER",
    "FUND TRANSFER",
    "FAST PAYMENT",
    "GIRO",
    "IBG",
    "PAYNOW",
    "BILL",
    "TAX",
    "IRAS",
    "SRS",
    "CPF",
    "TOPUP",
    "TOP UP",
)
_INCOME_KEYWORDS = ("INTEREST CREDIT", "BONUS INTEREST")


@dataclass
class OcbcBalances:
    account_name: str | None = None
    currency: str = "SGD"
    available: float | None = None
    ledger: float | None = None


def _normalize_header(value: str) -> str:
    return value.strip().lower()


def _collapse_description(value: str) -> str:
    return " ".join(value.split())


def _extract_currency(*headers: str) -> str:
    for header in headers:
        match = _CURRENCY_RE.search(header)
        if match:
            return match.group(1).strip().upper()
    return "SGD"


def _is_transfer(description: str) -> bool:
    upper = description.upper()
    return any(keyword in upper for keyword in _TRANSFER_KEYWORDS)


def _classify(description: str, amount: float) -> str:
    upper = description.upper()
    if any(keyword in upper for keyword in _INCOME_KEYWORDS):
        return "INCOME"
    if _is_transfer(description):
        return "TRANSFER"
    return "INCOME" if amount > 0 else "EXPENSE"


def parse_ocbc_account_csv(file_path: str, delimiter: str = ",") -> ParseResult:
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=delimiter))

    balances = OcbcBalances()
    header_idx = None

    for idx, row in enumerate(rows):
        if not row:
            continue
        first = row[0].strip().lower()
        if first == "account details for:" and len(row) > 1:
            balances.account_name = row[1].strip() or balances.account_name
        elif first == "available balance" and len(row) > 1:
            amount = _parse_amount(row[1])
            balances.available = amount if amount is not None else balances.available
        elif first == "ledger balance" and len(row) > 1:
            amount = _parse_amount(row[1])
            balances.ledger = amount if amount is not None else balances.ledger
        elif len(row) >= 2 and _normalize_header(row[0]) == "transaction date" and _normalize_header(row[1]) == "value date":
            header_idx = idx
            break

    if header_idx is None:
        return ParseResult(transactions=[], positions=[], section_counts={}, parser_meta={})

    headers = [header.strip() for header in rows[header_idx]]
    normalized_headers = {_normalize_header(header): header for header in headers}
    withdrawal_key = normalized_headers.get("withdrawals(sgd)") or normalized_headers.get("withdrawals")
    deposit_key = normalized_headers.get("deposits(sgd)") or normalized_headers.get("deposits")
    balances.currency = _extract_currency(withdrawal_key or "", deposit_key or "")

    def row_to_dict(row: list[str]) -> Dict[str, str]:
        return {headers[index]: row[index].strip() if index < len(row) else "" for index in range(len(headers))}

    parsed: List[Dict] = []
    count = 0
    latest_tx = None

    for row in rows[header_idx + 1 :]:
        if not row or all(cell.strip() == "" for cell in row):
            continue
        count += 1
        record = row_to_dict(row)

        tx_date = _parse_date(record.get(normalized_headers.get("transaction date", ""), "")) or _parse_date(
            record.get(normalized_headers.get("value date", ""), "")
        )
        if tx_date is None:
            continue

        debit = _parse_amount(record.get(withdrawal_key or "", ""))
        credit = _parse_amount(record.get(deposit_key or "", ""))
        if credit is not None and credit > 0:
            amount = credit
        elif debit is not None and debit > 0:
            amount = -debit
        else:
            continue

        description = _collapse_description(record.get(normalized_headers.get("description", ""), ""))
        tx_type = _classify(description, amount)
        latest_tx = tx_date if latest_tx is None or tx_date > latest_tx else latest_tx
        category = "Bank::Transfer" if tx_type == "TRANSFER" else "Bank::Transaction"

        parsed.append(
            {
                "ts": tx_date,
                "type": tx_type,
                "amount": amount,
                "currency": balances.currency,
                "category": category,
                "merchant_counterparty": description or balances.account_name or "OCBC",
                "notes": None,
            }
        )

    positions: List[Dict] = []
    balance_value = balances.available if balances.available is not None else balances.ledger
    if balance_value is not None:
        positions.append(
            {
                "symbol": balances.currency,
                "name": f"{balances.currency} Cash",
                "asset_class": "CASH",
                "currency": balances.currency,
                "quantity": balance_value,
                "avg_cost": 1.0,
                "cost_basis_base": balance_value,
                "as_of": None,
            }
        )

    parser_meta = {
        "account_name": balances.account_name,
        "available_balance": balances.available,
        "ledger_balance": balances.ledger,
        "currency": balances.currency,
        "latest_transaction_at": latest_tx.isoformat() if latest_tx else None,
    }
    return ParseResult(
        transactions=parsed,
        positions=positions,
        section_counts={"transactions": count},
        parser_meta=parser_meta,
    )
