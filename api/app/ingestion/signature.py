from __future__ import annotations

import csv
import hashlib
from typing import Tuple, Dict, List, Any

import pandas as pd


def _detect_delimiter(sample: str) -> str:
    candidates = [",", ";", "\t", "|"]
    best = ","
    best_count = 0
    for d in candidates:
        rows = list(csv.reader(sample.splitlines(), delimiter=d))
        if not rows:
            continue
        counts = [len(r) for r in rows if r]
        if not counts:
            continue
        score = max(counts)
        if score > best_count:
            best_count = score
            best = d
    return best


def _detect_ibkr(lines: list[str], delimiter: str) -> bool:
    reader = csv.reader(lines, delimiter=delimiter)
    for row in reader:
        if len(row) < 2:
            continue
        record_type = row[1].strip().lower()
        if record_type in {"header", "data"}:
            return True
    return False


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


def _find_header_row_excel(df: pd.DataFrame) -> int | None:
    tokens = {"available", "qty", "hold", "market", "scrip", "symbol", "isin"}
    for idx, row in df.iterrows():
        values = [str(v).strip().lower() for v in row.tolist()]
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


def _find_header_row_table(df: pd.DataFrame) -> int | None:
    tokens = {"available", "qty", "hold", "market", "scrip", "symbol", "isin"}
    for idx, row in df.iterrows():
        values = [str(v).strip().lower() for v in row.tolist()]
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


def _html_signature(file_path: str, platform_hint: str | None) -> Tuple[str, dict]:
    tables = pd.read_html(file_path)
    header_fields: list[str] = []
    type_profile: list[str] = []
    table_index: int | None = None
    header_row: int | None = None

    for idx, raw in enumerate(tables):
        if raw.empty:
            continue
        header_row = _find_header_row_table(raw)
        if header_row is None:
            # pandas read_html often uses the first row as headers already
            header_fields = [str(c).strip().lower() for c in raw.columns.tolist()]
            data = raw
        else:
            header_fields = [str(c).strip().lower() for c in raw.loc[header_row].tolist()]
            data = raw.iloc[header_row + 1 :]
        for col_idx in range(len(header_fields)):
            sample = data.iloc[:, col_idx].dropna() if not data.empty else []
            if sample is None or len(sample) == 0:
                type_profile.append("empty")
            else:
                val = str(sample.iloc[0]).strip().replace(",", "")
                try:
                    float(val)
                    type_profile.append("num")
                except ValueError:
                    type_profile.append("text")
        table_index = idx
        break

    signature_parts = [
        "file_kind=html_table",
        f"platform_hint={platform_hint or ''}",
        f"table_index={table_index if table_index is not None else -1}",
        f"header_row_index={header_row if header_row is not None else -1}",
        f"column_count={len(header_fields)}",
        "header=" + ",".join(header_fields),
        "type_profile=" + ",".join(type_profile),
    ]
    normalized = "\n".join(signature_parts)
    signature = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    debug = {
        "file_kind": "html_table",
        "platform_hint": platform_hint,
        "table_index": table_index,
        "header_row_index": header_row,
        "header": header_fields,
        "type_profile": type_profile,
    }
    return signature, debug


