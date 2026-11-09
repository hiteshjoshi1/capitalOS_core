"""Own-account transfers (#339, D-85): money moved between the user's own accounts is
neither income nor spending.

Two read-time rules over Cash Flow rows (nothing stored is changed):

- **Name:** a row whose counterparty text names the account holder (every word of the
  user's display name, any order, at least two words) moves money to or from the holder
  themselves. A bank's standing instruction "SI TO :<holder> REF:SALARY" and the other
  bank's "GIRO SI SALARY … <holder>" both name them. Such a row is an own-account
  transfer even when the other account's side isn't uploaded.
- **Pair:** an outflow and an inflow of the same amount and currency on two of the
  user's accounts within ``OWN_TRANSFER_MATCH_DAYS`` days, where one side is already
  transfer-like (its type, category, markers or the name rule), are the two sides of one
  move: both are transfers, whatever the other side's parsed type (a credit typed INCOME
  included). A candidate filed under a salary category is never re-classified: an
  employer's salary stays income. When two candidates are equally near, the pair is
  ambiguous and nothing is paired.

Rows get ``own_transfer`` ("name" | "pair" | None) and, when paired, the partner's id and
transaction date (``own_transfer_partner_id`` / ``own_transfer_partner_day``).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Iterable, Mapping, Optional

from app.valuation import clock

OWN_TRANSFER_MATCH_DAYS = 3
_AMOUNT_TOLERANCE = 0.005
_WORD = re.compile(r"[a-z]+")


def owner_name_words(display_name: Optional[str]) -> frozenset[str]:
    """The holder's name as a set of lower-case words; empty (rule off) under two words."""
    words = frozenset(word for word in _WORD.findall(str(display_name or "").lower()) if len(word) >= 2)
    return words if len(words) >= 2 else frozenset()


def names_owner(row: Mapping[str, Any], owner_words: frozenset[str]) -> bool:
    """Whether the row's counterparty text or notes carry every word of the holder's name."""
    if not owner_words:
        return False
    text = f"{row.get('merchant_counterparty') or ''} {row.get('notes') or ''}".lower()
    return owner_words <= set(_WORD.findall(text))


def _is_salary_category(row: Mapping[str, Any]) -> bool:
    categories = " ".join(
        str(row.get(key) or "") for key in ("raw_category", "resolved_category", "resolved_category_code")
    ).lower()
    return "salary" in categories


def _amount(row: Mapping[str, Any]) -> float:
    try:
        return float(row.get("amount") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _day(row: Mapping[str, Any]) -> Optional[date]:
    try:
        return clock._transaction_date(row["ts"])
    except Exception:  # noqa: BLE001 - a row without a usable date can't be paired
        return None


def mark_own_transfers(
    rows: Iterable[Mapping[str, Any]],
    owner_words: frozenset[str],
    is_transfer_like: Callable[[Mapping[str, Any]], bool],
    match_days: int = OWN_TRANSFER_MATCH_DAYS,
) -> list[dict[str, Any]]:
    """``rows`` (Cash Flow rows of one user) with the own-transfer fields set."""
    out = [dict(row) for row in rows]
    for row in out:
        row["own_transfer"] = "name" if names_owner(row, owner_words) else None
        row["own_transfer_partner_id"] = None
        row["own_transfer_partner_day"] = None

    days = [_day(row) for row in out]
    anchors = sorted(
        (i for i, row in enumerate(out) if (row["own_transfer"] or is_transfer_like(row)) and days[i] is not None),
        key=lambda i: (days[i], int(out[i].get("transaction_id") or 0)),
    )
    paired: set[int] = set()
    for i in anchors:
        if i in paired:
            continue
        row, amount, day_i = out[i], _amount(out[i]), days[i]
        if day_i is None or abs(amount) < _AMOUNT_TOLERANCE:
            continue
        currency = str(row.get("currency") or "").upper()
        best: list[int] = []
        best_gap: Optional[int] = None
        for j, other in enumerate(out):
            day_j = days[j]
            if j == i or j in paired or day_j is None:
                continue
            if other.get("account_id") == row.get("account_id"):
                continue
            if str(other.get("currency") or "").upper() != currency:
                continue
            if abs(_amount(other) + amount) > _AMOUNT_TOLERANCE:
                continue
            gap = abs((day_j - day_i).days)
            if gap > match_days:
                continue
            if _is_salary_category(other) and not other["own_transfer"]:
                continue  # an employer's salary is income, never the other side of a move
            if best_gap is None or gap < best_gap:
                best, best_gap = [j], gap
            elif gap == best_gap:
                best.append(j)
        if len(best) != 1:
            continue  # nothing near, or ambiguous
        j = best[0]
        for a, b in ((i, j), (j, i)):
            out[a]["own_transfer"] = "pair"
            out[a]["own_transfer_partner_id"] = out[b].get("transaction_id")
            out[a]["own_transfer_partner_day"] = days[b]
        paired.update((i, j))
    return out
