"""Checks that an upload goes to the right account (#180).

Two checks run before an upload writes anything:

1. **Account type.** Every parser declares the account types its files belong
   to (``PARSER_ACCOUNT_TYPES``). A bank statement sent to a credit-card account,
   or a holdings file sent to a bank account, is refused with a message naming
   the expected type. A file no parser recognises but that looks like a holdings
   export is refused the same way when the account is not a broker account,
   instead of ending in NEEDS_MAPPING.
2. **Statement identity.** When the file names its own account (the DBS/OCBC
   "Account details for:" line, the DBS card line, UOB's "Account Number:"), the
   first import into an account links that account to the statement's number.
   A later file naming a different number is refused unless the upload passes
   the explicit override, which imports it and moves the link to the new number
   (a replaced card gets a new number). Only a hash of the normalised number and
   its last four digits are stored; the full number is never stored or logged here.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql

# Which account types each parser's files belong to. Every key of the runner's
# PARSER_REGISTRY must be here (enforced by a test).
PARSER_ACCOUNT_TYPES: dict[str, frozenset[str]] = {
    # Bank account statements
    "dbs_transaction_history_csv_v1": frozenset({"BANK"}),
    "ocbc_account_csv_v1": frozenset({"BANK"}),
    "uob_account_xls_v1": frozenset({"BANK"}),
    # Card statements
    "dbs_credit_card_csv_v1": frozenset({"CREDIT_CARD"}),
    "uob_credit_card_xls_v1": frozenset({"CREDIT_CARD"}),
    "citi_credit_card_csv_v1": frozenset({"CREDIT_CARD"}),
    # Broker activity and holdings exports
    "ibkr_activity_csv_v1": frozenset({"BROKER"}),
    "sharekhan_holdings_xls_v1": frozenset({"BROKER", "MUTUAL_FUND"}),
    "dbs_vickers_holdings_xls_v1": frozenset({"BROKER", "MUTUAL_FUND"}),
}

# Which platform codes each parser's files come from (#399, U27: pre-selecting the account).
PARSER_PLATFORMS: dict[str, frozenset[str]] = {
    "dbs_transaction_history_csv_v1": frozenset({"DBS"}),
    "ocbc_account_csv_v1": frozenset({"OCBC"}),
    "uob_account_xls_v1": frozenset({"UOB"}),
    "dbs_credit_card_csv_v1": frozenset({"DBS"}),
    "uob_credit_card_xls_v1": frozenset({"UOB"}),
    "citi_credit_card_csv_v1": frozenset({"CITI", "CITIBANK"}),
    "ibkr_activity_csv_v1": frozenset({"IBKR"}),
    "sharekhan_holdings_xls_v1": frozenset({"SHAREKHAN"}),
    "dbs_vickers_holdings_xls_v1": frozenset({"DBS_VICKERS", "VICKERS"}),
}

# How each parser's files are named in messages.
PARSER_FILE_LABELS: dict[str, str] = {
    "dbs_transaction_history_csv_v1": "DBS bank-account statement",
    "ocbc_account_csv_v1": "OCBC bank-account statement",
    "uob_account_xls_v1": "UOB bank-account statement",
    "dbs_credit_card_csv_v1": "DBS card statement",
    "uob_credit_card_xls_v1": "UOB card statement",
    "citi_credit_card_csv_v1": "Citi card statement",
    "ibkr_activity_csv_v1": "IBKR activity statement",
    "sharekhan_holdings_xls_v1": "Sharekhan holdings file",
    "dbs_vickers_holdings_xls_v1": "DBS Vickers holdings file",
}

# Account types an unrecognised holdings-shaped file may go to.
HOLDINGS_ACCOUNT_TYPES = frozenset({"BROKER", "MUTUAL_FUND"})

ACCOUNT_TYPE_LABELS: dict[str, str] = {
    "BANK": "bank account",
    "CREDIT_CARD": "credit card",
    "BROKER": "broker account",
    "MUTUAL_FUND": "fund account",
    "EXCHANGE": "exchange account",
    "WALLET": "wallet",
    "LOAN": "loan",
}

# The form field that overrides the statement identity check.
IDENTITY_OVERRIDE_FIELD = "allow_account_mismatch"


@dataclass
class UploadRefusal:
    """Why an upload was refused before anything was written."""

    code: str
    message: str
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


def _label(account_type: str) -> str:
    return ACCOUNT_TYPE_LABELS.get(account_type, account_type.lower().replace("_", " "))


def _expected_text(expected: frozenset[str]) -> str:
    labels = [f"{_label(t)} ({t})" for t in sorted(expected)]
    return " or ".join(labels)


def account_type_of(db: Session, account_id: int) -> str:
    row = db.execute(
        text("SELECT account_type FROM accounts WHERE id = :account_id"),
        {"account_id": account_id},
    ).fetchone()
    return str(row[0] or "").upper() if row else ""


def check_parser_account_type(parser_key: str, account_type: str) -> UploadRefusal | None:
    """Refusal when ``parser_key``'s files don't belong in an ``account_type`` account."""
    expected = PARSER_ACCOUNT_TYPES.get(parser_key)
    if expected is None:
        return UploadRefusal(
            code="account_type_unknown_for_parser",
            message=f"Parser {parser_key!r} declares no account type, so the upload was refused.",
            extra={"parser_key": parser_key, "account_type": account_type or None, "expected_account_types": []},
        )
    if account_type in expected:
        return None
    return UploadRefusal(
        code="account_type_mismatch",
        message=(
            f"This file is a {PARSER_FILE_LABELS.get(parser_key, parser_key)}, which belongs to a {_expected_text(expected)}, "
            f"but the selected account is a {_label(account_type)} ({account_type or 'unknown'}). "
            "Nothing was imported. Pick the right account and upload again."
        ),
        extra={
            "parser_key": parser_key,
            "account_type": account_type or None,
            "expected_account_types": sorted(expected),
        },
    )


_QUANTITY_TOKENS = ("qty", "quantity", "units", "no. of shares", "shares")
_SECURITY_TOKENS = ("symbol", "stock", "scrip", "isin", "security", "counter", "instrument")
_VALUE_TOKENS = ("market value", "mkt value", "market price", "mkt price", "avg", "average cost")
_BANK_TOKENS = ("withdrawal", "deposit", "debit", "credit", "transaction date", "balance")


def looks_like_holdings_file(signature_debug: dict | None) -> bool:
    """A spreadsheet whose header has a quantity column and a security or value
    column, and no bank-statement columns: a holdings export."""
    if not isinstance(signature_debug, dict):
        return False
    if signature_debug.get("file_kind") not in {"excel", "html_table"}:
        return False
    header = [str(h).strip().lower() for h in (signature_debug.get("header") or []) if str(h).strip()]
    if not header:
        return False

    def has(tokens: tuple[str, ...]) -> bool:
        return any(token in column for column in header for token in tokens)

    if has(_BANK_TOKENS):
        return False
    return has(_QUANTITY_TOKENS) and (has(_SECURITY_TOKENS) or has(_VALUE_TOKENS))


def check_unrecognised_file(signature_debug: dict | None, account_type: str) -> UploadRefusal | None:
    """Refusal for an unrecognised holdings-shaped file sent to a non-broker account."""
    if account_type in HOLDINGS_ACCOUNT_TYPES or not looks_like_holdings_file(signature_debug):
        return None
    return UploadRefusal(
        code="account_type_mismatch",
        message=(
            f"This file looks like a holdings export, which belongs to a {_expected_text(HOLDINGS_ACCOUNT_TYPES)}, "
            f"but the selected account is a {_label(account_type)} ({account_type or 'unknown'}). "
            "Nothing was imported. Pick the right account and upload again."
        ),
        extra={
            "parser_key": None,
            "account_type": account_type or None,
            "expected_account_types": sorted(HOLDINGS_ACCOUNT_TYPES),
        },
    )


# --- Statement identity ------------------------------------------------------

# Header labels (first cell, lowercased, trailing colon dropped) that name the
# statement's own account in CSV statements.
_CSV_IDENTITY_LABELS: dict[str, tuple[str, ...]] = {
    "dbs_transaction_history_csv_v1": ("account details for",),
    "ocbc_account_csv_v1": ("account details for",),
    "dbs_credit_card_csv_v1": ("card transaction details for",),
}
# Parsers whose parser_meta carries the statement's account number.
_META_IDENTITY_KEYS: dict[str, str] = {
    "uob_account_xls_v1": "account_number",
    "uob_credit_card_xls_v1": "account_number",
}

# A run of digits, optionally masked (x/*) and grouped with spaces or dashes,
# ending in at least four digits.
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[0-9Xx*](?:[0-9Xx*\- ]*[0-9Xx*])?")
_HASH_PREFIX = "capitalos-statement-identity-v1|"


@dataclass(frozen=True)
class StatementIdentity:
    identity_hash: str
    last4: str


def normalise_account_number(value: str | None) -> str | None:
    """The account number in a header value, as digits (masked digits as X), or None.

    "Test Savings 012-345678-9" -> "0123456789"; "Card 5520-xxxx-xxxx-2403" -> "5520XXXXXXXX2403".
    """
    if not value:
        return None
    candidates = []
    for match in _NUMBER_RE.finditer(str(value)):
        token = re.sub(r"[\s\-]", "", match.group(0)).upper().replace("*", "X")
        digits = re.sub(r"\D", "", token)
        if len(digits) >= 4 and token[-4:].isdigit():
            candidates.append(token)
    # The number is the last such token (product names come first).
    return candidates[-1] if candidates else None


def identity_from_number(normalised: str) -> StatementIdentity:
    digest = hashlib.sha256((_HASH_PREFIX + normalised).encode("utf-8")).hexdigest()
    return StatementIdentity(identity_hash=digest, last4=normalised[-4:])


def _csv_header_value(stored_path: str, labels: tuple[str, ...], max_rows: int = 30) -> str | None:
    try:
        with open(stored_path, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(16384)
    except (OSError, UnicodeDecodeError):
        return None
    lines = sample.splitlines()[:max_rows]
    delimiter = ";" if lines and lines[0].count(";") > lines[0].count(",") else ","
    for row in csv.reader(lines, delimiter=delimiter):
        if len(row) < 2:
            continue
        label = row[0].strip().lower().rstrip(":").strip()
        if label in labels:
            return row[1].strip()
    return None


def statement_identity(parser_key: str | None, stored_path: str, parser_meta: dict | None) -> StatementIdentity | None:
    """The account the file names, or None when the format doesn't name one."""
    if not parser_key:
        return None
    raw: str | None = None
    if parser_key in _CSV_IDENTITY_LABELS:
        raw = _csv_header_value(stored_path, _CSV_IDENTITY_LABELS[parser_key])
    elif parser_key in _META_IDENTITY_KEYS:
        value = (parser_meta or {}).get(_META_IDENTITY_KEYS[parser_key])
        raw = str(value) if value is not None else None
    normalised = normalise_account_number(raw)
    return identity_from_number(normalised) if normalised else None