def _excel_signature(file_path: str, platform_hint: str | None, max_rows: int) -> Tuple[str, dict]:
    if _is_html_file(file_path):
        return _html_signature(file_path, platform_hint)
    engine = _pick_engine(file_path)
    try:
        xls = pd.ExcelFile(file_path, engine=engine)
    except Exception:
        return _html_signature(file_path, platform_hint)
    sheet_name = None
    header_row = None
    header_fields: list[str] = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=max_rows)
        df = df.dropna(how="all")
        if df.empty:
            continue
        header_row = _find_header_row_excel(df)
        if header_row is None:
            continue
        header_fields = [str(c).strip().lower() for c in df.loc[header_row].tolist()]
        sheet_name = sheet
        break

    type_profile: list[str] = []
    if sheet_name is not None and header_row is not None:
        df_full = pd.read_excel(xls, sheet_name=sheet_name, header=header_row, nrows=5)
        for col in df_full.columns:
            sample = df_full[col].dropna()
            if sample.empty:
                type_profile.append("empty")
            else:
                val = str(sample.iloc[0]).strip().replace(",", "")
                try:
                    float(val)
                    type_profile.append("num")
                except ValueError:
                    type_profile.append("text")

    signature_parts = [
        "file_kind=excel",
        f"platform_hint={platform_hint or ''}",
        f"column_count={len(header_fields)}",
        f"header_row_index={header_row if header_row is not None else -1}",
        "header=" + ",".join(header_fields),
        "type_profile=" + ",".join(type_profile),
    ]
    normalized = "\n".join(signature_parts)
    signature = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    debug = {
        "file_kind": "excel",
        "platform_hint": platform_hint,
        "sheet_name": sheet_name,
        "header_row_index": header_row,
        "header": header_fields,
        "type_profile": type_profile,
    }
    return signature, debug


def _find_flat_header(lines: list[str], delimiter: str) -> List[str]:
    reader = csv.reader(lines, delimiter=delimiter)
    header_row: list[str] | None = None
    for row in reader:
        if not row:
            continue
        lowered = [c.strip().lower() for c in row]
        if len(lowered) >= 2 and lowered[0] == "transaction date" and lowered[1] == "value date":
            header_row = lowered
            break
    if header_row is None:
        reader = csv.reader(lines, delimiter=delimiter)
        for row in reader:
            if len(row) >= 3:
                header_row = [c.strip().lower() for c in row]
                break
    return header_row or []


def compute_format_signature(file_path: str, platform_hint: str | None = None, max_lines: int = 50) -> Tuple[str, dict]:
    if file_path.lower().endswith((".xls", ".xlsx")):
        return _excel_signature(file_path, platform_hint, max_lines)

    lines: list[str] = []
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        for _ in range(max_lines):
            line = f.readline()
            if not line:
                break
            lines.append(line)

    sample = "".join(lines)
    delimiter = _detect_delimiter(sample)
    if _detect_ibkr(lines, delimiter):
        reader = csv.reader(lines, delimiter=delimiter)

        sections: Dict[str, Dict[str, List[str]]] = {}
        record_types: Dict[str, set] = {}

        for row in reader:
            if len(row) < 2:
                continue
            section = row[0].strip().lower()
            record_type = row[1].strip().lower()
            record_types.setdefault(section, set()).add(record_type)
            if record_type == "header":
                header_fields = [c.strip().lower() for c in row[2:]]
                sections.setdefault(section, {})["header"] = header_fields

        section_names = sorted(sections.keys())
        signature_parts = [
            "file_kind=ibkr_activity_csv",
            f"delimiter={delimiter}",
            f"platform_hint={platform_hint or ''}",
            "sections=" + "|".join(section_names),
        ]
        for section in section_names:
            header = sections.get(section, {}).get("header", [])
            types = sorted(record_types.get(section, set()))
            signature_parts.append(f"section={section}")
            signature_parts.append(f"record_types={','.join(types)}")
            signature_parts.append("header=" + ",".join(header))

        normalized = "\n".join(signature_parts)
        signature = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        debug = {
            "file_kind": "ibkr_activity_csv",
            "delimiter": delimiter,
            "platform_hint": platform_hint,
            "sections": section_names,
            "section_headers": {k: v.get("header", []) for k, v in sections.items()},
            "record_types": {k: sorted(list(v)) for k, v in record_types.items()},
        }
        return signature, debug

    header_fields = _find_flat_header(lines, delimiter)
    signature_parts = [
        "file_kind=flat_csv",
        f"delimiter={delimiter}",
        f"platform_hint={platform_hint or ''}",
        "header=" + ",".join(header_fields),
    ]
    normalized = "\n".join(signature_parts)
    signature = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    debug = {
        "file_kind": "flat_csv",
        "delimiter": delimiter,
        "platform_hint": platform_hint,
        "header": header_fields,
    }
    return signature, debug
