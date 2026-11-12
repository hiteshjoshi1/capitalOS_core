"""'Since your last visit' on Overview (#408, U3, D-112).

A visit is a load of Overview. The stored mark (``user_last_visit``) is when the user last
looked and the live net worth shown then; the strip compares now with it: the change in
net worth (same base currency only), imports since, and what needs action now.

The mark moves on a visit only when it is over ``LAST_VISIT_MIN_GAP`` old, or on "Dismiss":
so reloading Overview, or coming back from another page, within a session keeps the same
comparison until the user dismisses it, and the next session compares with the last one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.auth_context import CurrentUser
from app.models import Account, ImportJob
from app.models.last_visit import UserLastVisit
from app.valuation.clock import _app_today, _month_start_of, _month_view_anchor
from app.valuation.facts import _networth_components
from app.valuation.money import D

# A visit within this of the stored one doesn't move the mark.
LAST_VISIT_MIN_GAP = timedelta(hours=1)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def live_net_worth(db: Session, user_id: int, base_currency: str) -> Decimal:
    """Overview's live headline: the open month's view anchor, with live prices."""
    anchor, _is_live = _month_view_anchor(_month_start_of(_app_today()))
    return D(_networth_components(db, anchor, base_currency, user_id, price_overlay=True)["total"])


def _imports_since(db: Session, user_id: int, since: datetime) -> int:
    return (
        db.query(ImportJob)
        .join(Account, Account.id == ImportJob.account_id)
        .filter(Account.user_id == user_id, ImportJob.status == "IMPORTED", ImportJob.created_at > since)
        .count()
    )


def _needs_action(db: Session, user: CurrentUser) -> Optional[int]:
    from app.services.inbox import build_inbox  # local: inbox imports a lot

    try:
        return build_inbox(db, user).count
    except Exception:  # noqa: BLE001 - the strip still shows the rest
        return None


def since_last_visit(db: Session, user: CurrentUser, base_currency: str) -> dict[str, Any]:
    """What changed since the stored visit. Read-only (``mark_visit`` moves the mark)."""
    base = base_currency.upper()
    row = db.get(UserLastVisit, user.id)
    if row is None:
        return {"first_visit": True, "base_currency": base}
    seen_at = _aware(row.seen_at)
    now_value = live_net_worth(db, user.id, base)
    then_value = D(row.net_worth) if row.net_worth is not None else None
    comparable = then_value is not None and (row.base_currency or "").upper() == base
    return {
        "first_visit": False,
        "seen_at": seen_at.isoformat(),
        "base_currency": base,
        "net_worth_then": float(then_value) if comparable and then_value is not None else None,
        "net_worth_now": float(now_value),
        "change": float(now_value - then_value) if comparable and then_value is not None else None,
        # The stored figure is in another base currency: say so rather than convert it.
        "currency_changed": then_value is not None and not comparable,
        "imports_since": _imports_since(db, user.id, seen_at),
        "needs_action": _needs_action(db, user),
    }


def mark_visit(
    db: Session, user: CurrentUser, base_currency: str, *, force: bool = False, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Record a visit: moves the mark if it's over LAST_VISIT_MIN_GAP old, or ``force`` (Dismiss)."""
    now = _aware(now or datetime.now(timezone.utc))
    base = base_currency.upper()
    row = db.get(UserLastVisit, user.id)
    moved = row is None or force or now - _aware(row.seen_at) >= LAST_VISIT_MIN_GAP
    if moved:
        value = live_net_worth(db, user.id, base).quantize(Decimal("0.01"))
        if row is None:
            row = UserLastVisit(user_id=user.id, seen_at=now, net_worth=value, base_currency=base)
            db.add(row)
        else:
            row.seen_at, row.net_worth, row.base_currency = now, value, base
        db.commit()
    assert row is not None
    return {"moved": moved, "seen_at": _aware(row.seen_at).isoformat()}