def linked_identity(db: Session, account_id: int) -> dict[str, Any] | None:
    row = db.execute(
        text(
            "SELECT identity_hash, last4, import_job_id FROM account_statement_identities WHERE account_id = :account_id"
        ),
        {"account_id": account_id},
    ).mappings().one_or_none()
    return dict(row) if row else None


def _account_linked_to(db: Session, identity_hash: str, current_user_id: int, exclude_account_id: int) -> dict | None:
    """The caller's other account already linked to this statement, if any."""
    row = db.execute(
        text(
            """
            SELECT a.id, a.name
            FROM account_statement_identities si
            JOIN accounts a ON a.id = si.account_id
            WHERE si.identity_hash = :identity_hash
              AND si.account_id <> :exclude_account_id
              AND """
            + account_scope_sql("a")
            + """
            ORDER BY a.id
            LIMIT 1
            """
        ),
        {"identity_hash": identity_hash, "exclude_account_id": exclude_account_id, "current_user_id": current_user_id},
    ).mappings().one_or_none()
    return dict(row) if row else None


def check_statement_identity(
    db: Session,
    *,
    account_id: int,
    current_user_id: int,
    identity: StatementIdentity | None,
) -> UploadRefusal | None:
    """Refusal when the file names a different account than the one linked."""
    if identity is None:
        return None
    linked = linked_identity(db, account_id)
    if linked is None or linked["identity_hash"] == identity.identity_hash:
        return None
    other = _account_linked_to(db, identity.identity_hash, current_user_id, account_id)
    hint = f" It matches your account “{other['name']}”." if other else ""
    return UploadRefusal(
        code="statement_account_mismatch",
        message=(
            f"This statement is for the account ending {identity.last4}, but the selected account's "
            f"statements are for the account ending {linked['last4']}.{hint} Nothing was imported. "
            "Pick the right account, or upload anyway if this statement belongs here "
            f"(the account is then linked to the account ending {identity.last4})."
        ),
        extra={
            "statement_last4": identity.last4,
            "linked_last4": linked["last4"],
            "suggested_account_id": int(other["id"]) if other else None,
            "override_field": IDENTITY_OVERRIDE_FIELD,
        },
    )


