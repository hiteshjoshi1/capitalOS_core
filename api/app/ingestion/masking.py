"""Mask account and card numbers in the app's own copies of statement headers (#190).

The import report (``data/reports/<job>.json``) and the upload / register
responses carry the file's header (``signature_debug``) and the parser's
metadata, and those can hold a statement's full account or card number. They
only ever need the last 4 digits, so a number there is masked to those.

Only the copies the app makes itself are masked. ``merchant_counterparty`` is
the bank's own text and stays as it is (it is part of the dedup key, D-35, and
merchant matching reads it). Transaction ``notes`` are masked too (#301): parsers
put the statement's card or account number there (``card_number=...``), and no
key or match reads the notes, so masking them changes no fingerprint or dedup.
The statement-identity link (#180) hashes the unmasked number before any
report is built, so masking never changes which account a statement links to.
"""
from __future__ import annotations

import copy
import re
from typing import Any

# A run of digits (and masked X / *), optionally grouped with single spaces or
# dashes, starting and ending with a digit, not glued to letters ("U1234567" or
# "ref123" are not numbers; a word "x" next to a number is not part of it).
_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9*])[0-9](?:[0-9Xx*]|[ \-](?=[0-9Xx*]))*(?<=[0-9])(?![A-Za-z0-9*])")
# Dash-separated dates look like grouped numbers; they are not account numbers.
_DATE_RE = re.compile(r"^(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{4})$")
# Shorter runs are amounts, years, codes; account and card numbers are longer.
MIN_NUMBER_LENGTH = 8
MASK = "*"

# parser_meta keys that name the statement's own account (UOB: account_number,
# OCBC: account_name embeds it, DBS card: display name and masked number).
PARSER_META_IDENTITY_KEYS = frozenset(
    {"account_number", "account_name", "card_number", "card_display_name", "card_masked"}
)


def _mask_token(token: str) -> str:
    symbols = [c for c in token if c not in " -"]
    if len(symbols) < MIN_NUMBER_LENGTH or not "".join(symbols[-4:]).isdigit() or _DATE_RE.match(token):
        return token
    keep = 4
    out = []
    for c in reversed(token):
        if c in " -":
            out.append(c)
        elif keep > 0:
            out.append(c)
            keep -= 1
        else:
            out.append(MASK)
    return "".join(reversed(out))


def mask_account_numbers(value: str) -> str:
    """``value`` with every account/card-like number masked to its last 4 digits,
    separators kept: "Card 5555-5555-5555-4444" -> "Card ****-****-****-4444".
    Idempotent; text without such a number comes back unchanged."""
    if not value:
        return value
    return _TOKEN_RE.sub(lambda m: _mask_token(m.group(0)), value)


def mask_transaction_notes(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mask account/card numbers in each parsed transaction's ``notes``, in place (#301).

    Runs before the runner adds its ``| fp:<hash>`` suffix, so fingerprints are never
    touched, and before the preview is built, so the report shows the masked text.
    """
    for tx in transactions:
        notes = tx.get("notes")
        if notes:
            tx["notes"] = mask_account_numbers(str(notes))
    return transactions


def _mask_deep(value: Any) -> Any:
    if isinstance(value, str):
        return mask_account_numbers(value)
    if isinstance(value, list):
        return [_mask_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: _mask_deep(v) for k, v in value.items()}
    return value


def mask_parser_meta(parser_meta: dict | None) -> dict | None:
    """A copy of ``parser_meta`` with its account-identifier fields masked."""
    if not isinstance(parser_meta, dict):
        return parser_meta
    out = dict(parser_meta)
    for key in PARSER_META_IDENTITY_KEYS & out.keys():
        value = out[key]
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)  # a number cell read as an integer
        out[key] = _mask_deep(value)
    return out


def mask_signature_debug(signature_debug: dict | None) -> dict | None:
    """A copy of ``signature_debug`` with numbers in its header lines masked."""
    if not isinstance(signature_debug, dict):
        return signature_debug
    return _mask_deep(copy.deepcopy(signature_debug))


def mask_report(report: dict) -> tuple[dict, list[str]]:
    """A copy of an import report (or upload response) with the in-scope fields
    masked, plus the dotted paths of the fields that changed."""
    out = dict(report)
    changed: list[str] = []
    meta = report.get("parser_meta")
    masked_meta = mask_parser_meta(meta)
    if masked_meta != meta:
        out["parser_meta"] = masked_meta
        changed += [f"parser_meta.{k}" for k in sorted(PARSER_META_IDENTITY_KEYS & (meta or {}).keys()) if masked_meta[k] != meta[k]]  # type: ignore[index]
    debug = report.get("signature_debug")
    masked_debug = mask_signature_debug(debug)
    if masked_debug != debug:
        out["signature_debug"] = masked_debug
        changed += [f"signature_debug.{k}" for k in sorted(debug or {}) if masked_debug[k] != debug[k]]  # type: ignore[index]
    return out, changed
