from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from app.ingestion.as_of import find_stated_date, html_text_fragments, preamble_cells
from app.ingestion.parsers import ParseResult

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


_HEADER_TOKENS = {"available qty", "qty", "hold value", "market value", "hold price", "market price", "scrip", "symbol", "isin"}


def _header_hit_count(values: list[str]) -> int:
    hit = 0
    for v in values:
        if not v:
            continue
        for t in _HEADER_TOKENS:
            if t in v:
                hit += 1
                break
    return hit


def _find_header_row(df: pd.DataFrame) -> int | None:
    for idx, row in df.iterrows():
        values = [_clean_header(v) for v in row.tolist()]
        if not any(values):
            continue
        if _header_hit_count(values) >= 2:
            return int(idx)
    return None


def _columns_look_like_header(columns: list) -> bool:
    # Covers HTML tables whose header row uses <th> — pandas' read_html
    # already promotes that to DataFrame.columns, so it never shows up as a
    # data row for _find_header_row to scan.
    return _header_hit_count([_clean_header(c) for c in columns]) >= 2


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


def _cell_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def code_and_name_swapped(pairs: list[tuple[Any, Any]]) -> bool:
    """Whether the (code column, name column) values hold the name first (#222).

    Sharekhan's export labels its first two columns ``SKScripCode | Stock Name``
    but each data row holds the company name first and the scrip code second.
    A scrip code never has a space and a company name nearly always does, so the
    columns are swapped when more rows look like (name, code) than (code, name).
    Rows where neither or both values have a space (a one-word company name)
    don't count either way.
    """
    swapped = straight = 0
    for code, name in pairs:
        code_text, name_text = _cell_text(code), _cell_text(name)
        if not code_text or not name_text:
            continue
        code_spaced, name_spaced = " " in code_text, " " in name_text
        if code_spaced and not name_spaced:
            swapped += 1
        elif name_spaced and not code_spaced:
            straight += 1
    return swapped > straight


def _select_html_table(tables: list[pd.DataFrame]) -> tuple[pd.DataFrame, SheetSelection] | None:
    for idx, raw in enumerate(tables):
        if raw.empty:
            continue
        header_row = _find_header_row(raw)
        if header_row is not None:
            header_vals = [_clean_header(c) for c in raw.loc[header_row].tolist()]
            selection = SheetSelection(name=f"HTML_TABLE_{idx}", header_row=header_row, columns=header_vals)
            data = raw.iloc[header_row + 1 :].reset_index(drop=True)
            data.columns = [str(c).strip() for c in header_vals]
            return data, selection
        if _columns_look_like_header(raw.columns.tolist()):
            # Header used <th> — pandas already promoted it to real column
            # names, so every row of `raw` is data (there's no header row to
            # skip past).
            header_vals = [_clean_header(c) for c in raw.columns.tolist()]
            selection = SheetSelection(name=f"HTML_TABLE_{idx}", header_row=0, columns=header_vals)
            data = raw.reset_index(drop=True)
            data.columns = [str(c).strip() for c in header_vals]
            return data, selection
        # Neither a matching header row nor matching column names — this
        # table isn't the holdings table (e.g. a title/customer-info table
        # above the real one in Sharekhan's export). Keep looking.
        continue
    return None


def parse_sharekhan_holdings_xls(file_path: str) -> ParseResult:
    if _is_html_file(file_path):
        tables = pd.read_html(file_path)
        found = _select_html_table(tables)
        if not found:
            return ParseResult(
                transactions=[],
                positions=[],
                section_counts={"rows_parsed": 0},
                parser_meta={"sheet_name": None, "header_row_index": None},
            )
        df, selection = found
        # A title/customer-info block (its own table or loose text) states the
        # holdings date: "Holdings as on 01/10/2026" (#141).
        stated_as_of = find_stated_date(html_text_fragments(file_path))
    else:
        engine = _pick_engine(file_path)
        xls = pd.ExcelFile(file_path, engine=engine)
        selection = _select_sheet(xls)
        if selection is None:
            return ParseResult(
                transactions=[],
                positions=[],
                section_counts={"rows_parsed": 0},
                parser_meta={"sheet_name": None, "header_row_index": None},
            )
        preamble = pd.read_excel(xls, sheet_name=selection.name, header=None, nrows=selection.header_row)
        stated_as_of = find_stated_date(preamble_cells(preamble, selection.header_row))
        df = pd.read_excel(xls, sheet_name=selection.name, header=selection.header_row)
    df = df.dropna(how="all")
    columns = [str(c).strip() for c in df.columns.tolist()]
    col_map = _normalize_columns(columns)
    # The scrip-code and name columns trade places in Sharekhan's rows (#222).
    columns_swapped = (
        "symbol" in col_map
        and "name" in col_map
        and code_and_name_swapped(list(zip(df[col_map["symbol"]].tolist(), df[col_map["name"]].tolist())))
    )
    if columns_swapped:
        col_map["symbol"], col_map["name"] = col_map["name"], col_map["symbol"]

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
                "market_price": market_price,
                "market_value_base": market_value,
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
        "code_name_columns_swapped": columns_swapped,
    }
    if stated_as_of is not None:
        meta["as_of"] = stated_as_of.isoformat()
    return ParseResult(
        transactions=[],
        positions=positions,
        section_counts={"rows_parsed": len(df)},
        parser_meta=meta,
    )
