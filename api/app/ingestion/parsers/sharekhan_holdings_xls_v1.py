from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import pandas as pd


@dataclass
class SheetSelection:
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
    tokens = {"available qty", "qty", "hold value", "market value", "hold price", "market price", "scrip", "symbol", "isin"}
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


def _select_sheet(xls: pd.ExcelFile) -> SheetSelection | None:
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=30)
        df = df.dropna(how="all")
        if df.empty:
            continue
        header_row = _find_header_row(df)
        if header_row is None:
            continue
        columns = [_clean_header(c) for c in df.loc[header_row].tolist()]
        return SheetSelection(name=sheet, header_row=header_row, columns=columns)
    return None


def _normalize_columns(columns: list[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for col in columns:
        key = col.strip().lower()
        if key in ("scrip name", "script name", "scrip", "script", "symbol", "security", "company", "skscripcode", "scripcode", "scrip code"):
            mapping["symbol"] = col
        elif key in ("stock name", "security name", "company name"):
            mapping["name"] = col
        elif "isin" in key:
            mapping["isin"] = col
        elif ("available" in key or "current" in key) and "qty" in key:
            mapping["qty"] = col
        elif key in ("qty", "quantity", "holding qty", "balance qty", "current qty"):
            mapping.setdefault("qty", col)
        elif ("hold" in key or "holding" in key) and "value" in key:
            mapping["hold_value"] = col
        elif "market" in key and "value" in key:
            mapping["market_value"] = col
        elif ("hold" in key or "avg" in key or "cost" in key or "investment" in key) and "price" in key:
            mapping["hold_price"] = col
        elif ("market" in key or "last" in key or "ltp" in key or "current market" in key) and "price" in key:
            mapping["market_price"] = col
    return mapping


def _select_html_table(tables: list[pd.DataFrame]) -> tuple[pd.DataFrame, SheetSelection] | None:
    for idx, raw in enumerate(tables):
        if raw.empty:
            continue
        header_row = _find_header_row(raw)
        if header_row is None:
            header_vals = [_clean_header(c) for c in raw.columns.tolist()]
            selection = SheetSelection(name=f"HTML_TABLE_{idx}", header_row=0, columns=header_vals)
            data = raw.reset_index(drop=True)
            data.columns = [str(c).strip() for c in header_vals]
        else:
            header_vals = [_clean_header(c) for c in raw.loc[header_row].tolist()]
            selection = SheetSelection(name=f"HTML_TABLE_{idx}", header_row=header_row, columns=header_vals)
            data = raw.iloc[header_row + 1 :].reset_index(drop=True)
            data.columns = [str(c).strip() for c in header_vals]
        return data, selection
    return None


def parse_sharekhan_holdings_xls(file_path: str) -> Tuple[List[Dict], List[Dict], Dict[str, int], Dict[str, Any]]:
    if _is_html_file(file_path):
        tables = pd.read_html(file_path)
        found = _select_html_table(tables)
        if not found:
            return [], [], {"rows_parsed": 0}, {"sheet_name": None, "header_row_index": None}
        df, selection = found
    else:
        engine = _pick_engine(file_path)
        xls = pd.ExcelFile(file_path, engine=engine)
        selection = _select_sheet(xls)
        if selection is None:
            return [], [], {"rows_parsed": 0}, {"sheet_name": None, "header_row_index": None}
        df = pd.read_excel(xls, sheet_name=selection.name, header=selection.header_row)
    df = df.dropna(how="all")
    columns = [str(c).strip() for c in df.columns.tolist()]
    col_map = _normalize_columns(columns)

    positions: List[Dict] = []
    preview: List[Dict] = []
    for _, row in df.iterrows():
        symbol = None
        if "symbol" in col_map:
            symbol = str(row[col_map["symbol"]]).strip()
        if (not symbol or symbol.lower() == "nan") and "isin" in col_map:
            symbol = str(row[col_map["isin"]]).strip()
        name = None
        if "name" in col_map:
            name = str(row[col_map["name"]]).strip()
        if not symbol or symbol.lower() == "nan":
            if name and name.lower() != "nan":
                symbol = name
            else:
                continue
        if "total" in symbol.lower():
            continue

        qty = _as_float(row.get(col_map.get("qty", ""), None)) or 0.0
        hold_value = _as_float(row.get(col_map.get("hold_value", ""), None))
        market_value = _as_float(row.get(col_map.get("market_value", ""), None))
        hold_price = _as_float(row.get(col_map.get("hold_price", ""), None))
        market_price = _as_float(row.get(col_map.get("market_price", ""), None))

        if hold_value is None and hold_price is not None:
            hold_value = qty * hold_price
        if market_value is None and market_price is not None:
            market_value = qty * market_price

        cost_basis = hold_value if hold_value is not None else (market_value if market_value is not None else 0.0)

        positions.append(
            {
                "symbol": symbol,
                "name": name or symbol,
                "asset_class": "STOCK",
                "currency": "INR",
                "quantity": qty,
                "avg_cost": hold_price,
                "cost_basis_base": cost_basis,
                "home_country": "IN",
            }
        )

        if len(preview) < 10:
            preview.append(
                {
                    "symbol": symbol,
                    "quantity": qty,
                    "hold_value": hold_value,
                    "market_value": market_value,
                }
            )

    meta = {
        "sheet_name": selection.name,
        "header_row_index": selection.header_row,
        "preview_positions": preview,
    }
    return [], positions, {"rows_parsed": len(df)}, meta