def link_statement_identity(
    db: Session,
    *,
    account_id: int,
    identity: StatementIdentity,
    parser_key: str,
    import_job_id: int,
    undo: dict[str, Any] | None = None,
) -> bool:
    """Link the account to this statement's number: on its first identified
    import, or (after an explicit override) when the number changed.

    Returns True when this job created the link (removing the job removes it, and
    puts back the link it replaced, kept in ``undo``). Part of the caller's transaction.
    """
    from app.ingestion.undo import jsonable_row

    current = db.execute(
        text("SELECT * FROM account_statement_identities WHERE account_id = :account_id"),
        {"account_id": account_id},
    ).mappings().one_or_none()
    if current is not None:
        if current["identity_hash"] == identity.identity_hash:
            return False
        if undo is not None:
            undo.setdefault("replaced_rows", {}).setdefault("account_statement_identities", []).append(
                jsonable_row(current)
            )
        db.execute(
            text("DELETE FROM account_statement_identities WHERE account_id = :account_id"),
            {"account_id": account_id},
        )
    db.execute(
        text(
            """
            INSERT INTO account_statement_identities
              (account_id, identity_hash, last4, parser_key, import_job_id)
            VALUES (:account_id, :identity_hash, :last4, :parser_key, :import_job_id)
            """
        ),
        {
            "account_id": account_id,
            "identity_hash": identity.identity_hash,
            "last4": identity.last4,
            "parser_key": parser_key,
            "import_job_id": import_job_id,
        },
    )
    return True
