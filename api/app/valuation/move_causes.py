"""Why net worth moved (#289): the data causes behind a period's change, next to the
Overview delta and History's "unusual move" flag.

The month bridge (D-60) splits a change into money, markets, FX and the rest. This
names the *data* events that can make a headline jump without the market doing it:

- ``first_statement``: an account's first data lands in the period (it wasn't there at
  the start), sized at its end value;
- ``catch_up``: an account's data jumps more than ``CATCH_UP_DAYS`` (a late upload that
  bundles several months, as History's catch-up flag), sized at the account's change
  less what the market did to its holdings;
- ``statement``: a new statement in the period moved an account by a large amount other
  than the market (cash, trades, positions added or removed), sized the same way;
- ``new_position``: a large holding not held at the start, in an account that was;
- ``fx_gap``: a currency had no rate, so its amounts were left out (D-30), no size;
- ``price_fallback``: live holdings valued at their statement price instead of a quote
  (D-21), sized at their value (context: those didn't move with the market).

A cause is ``significant`` when it has no size (an FX gap) or its size is at least
``SIGNIFICANT_SHARE`` of the change and ``CAUSE_MIN``. ``is_big_move`` is a change of at
least ``BIG_MOVE_PCT`` of the start. When a big move has no significant cause,
``none_reason`` says so: the move is the market's (or isn't recorded as data).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, Mapping, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.valuation.clock import _date_only
from app.valuation.state import _cash_positions

BIG_MOVE_PCT = 5.0
SIGNIFICANT_SHARE = 0.2
CAUSE_MIN = 1000.0
CATCH_UP_DAYS = 45
NONE_REASON = "No data cause found: a market move"
_EPS = 1e-9


def _day(value: date) -> str:
    """"6 Nov 2026", as lib/format.ts writes dates (D-46)."""
    return f"{value.day} {value.strftime('%b %Y')}"


def _account_names(db: Session, ids: Iterable[int]) -> Dict[int, str]:
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    stmt = text("SELECT id, name FROM accounts WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
    return {int(r["id"]): str(r["name"] or f"Account {r['id']}") for r in db.execute(stmt, {"ids": ids}).mappings()}


class _Account:
    __slots__ = ("value", "as_of", "market")

    def __init__(self) -> None:
        self.value = 0.0
        self.as_of: Optional[date] = None
        self.market = 0.0  # price + FX effect on its holdings (filled for the end side)

    def see(self, value: Any, as_of: Any) -> None:
        self.value += float(value or 0.0)
        day = _date_only(as_of)
        if day is not None and (self.as_of is None or day > self.as_of):
            self.as_of = day


def _accounts(cash: Iterable[Mapping[str, Any]], holdings: Iterable[Any]) -> Dict[int, _Account]:
    out: Dict[int, _Account] = {}
    for entry in cash:
        if entry.get("account_id") is None:
            continue
        out.setdefault(int(entry["account_id"]), _Account()).see(entry.get("value"), entry.get("as_of_date"))
    for held in holdings:
        if held.account_id is None:
            continue
        out.setdefault(int(held.account_id), _Account()).see(held.value, held.as_of)
    return out


def _market_effect(start: Any, end: Any) -> float:
    """What price and FX did to one holding held at both ends (the bridge's split)."""
    from app.valuation.bridge import _split  # the bridge imports this module

    split = _split(start, end)
    return split.price + split.fx


def _cause(
    key: str,
    label: str,
    *,
    amount: Optional[float],
    change: float,
    detail: Optional[str] = None,
    account_id: Optional[int] = None,
    as_of: Optional[date] = None,
    significant: Optional[bool] = None,
) -> Dict[str, Any]:
    if significant is None:
        significant = amount is None or abs(amount) >= max(CAUSE_MIN, SIGNIFICANT_SHARE * abs(change))
    return {
        "key": key,
        "label": label,
        "detail": detail,
        "amount": amount,
        "significant": bool(significant),
        "account_id": account_id,
        "as_of": as_of.isoformat() if as_of else None,
    }


def classify(
    *,
    start_total: float,
    end_total: float,
    start_accounts: Mapping[int, _Account],
    end_accounts: Mapping[int, _Account],
    start_holdings: Iterable[Any],
    end_holdings: Iterable[Any],
    names: Mapping[int, str],
    fx_flags: Mapping[str, Any],
    baseline_missing: bool,
    period_start: date,
) -> Dict[str, Any]:
    """The causes from already-valued facts (pure, so each cause is tested alone)."""
    change = end_total - start_total
    change_pct = (change / abs(start_total) * 100.0) if abs(start_total) > _EPS and not baseline_missing else None
    is_big_move = change_pct is not None and abs(change_pct) >= BIG_MOVE_PCT
    causes: list[Dict[str, Any]] = []

    start_by_key = {h_key(h): h for h in start_holdings}
    end_list = list(end_holdings)
    # Per account: the market part of its change (holdings held at both ends).
    market_by_account: Dict[int, float] = {}
    for held in end_list:
        before = start_by_key.get(h_key(held))
        if held.account_id is not None and before is not None and not before.is_empty():
            market_by_account[int(held.account_id)] = market_by_account.get(int(held.account_id), 0.0) + _market_effect(before, held)

    first_accounts: set[int] = set()
    for account_id, end in sorted(end_accounts.items()):
        start = start_accounts.get(account_id)
        name = names.get(account_id, f"Account {account_id}")
        if start is None or (abs(start.value) < _EPS and start.as_of is None):
            if abs(end.value) >= CAUSE_MIN:
                first_accounts.add(account_id)
                causes.append(_cause(
                    "first_statement", f"First data for {name}", amount=end.value, change=change,
                    detail=f"Not in the {_day(period_start)} figure: its whole value is new",
                    account_id=account_id, as_of=end.as_of,
                ))
            continue
        if end.as_of is None or start.as_of is None or end.as_of <= start.as_of:
            continue  # no new data for it in the period
        data_change = (end.value - start.value) - market_by_account.get(account_id, 0.0)
        gap_days = (end.as_of - start.as_of).days
        if gap_days > CATCH_UP_DAYS:
            causes.append(_cause(
                "catch_up", f"Catch-up statement for {name}", amount=data_change, change=change,
                detail=f"Its data jumped {gap_days} days ({_day(start.as_of)} to {_day(end.as_of)}): several months in one",
                account_id=account_id, as_of=end.as_of,
            ))
        elif abs(data_change) >= max(CAUSE_MIN, SIGNIFICANT_SHARE * abs(change)):
            causes.append(_cause(
                "statement", f"New statement for {name}", amount=data_change, change=change,
                detail=f"Statement of {_day(end.as_of)}: balances or positions changed, not prices",
                account_id=account_id, as_of=end.as_of,
            ))

    for held in end_list:
        before = start_by_key.get(h_key(held))
        if before is not None and not before.is_empty():
            continue
        if held.account_id is not None and int(held.account_id) in first_accounts:
            continue
        if abs(held.value) < max(CAUSE_MIN, SIGNIFICANT_SHARE * abs(change)):
            continue
        where = names.get(int(held.account_id)) if held.account_id is not None else None
        causes.append(_cause(
            "new_position", f"New position: {held.symbol}", amount=held.value, change=change,
            detail=f"Not held on {_day(period_start)}" + (f" ({where})" if where else ""),
            account_id=int(held.account_id) if held.account_id is not None else None, as_of=held.as_of,
        ))

    missing = list(fx_flags.get("fx_missing_currencies") or [])
    if missing:
        causes.append(_cause(
            "fx_gap", f"No exchange rate for {', '.join(missing)}", amount=None, change=change,
            detail="Amounts in those currencies are left out (never converted at 1.0)",
        ))

    fallback = [h for h in end_list if getattr(h, "fallback_reason", None)]
    if fallback:
        value = sum(h.value for h in fallback)
        causes.append(_cause(
            "price_fallback", f"{len(fallback)} holding(s) at their statement price", amount=value, change=change,
            detail="No usable quote: they didn't move with the market", significant=False,
        ))

    causes.sort(key=lambda c: (not c["significant"], -abs(c["amount"]) if c["amount"] is not None else float("-inf")))
    has_significant = any(c["significant"] for c in causes)
    return {
        "change": change,
        "change_pct": change_pct,
        "is_big_move": is_big_move,
        "causes": causes,
        "none_reason": NONE_REASON if is_big_move and not has_significant else None,
    }


def h_key(held: Any) -> tuple:
    return (held.account_id, held.mover_key)


def move_causes(
    db: Session,
    current_user_id: int,
    *,
    base_currency: str,
    start_anchor: datetime,
    end_anchor: datetime,
    start_total: float,
    end_total: float,
    start_holdings: list[Any],
    end_holdings: list[Any],
    fx_flags: Mapping[str, Any],
    baseline_missing: bool,
) -> Dict[str, Any]:
    start_accounts = _accounts(_cash_positions(db, start_anchor, base_currency, current_user_id), start_holdings)
    end_accounts = _accounts(_cash_positions(db, end_anchor, base_currency, current_user_id), end_holdings)
    names = _account_names(db, set(start_accounts) | set(end_accounts))
    return classify(
        start_total=start_total,
        end_total=end_total,
        start_accounts=start_accounts,
        end_accounts=end_accounts,
        start_holdings=start_holdings,
        end_holdings=end_holdings,
        names=names,
        fx_flags=fx_flags,
        baseline_missing=baseline_missing,
        period_start=start_anchor.date(),
    )
