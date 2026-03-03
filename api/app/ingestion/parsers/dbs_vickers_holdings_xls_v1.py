from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import pandas as pd


@dataclass
class TableSelection:
    name: str
    header_row: int
    columns: list[str]


def _clean_header(value: Any) -> str:
    return str(value).strip().lower()


def _as_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick_engine(path: str) -> str | None:
    lower = path.lower()
    if lower.endswith(".xls"):
        return "xlrd"
    if lower.endswith(".xlsx"):
        return "openpyxl"
    return None


def _is_html_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            sample = f.read(512).lower()
        return b"<html" in sample or b"<table" in sample
    except OSError:
        return False


def _find_header_row(df: pd.DataFrame) -> int | None:
    tokens = {"symbol", "stock", "qty", "quantity", "avg", "price", "mkt", "market", "value"}
    for idx, row in df.iterrows():
        values = [_clean_header(v) for v in row.tolist()]
        if not any(values):
            continue
        hit = 0
        for v in values:
            if not v:
                continue
            for t in tokens:
                if t in v:
                    hit += 1
                    break
        if hit >= 2:
            return int(idx)
    return None


def _select_html_table(tables: list[pd.DataFrame]) -> tuple[pd.DataFrame, TableSelection] | None:
    for idx, raw in enumerate(tables):
        if raw.empty:
            continue
        header_row = _find_header_row(raw)
        if header_row is None:
            header_vals = [_clean_header(c) for c in raw.columns.tolist()]
            data = raw.reset_index(drop=True)
            data.columns = [str(c).strip() for c in header_vals]
            selection = TableSelection(name=f"HTML_TABLE_{idx}", header_row=0, columns=header_vals)
        else:
            header_vals = [_clean_header(c) for c in raw.loc[header_row].tolist()]
            data = raw.iloc[header_row + 1 :].reset_index(drop=True)
            data.columns = [str(c).strip() for c in header_vals]
            selection = TableSelection(name=f"HTML_TABLE_{idx}", header_row=header_row, columns=header_vals)
        return data, selection
    return None


def _normalize_columns(columns: list[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for col in columns:
        key = col.strip().lower()
        if key in ("symbol", "stock code", "ticker"):
            mapping["symbol"] = col
        elif key in ("stock name", "name", "security", "company"):
            mapping["name"] = col
        elif key in ("qty", "quantity") or "qty" in key:
            mapping.setdefault("qty", col)
        elif key in ("avg price", "average price", "avg cost", "avg"):
            mapping["avg_price"] = col
        elif key in ("mkt value", "market value", "mkt value (sgd)"):
            mapping["market_value"] = col
        elif key in ("original value", "original cost", "cost value"):
            mapping["original_value"] = col
        elif key in ("last", "last price", "price"):
            mapping.setdefault("last_price", col)
        elif key == "market":
            mapping["market"] = col
    return mapping


def parse_dbs_vickers_holdings_xls(file_path: str) -> Tuple[List[Dict], List[Dict], Dict[str, int], Dict[str, Any]]:
    if _is_html_file(file_path):
        tables = pd.read_html(file_path)
        found = _select_html_table(tables)
        if not found:
            return [], [], {"rows_parsed": 0}, {"sheet_name": None, "header_row_index": None}
        df, selection = found
    else:
        engine = _pick_engine(file_path)
        xls = pd.ExcelFile(file_path, engine=engine)
        sheet_name = xls.sheet_names[0]
        df = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=30)
        header_row = _find_header_row(df)
        if header_row is None:
            return [], [], {"rows_parsed": 0}, {"sheet_name": sheet_name, "header_row_index": None}
        df = pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
        selection = TableSelection(name=sheet_name, header_row=header_row, columns=[_clean_header(c) for c in df.columns])

    df = df.dropna(how="all")
    columns = [str(c).strip() for c in df.columns.tolist()]
    col_map = _normalize_columns(columns)

    aggregated: Dict[str, Dict[str, Any]] = {}
    rows_parsed = 0

    for _, row in df.iterrows():
        symbol = None
        if "symbol" in col_map:
            symbol = str(row.get(col_map["symbol"], "")).strip()
        name = None
        if "name" in col_map:
            name = str(row.get(col_map["name"], "")).strip()

        if not symbol or symbol.lower() == "nan":
            if name and name.lower() != "nan":
                symbol = name
            else:
                continue

        if "total" in symbol.lower():
            continue

        qty = _as_float(row.get(col_map.get("qty", ""), None)) or 0.0
        avg_price = _as_float(row.get(col_map.get("avg_price", ""), None))
        market_value = _as_float(row.get(col_map.get("market_value", ""), None))
        original_value = _as_float(row.get(col_map.get("original_value", ""), None))

        if market_value is None and avg_price is not None:
            market_value = qty * avg_price

        cost_basis = market_value if market_value is not None else (original_value if original_value is not None else 0.0)

        key = symbol
        current = aggregated.get(key)
        if current is None:
            aggregated[key] = {
                "symbol": symbol,
                "name": name or symbol,
                "asset_class": "STOCK",
                "currency": "SGD",
                "quantity": qty,
                "avg_cost": avg_price,
                "cost_basis_base": cost_basis,
                "home_country": "SG",
                "_avg_cost_total": (avg_price or 0.0) * qty,
            }
        else:
            current["quantity"] += qty
            current["cost_basis_base"] += cost_basis
            current["_avg_cost_total"] += (avg_price or 0.0) * qty

        rows_parsed += 1

    positions: List[Dict] = []
    preview: List[Dict] = []
    for entry in aggregated.values():
        qty = entry["quantity"]
        avg_cost_total = entry.pop("_avg_cost_total", 0.0)
        if qty and avg_cost_total:
            entry["avg_cost"] = avg_cost_total / qty
        positions.append(entry)
        if len(preview) < 10:
            preview.append(
                {
                    "symbol": entry["symbol"],
                    "quantity": entry["quantity"],
                    "market_value": entry["cost_basis_base"],
                }
            )

    meta = {
        "sheet_name": selection.name,
        "header_row_index": selection.header_row,
        "preview_positions": preview,
    }
    return [], positions, {"rows_parsed": rows_parsed}, meta
