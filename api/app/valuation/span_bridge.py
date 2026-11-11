"""History → Compare (#398, U20, D-110): the bridge between two months' closes.

Month A's close to month B's close is the sum of the month bridges A+1 … B, each
computed exactly as Overview's "This month" (``bridge.month_bridge``, Decimal inside,
D-106). Every month's start + lines + unexplained = its end, and one month's end
anchor is the next month's start anchor, so the sums telescope: the span's start +
lines + unexplained = its end, exactly, and Sep→Nov is Sep→Oct + Oct→Nov line by line.
Should two consecutive months not meet (a later SNAPSHOT_DAY can make two views share
or skip an anchor), the difference is its own Unexplained part, so the span still adds up.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List

from sqlalchemy.orm import Session

from app.valuation import bridge as month
from app.valuation import fx
from app.valuation.clock import _add_months, _app_today, _configured_snapshot_day
from app.valuation.money import ZERO, D, dsum, float_edge

SPAN_MONTHS_MAX = 60
# Every mover and trade of each month is needed to merge them; the span then keeps the top.
_ALL = 100_000


class SpanError(ValueError):
    """A span the bridge can't be built for (from after to, too long, in the future)."""


def _month_key(start: datetime) -> str:
    return start.strftime("%Y-%m")


def _month_short(key: str) -> str:
    return datetime.strptime(key, "%Y-%m").strftime("%b %Y")


def _merge_items(groups: Iterable[List[Dict[str, Any]]], total: Any) -> List[Dict[str, Any]]:
    """A part's items over the months: same label summed, then ranked and capped like a
    month's (``bridge._items``), with a last "Rest" so they still add up to the part."""
    merged: Dict[str, Dict[str, Any]] = {}
    for items in groups:
        for item in items:
            label = item["label"]
            if label == "Rest" or label.startswith("Rest:"):
                continue  # recomputed below
            if label not in merged:
                merged[label] = dict(item)
                continue
            have = merged[label]
            if have["amount"] is None or item["amount"] is None:
                have["amount"] = have["amount"] if item["amount"] is None else item["amount"]
            else:
                have["amount"] = have["amount"] + item["amount"]
            have["reason"] = item.get("reason") or have.get("reason")
            have["link"] = item.get("link") or have.get("link")
    return month._items(merged.values(), D(total))


