from __future__ import annotations

import csv
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.ingestion.parsers import ParseResult

def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    if not value:
        return datetime.now(tz=timezone.utc)
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


def _to_float(value: str) -> float:
    v = value.strip().replace(",", "")
    if v == "":
        return 0.0
    return float(v)


def _normalize_cash_transaction(row: Dict[str, str]) -> Dict[str, Any]:
    desc = row.get("Description", "") or row.get("description", "")
    txn_type = row.get("Type", "") or row.get("type", "")
    amount = _to_float(row.get("Amount", "") or row.get("amount", "0"))
    currency = row.get("Currency", "") or row.get("currency", "")
    ts = _parse_datetime(row.get("Date", "") or row.get("date", ""))

    label = f"{txn_type} {desc}".lower()
    if "dividend" in label:
        ttype = "INCOME"
        category = "Brokerage::Dividend"
        amount = abs(amount)
    elif "interest" in label:
        ttype = "INCOME"
        category = "Brokerage::Interest"
        amount = abs(amount)
    elif "withholding" in label or "tax" in label:
        ttype = "TAX"
        category = "Brokerage::Tax"
        amount = -abs(amount)
    elif "commission" in label or "fee" in label:
        ttype = "FEE"
        category = "Brokerage::Fee"
        amount = -abs(amount)
    elif "deposit" in label or "withdrawal" in label or "transfer" in label:
        ttype = "TRANSFER"
        category = "Brokerage::Transfer"
    else:
        if amount >= 0:
            ttype = "INCOME"
            category = "Brokerage::Other Income"
        else:
            ttype = "EXPENSE"
            category = "Brokerage::Expense"
    return {
        "ts": ts,
        "type": ttype,
        "amount": amount,
        "currency": currency,
        "category": category,
        "merchant_counterparty": desc or "IBKR",
    }


def _normalize_trade(row: Dict[str, str]) -> Dict[str, Any]:
    side = (row.get("Buy/Sell", "") or row.get("buy/sell", "")).strip().upper()
    symbol = (row.get("Symbol", "") or row.get("symbol", "")).strip()
    currency = row.get("Currency", "") or row.get("currency", "")
    quantity_raw = row.get("Quantity", "") or row.get("quantity", "") or row.get("Shares", "") or row.get("shares", "")
    quantity = _to_float(quantity_raw) if str(quantity_raw).strip() else 0.0
    asset_class_raw = (row.get("Asset Class") or row.get("Asset Category") or row.get("asset class") or "Stock")
    asset_class = _map_asset_class(asset_class_raw)
    ts = _parse_datetime(row.get("Date", "") or row.get("date", ""))
    net_cash = row.get("Net Cash", "") or row.get("net cash", "")
    amount = _to_float(net_cash)

    if side == "BUY":
        ttype = "BUY"
        amount = -abs(amount) if amount != 0 else amount
    elif side == "SELL":
        ttype = "SELL"
        amount = abs(amount) if amount != 0 else amount
    else:
        ttype = "TRANSFER"
    return {
        "ts": ts,
        "type": ttype,
        "amount": amount,
        "currency": currency,
        "category": "Brokerage::Trade",
        "merchant_counterparty": symbol or "IBKR",
        "symbol": symbol or None,
        "quantity": abs(quantity) if quantity else None,
        "asset_class": asset_class,
    }


def _map_asset_class(value: str) -> str:
    v = value.lower()
    if "stock" in v or "equity" in v:
        return "STOCK"
    if "fund" in v or "etf" in v or "mutual" in v:
        return "FUND"
    if "crypto" in v or "digital" in v:
        return "CRYPTO"
    if "bond" in v:
        return "BOND"
    if "cash" in v:
        return "CASH"
    return "OTHER"


def _normalize_position(row: Dict[str, str]) -> Dict[str, Any]:
    symbol = (row.get("Symbol") or row.get("symbol") or row.get("Ticker") or "").strip()
    name = (row.get("Description") or row.get("description") or row.get("Security") or "").strip() or None
    asset_class_raw = (row.get("Asset Class") or row.get("Asset Category") or row.get("asset class") or "Other")
    asset_class = _map_asset_class(asset_class_raw)
    currency = (row.get("Currency") or row.get("currency") or "").strip()
    quantity = _to_float(row.get("Quantity", "") or row.get("Position", "") or row.get("position", "0"))
    avg_cost = _to_float(row.get("Cost Price", "") or row.get("Average Price", "") or row.get("Avg Price", "") or "0")
    value_field = row.get("Value", "") or row.get("value", "")
    cost_basis = _to_float(value_field or row.get("Cost Basis", "") or row.get("Cost", "") or "0")
    if cost_basis == 0 and quantity and avg_cost:
        cost_basis = quantity * avg_cost
    home_country = (row.get("Country/Region") or row.get("Country") or row.get("country") or "").strip() or None
    return {
        "symbol": symbol,
        "name": name,
        "asset_class": asset_class,
        "currency": currency,
        "quantity": quantity,
        "avg_cost": avg_cost or None,
        "cost_basis_base": cost_basis,
        "home_country": home_country,
    }


def _normalize_cash_balance(row: Dict[str, str]) -> Dict[str, Any] | None:
    asset_category = (row.get("Asset Category") or row.get("asset category") or "").strip().lower()
    if asset_category not in ("forex", "cash"):
        return None
    currency = (row.get("Description") or row.get("Currency") or "").strip().upper()
    if not currency:
        return None
    quantity = _to_float(row.get("Quantity", "") or "0")
    if quantity == 0:
        return None
    return {
        "symbol": currency,
        "name": f"{currency} Cash",
        "asset_class": "CASH",
        "currency": currency,
        "quantity": quantity,
        "avg_cost": None,
        "cost_basis_base": quantity,
        "home_country": None,
    }


def parse_ibkr_activity_csv(file_path: str, delimiter: str) -> ParseResult:
    transactions: List[Dict[str, Any]] = []
    positions: List[Dict[str, Any]] = []
    section_counts: Dict[str, int] = {}

    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        headers: Dict[str, List[str]] = {}
        for row in reader:
            if len(row) < 2:
                continue
            section = row[0].strip()
            record_type = row[1].strip()
            section_counts[section] = section_counts.get(section, 0) + 1
            if record_type.lower() == "header":
                headers[section] = row[2:]
                continue
            if record_type.lower() != "data":
                continue
            header = headers.get(section)
            if not header:
                continue
            data = {header[i]: row[i + 2] if i + 2 < len(row) else "" for i in range(len(header))}
            if section == "Cash Transactions":
                transactions.append(_normalize_cash_transaction(data))
            elif section == "Trades":
                transactions.append(_normalize_trade(data))
            elif section.lower() in ("open positions", "positions"):
                positions.append(_normalize_position(data))
            elif section.lower() == "forex balances":
                cash = _normalize_cash_balance(data)
                if cash:
                    positions.append(cash)
    return ParseResult(
        transactions=transactions,
        positions=positions,
        section_counts=section_counts,
    )
