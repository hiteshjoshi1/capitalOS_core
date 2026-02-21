from __future__ import annotations

import csv
import hashlib
from typing import Tuple, Dict, List


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