def _merge_parts(groups: Iterable[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    order: List[str] = []
    labels: Dict[str, str] = {}
    amounts: Dict[str, Any] = {}
    items: Dict[str, List[List[Dict[str, Any]]]] = {}
    for parts in groups:
        for part in parts:
            key = part["key"]
            if key not in amounts:
                order.append(key)
                amounts[key] = ZERO
                items[key] = []
            amounts[key] += part["amount"]
            labels[key] = part["label"]  # the newest month's wording
            items[key].append(part.get("items") or [])
    return [month._part(key, labels[key], amounts[key], _merge_items(items[key], amounts[key])) for key in order]


def _merge_line(key: str, lines: List[tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """One line over the months (``lines``: (month, that month's line)). Amounts and parts
    add up; a status other than ok in some months reads partial; reasons and notes keep
    the month they're about."""
    statuses = {line["status"] for _m, line in lines}
    status = statuses.pop() if len(statuses) == 1 else "partial"
    reasons: List[str] = []
    for m, line in lines:
        if line.get("reason") and line["status"] != "ok":
            text = f"{_month_short(m)}: {line['reason']}"
            if text not in reasons:
                reasons.append(text)
    if status == "ok":
        # An "ok" line's reason is an explanation (e.g. Catch-up), the same each month.
        reason = next((line["reason"] for _m, line in reversed(lines) if line.get("reason")), None)
    else:
        reason = "; ".join(reasons[:3]) + (f"; and {len(reasons) - 3} more month(s)" if len(reasons) > 3 else "") or None
    label = lines[-1][1]["label"]
    if key == "dividends_interest" and any(
        p["key"] == "staking" for _m, line in lines for p in line.get("parts") or []
    ):
        label = "Dividends, interest & staking"
    notes = [
        month._note(note["key"], f"{_month_short(m)}: {note['label']}", note.get("amount"))
        for m, line in lines
        for note in line.get("notes") or []
    ]
    parts = _merge_parts(line.get("parts") or [] for _m, line in lines)
    # With parts, the line is their sum (summing per part, then the parts, can differ from
    # the months' totals in Decimal's last digit; the parts must add up to the line).
    amount = dsum(p["amount"] for p in parts) if parts else dsum(line["amount"] for _m, line in lines)
    return month._line(key, label, amount, status=status, reason=reason, parts=parts, notes=notes)


def _merge_movers(bridges: List[tuple[str, Dict[str, Any]]], limit: int) -> List[Dict[str, Any]]:
    merged: Dict[tuple, Dict[str, Any]] = {}
    for _m, b in bridges:
        for mover in b["movers"]:
            key = month.stock_mover_key(mover["asset_id"], mover["symbol"])
            have = merged.get(key)
            if have is None:
                merged[key] = {**mover, "_causes": {mover["cause"]}}
                continue
            for field in ("price_effect", "quantity_effect", "fx_effect", "market_effect"):
                have[field] = have[field] + mover[field]
            have["end_value"] = mover["end_value"]
            have["_causes"].add(mover["cause"])
    rows = []
    for mover in merged.values():
        mover["change"] = mover["end_value"] - mover["start_value"]
        causes = mover.pop("_causes")
        if causes == {"unknown"}:
            mover["cause"] = "unknown"
        else:
            mover["cause"] = "fx" if abs(mover["fx_effect"]) > abs(mover["price_effect"]) else "price"
        if abs(mover["market_effect"]) < 0.005 and mover["cause"] != "unknown":
            continue
        rows.append(mover)
    rows.sort(key=lambda m: (-abs(m["market_effect"]), str(m["symbol"]).lower()))
    return rows[:limit]


def _merge_trades(bridges: List[tuple[str, Dict[str, Any]]], limit: int) -> List[Dict[str, Any]]:
    merged: Dict[tuple, Dict[str, Any]] = {}
    for _m, b in bridges:
        for trade in b["trades"]:
            key = month.stock_mover_key(trade["asset_id"], trade["symbol"])
            have = merged.get(key)
            if have is None:
                merged[key] = dict(trade)
            else:
                have["amount"] = have["amount"] + trade["amount"]
                have["cash_recorded"] = have["cash_recorded"] or trade["cash_recorded"]
    rows = []
    for trade in merged.values():
        if abs(trade["amount"]) < month.TRADE_MIN:
            continue
        crypto = trade["asset_class"] == "CRYPTO"
        positive = trade["amount"] > 0
        trade["side"] = ("moved_in" if positive else "moved_out") if crypto else ("bought" if positive else "sold")
        rows.append(trade)
    rows.sort(key=lambda t: (-abs(t["amount"]), str(t["symbol"]).lower()))
    return rows[:limit]


def _months(from_month: str, to_month: str) -> tuple[datetime, List[datetime]]:
    from app.valuation.clock import _parse_month

    try:
        a, b = _parse_month(from_month), _parse_month(to_month)
    except Exception as exc:  # noqa: BLE001
        raise SpanError("from and to are months, YYYY-MM") from exc
    if a > b:
        raise SpanError("from must be the same month as to or earlier")
    if _month_key(b) > _app_today().strftime("%Y-%m"):
        raise SpanError("to can't be a future month")
    months: List[datetime] = []
    cursor = _add_months(a, 1)
    while cursor <= b:
        months.append(cursor)
        cursor = _add_months(cursor, 1)
        if len(months) > SPAN_MONTHS_MAX:
            raise SpanError(f"at most {SPAN_MONTHS_MAX} months apart")
    return a, months


@float_edge
def span_bridge(
    db: Session, current_user_id: int, from_month: str, to_month: str, base_currency: str, movers_limit: int = 5
) -> Dict[str, Any]:
    """A's close → B's close, as the sum of the month bridges A+1 … B (D-110)."""
    raw = month.month_bridge.__wrapped__  # type: ignore[attr-defined]  # Decimal inside; the edge is ours
    a, months = _months(from_month, to_month)
    base_currency = base_currency.upper()

    if not months:  # A = B: nothing between a month's close and itself
        one = raw(db, current_user_id, from_month, a, base_currency, movers_limit=1)
        point = one["end"]
        return {
            "from_month": from_month,
            "to_month": to_month,
            "base_currency": base_currency,
            "snapshot_day": _configured_snapshot_day(),
            "is_live": one["is_live"],
            "months": [],
            "start": point,
            "end": point,
            "change": ZERO,
            "lines": [],
            "unexplained": month._line("unexplained", "Unexplained", ZERO, parts=[]),
            "liabilities_change": ZERO,
            "movers": [],
            "trades": [],
            **fx.fx_status(),
        }

    bridges: List[tuple[str, Dict[str, Any]]] = []
    for start in months:
        key = _month_key(start)
        b = raw(db, current_user_id, key, start, base_currency, movers_limit=_ALL)
        if bridges and b["period_start"] == bridges[-1][1]["period_start"] and b["period_end"] == bridges[-1][1]["period_end"]:
            continue  # the same period twice (a later SNAPSHOT_DAY): counted once
        bridges.append((key, b))

    # Where one month's end and the next one's start don't meet, the jump between them.
    gaps: List[Dict[str, Any]] = []
    for (_pm, prev), (m, cur) in zip(bridges, bridges[1:]):
        jump = cur["start"]["value"] - prev["end"]["value"]
        if jump:
            gaps.append(month._item(f"{_month_short(m)}: start differs from the month before's end", jump))

    order: List[str] = []
    by_key: Dict[str, List[tuple[str, Dict[str, Any]]]] = {}
    for m, b in bridges:
        for line in b["lines"]:
            if line["key"] not in by_key:
                order.append(line["key"])
                by_key[line["key"]] = []
            by_key[line["key"]].append((m, line))
    fixed = [k for k in ("new_money", "markets", "fx", "dividends_interest", "cash_kept") if k in by_key]
    order = fixed + [k for k in order if k not in fixed]
    lines = [_merge_line(k, by_key[k]) for k in order]

    unexplained = _merge_line("unexplained", [(m, b["unexplained"]) for m, b in bridges])
    if gaps:
        jump_total = dsum(g["amount"] for g in gaps)
        unexplained["amount"] += jump_total
        unexplained["parts"].append(month._part("between_months", "Between months: a start that differs from the month before's end", jump_total, gaps))
    # Parts under a cent are left out, as in a month; "other" always stays (it closes the sum).
    unexplained["parts"] = [p for p in unexplained["parts"] if p["key"] == "other" or abs(p["amount"]) >= 0.005]
    unexplained["parts"].sort(key=lambda p: p["key"] == "other")
    unexplained["reason"] = "What the lines above can't account for over these months; its known parts are listed"

    first, last = bridges[0][1], bridges[-1][1]
    start, end = first["start"], last["end"]
    change = end["value"] - start["value"]
    # Unexplained closes the sum exactly, as in a month: it is the change the lines don't
    # cover, and its "other" part is what its named parts don't (equal to the months' sums
    # up to Decimal's last digit).
    unexplained["amount"] = change - dsum(line["amount"] for line in lines)
    named = dsum(p["amount"] for p in unexplained["parts"] if p["key"] != "other")
    for part in unexplained["parts"]:
        if part["key"] == "other":
            part["amount"] = unexplained["amount"] - named
            part["items"] = _merge_items([part["items"]], part["amount"])
    return {
        "from_month": from_month,
        "to_month": to_month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        "is_live": last["is_live"],
        "months": [
            {"month": m, "start_value": b["start"]["value"], "end_value": b["end"]["value"], "change": b["change"]}
            for m, b in bridges
        ],
        "start": start,
        "end": end,
        "change": change,
        "lines": lines,
        "unexplained": unexplained,
        "liabilities_change": dsum(b["liabilities_change"] for _m, b in bridges),
        "movers": _merge_movers(bridges, movers_limit),
        "trades": _merge_trades(bridges, movers_limit),
        **fx.fx_status(),
    }
