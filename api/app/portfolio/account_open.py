"""Closed accounts (#207, #130 finding 1.5).

An account closed on D (``accounts.closed_on``) counts at every anchor on or
before D, exactly as before, and contributes nothing at any anchor after D: its
last snapshot is no longer carried forward. Every as-of reader of account facts
(balances, holdings, NAV, card liabilities, coverage) adds this predicate.
"""
from __future__ import annotations


def account_open_sql(alias: str, date_param: str = ":anchor_date") -> str:
    """SQL: the account ``alias`` is open on the date bound as ``date_param``."""
    return f"({alias}.closed_on IS NULL OR {alias}.closed_on >= {date_param})"
