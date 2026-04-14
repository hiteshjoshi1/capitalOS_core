from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.parser_registry import ParserRegistry
from app.ingestion.parsers.uob_account_xls_v1 import UOB_ACCOUNT_XLS_HEADERS
from app.ingestion.parsers.uob_credit_card_xls_v1 import UOB_CREDIT_CARD_XLS_HEADERS

OCBC_ACCOUNT_CSV_HEADERS = (
    "transaction date",
    "value date",
    "description",
    "withdrawals(sgd)",
    "deposits(sgd)",
)


def _normalize_header(header: object) -> list[str]:
    if not isinstance(header, list):
        return []
    normalized: list[str] = []
    for value in header:
        text = str(value).strip().lower()
        if not text or text == "nan" or text.startswith("unnamed:"):
            continue
        normalized.append(text)
    return normalized


def _has_ordered_header_subset(header: object, expected: tuple[str, ...]) -> bool:
    normalized = _normalize_header(header)
    if not normalized:
        return False
    next_index = 0
    for value in normalized:
        if value != expected[next_index]:
            continue
        next_index += 1
        if next_index == len(expected):
            return True
    return False


def _infer_parser_key(signature_debug: dict | None, platform_hint: str | None) -> str | None:
    header = signature_debug.get("header") if isinstance(signature_debug, dict) else None
    file_kind = signature_debug.get("file_kind") if isinstance(signature_debug, dict) else None
    platform_text = (platform_hint or "").strip().upper()
    # UOB bank statements are currently identified by this ordered header shape.
    # R6 showed platform labels are not reliable enough to be the gating factor.
    has_uob_header = _has_ordered_header_subset(header, UOB_ACCOUNT_XLS_HEADERS)
    if file_kind == "excel" and has_uob_header:
        return "uob_account_xls_v1"
    has_uob_cc_header = _has_ordered_header_subset(header, UOB_CREDIT_CARD_XLS_HEADERS)
    if file_kind == "excel" and has_uob_cc_header:
        return "uob_credit_card_xls_v1"
    has_ocbc_header = _has_ordered_header_subset(header, OCBC_ACCOUNT_CSV_HEADERS)
    if file_kind == "flat_csv" and has_ocbc_header:
        return "ocbc_account_csv_v1"
    # Defensive account/platform inference for broker XLS flows.
    # This is intentionally conservative and only triggers for known platform labels.
    if file_kind in {"excel", "html_table"} and "VICKERS" in platform_text:
        return "dbs_vickers_holdings_xls_v1"
    if file_kind in {"excel", "html_table"} and "SHAREKHAN" in platform_text:
        return "sharekhan_holdings_xls_v1"
    return None


def lookup_parser_key(
    db: Session | None,
    signature: str,
    signature_debug: dict | None = None,
    platform_hint: str | None = None,
) -> str | None:
    if db is not None:
        row = db.query(ParserRegistry).filter(ParserRegistry.format_signature == signature).one_or_none()
        if row:
            return row.parser_key
    return _infer_parser_key(signature_debug, platform_hint)


def register_signature(db: Session, signature: str, parser_key: str, version: int = 1) -> ParserRegistry:
    existing = db.query(ParserRegistry).filter(ParserRegistry.format_signature == signature).one_or_none()
    if existing:
        return existing
    row = ParserRegistry(format_signature=signature, parser_key=parser_key, version=version)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
