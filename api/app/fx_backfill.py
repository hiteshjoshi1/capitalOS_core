"""FX back-fill (#290, D-75): fetch past rates once for the span of a user's data.

Without historical rates every past month leaves foreign holdings out (D-30) until
a read happens to fetch them. The back-fill fetches them up front, for the whole
span of the user's imported data, and stores them in the shared ``fx_rates`` table
(``fx._store_rows``, which also marks History dirty from the earliest new date,
#138, and drops cached rates, #188).

Rules:

- **Span**: the earliest to the latest dated fact the user owns (bank/card balance
  snapshots, broker position and cash snapshots, transactions), starting one
  lookback window earlier (so the first date has rates to look back to) and ending
  yesterday (today's rate comes from the daily fill).
- **Skip what's stored**: Frankfurter answers every currency for a date at once, so
  a weekday is covered when it has a Frankfurter row, or sits in a short hole
  between two stored rows at most ``HOLE_DAYS`` apart (an ECB holiday: Thursday to
  Tuesday over Easter is 5 days). Only uncovered weekdays are fetched, so a second
  run with nothing new fetches nothing (idempotent). Days after the last stored
  row are uncovered: data that stops on a Friday doesn't cover the Monday after.
- **Cap**: uncovered days are merged into ranges (gaps of up to a week joined), each
  at most ``MAX_DAYS_PER_REQUEST`` long, newest first, and at most
  ``FX_BACKFILL_MAX_REQUESTS`` (default 12) requests per run. What the cap leaves is
  reported, and the next run continues from there.
- **Currencies the provider doesn't publish** are named (``unsupported``): a held
  currency with no Frankfurter row on days that have Frankfurter rows.
- Runs record a ``job_runs`` row (job ``fx_backfill``), shown on Data Hub.
- The endpoint is admin-only (shared data, #152). After an import it also runs in
  the background for the importing user (``backfill_in_background``), unless
  remote FX is off.
"""
from __future__ import annotations

import bisect
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app import fx

logger = logging.getLogger("capitalos.fx_backfill")

JOB_FX_BACKFILL = "fx_backfill"
MAX_DAYS_PER_REQUEST = 366
HOLE_DAYS = 5
JOIN_GAP_DAYS = 7


def max_requests() -> int:
    try:
        return max(1, int(os.getenv("FX_BACKFILL_MAX_REQUESTS", "12")))
    except ValueError:
        return 12


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# The user's dated facts: (date, currency). Ownership through accounts.user_id, as
# the canonical reads do (broker facts via broker_accounts.legacy_account_id).
_FACTS_SQL = """
    SELECT bs.as_of_date AS d, bs.currency AS c
    FROM account_balance_snapshots bs JOIN accounts a ON a.id = bs.account_id
    WHERE a.user_id = :user_id
    UNION ALL
    SELECT ps.report_date, ps.currency
    FROM portfolio_position_snapshots ps
    JOIN broker_accounts ba ON ba.id = ps.broker_account_id
    JOIN accounts a ON a.id = ba.legacy_account_id
    WHERE a.user_id = :user_id
    UNION ALL
    SELECT cs.report_date, cs.currency
    FROM portfolio_cash_balance_snapshots cs
    JOIN broker_accounts ba ON ba.id = cs.broker_account_id
    JOIN accounts a ON a.id = ba.legacy_account_id
    WHERE a.user_id = :user_id
    UNION ALL
    SELECT t.ts, t.currency
    FROM transactions t JOIN accounts a ON a.id = t.account_id
    WHERE a.user_id = :user_id
"""


def data_span(db: Session, user_id: int) -> Optional[tuple[date, date]]:
    """Earliest and latest date of the user's dated facts (None with no data)."""
    row = db.execute(
        text(f"SELECT MIN(f.d), MAX(f.d) FROM ({_FACTS_SQL}) f"), {"user_id": user_id}
    ).first()
    if row is None:
        return None
    lo, hi = _as_date(row[0]), _as_date(row[1])
    if lo is None or hi is None:
        return None
    return lo, hi


def held_currencies(db: Session, user_id: int, base: str) -> list[str]:
    """Every 3-letter currency in the user's facts and accounts, plus the base."""
    rows = db.execute(
        text(
            f"SELECT DISTINCT f.c FROM ({_FACTS_SQL}) f "
            "UNION SELECT DISTINCT a.currency FROM accounts a WHERE a.user_id = :user_id"
        ),
        {"user_id": user_id},
    ).fetchall()
    codes = {str(r[0]).strip().upper() for r in rows if r[0]}
    codes.add(base.upper())
    return sorted(c for c in codes if len(c) == 3 and c.isalpha())


def _frankfurter_days(db: Session, lo: date, hi: date) -> set[date]:
    rows = db.execute(
        text(
            "SELECT DISTINCT rate_date FROM fx_rates "
            "WHERE source = 'frankfurter' AND base = 'EUR' AND rate_date BETWEEN :lo AND :hi"
        ),
        {"lo": lo.isoformat(), "hi": hi.isoformat()},
    ).fetchall()
    return {d for d in (_as_date(r[0]) for r in rows) if d is not None}


def _unsupported(db: Session, lo: date, hi: date, currencies: list[str]) -> list[str]:
    """Held currencies Frankfurter doesn't publish: no row for them on any day
    that has Frankfurter rows (EUR itself is the base of those rows)."""
    wanted = [c for c in currencies if c != "EUR"]
    if not wanted or not _frankfurter_days(db, lo, hi):
        return []
    rows = db.execute(
        text(
            "SELECT DISTINCT quote FROM fx_rates WHERE source = 'frankfurter' AND base = 'EUR' "
            "AND rate_date BETWEEN :lo AND :hi AND quote IN :currencies"
        ).bindparams(bindparam("currencies", expanding=True)),
        {"lo": lo.isoformat(), "hi": hi.isoformat(), "currencies": wanted},
    ).fetchall()
    published = {str(r[0]).upper() for r in rows}
    return [c for c in wanted if c not in published]


def uncovered_days(start: date, end: date, stored: set[date]) -> list[date]:
    """Weekdays in [start, end] with no stored Frankfurter row, except those in a
    hole of at most HOLE_DAYS between two stored rows (a provider holiday)."""
    days = sorted(stored)
    out: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in stored:
            idx = bisect.bisect_left(days, day)
            before = days[idx - 1] if idx > 0 else None
            after = days[idx] if idx < len(days) else None
            if before is None or after is None or (after - before).days > HOLE_DAYS:
                out.append(day)
        day += timedelta(days=1)
    return out


def request_ranges(days: list[date]) -> list[tuple[date, date]]:
    """Uncovered days as fetch ranges: gaps of up to JOIN_GAP_DAYS joined, each
    range at most MAX_DAYS_PER_REQUEST long, newest first."""
    ranges: list[tuple[date, date]] = []
    for day in sorted(days):
        if ranges and (day - ranges[-1][1]).days <= JOIN_GAP_DAYS and (day - ranges[-1][0]).days < MAX_DAYS_PER_REQUEST:
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return list(reversed(ranges))


@dataclass
class BackfillPlan:
    span_start: Optional[date]
    span_end: Optional[date]
    currencies: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    uncovered_days: int = 0
    requests: list[tuple[date, date]] = field(default_factory=list)
    remaining_requests: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "span_start": self.span_start.isoformat() if self.span_start else None,
            "span_end": self.span_end.isoformat() if self.span_end else None,
            "currencies": self.currencies,
            "unsupported_currencies": self.unsupported,
            "uncovered_days": self.uncovered_days,
            "planned_requests": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in self.requests],
            "remaining_requests": self.remaining_requests,
        }


def plan_backfill(db: Session, user_id: int, base: str, *, today: Optional[date] = None) -> BackfillPlan:
    today = today or datetime.now(tz=timezone.utc).date()
    span = data_span(db, user_id)
    if span is None:
        return BackfillPlan(None, None, currencies=[base.upper()])
    lo = span[0] - timedelta(days=fx.lookback_days())
    hi = min(span[1], today - timedelta(days=1))
    currencies = held_currencies(db, user_id, base)
    if hi < lo:
        return BackfillPlan(span[0], span[1], currencies=currencies)
    stored = _frankfurter_days(db, lo - timedelta(days=HOLE_DAYS), hi + timedelta(days=HOLE_DAYS))
    gaps = uncovered_days(lo, hi, stored)
    ranges = request_ranges(gaps)
    cap = max_requests()
    return BackfillPlan(
        span_start=span[0],
        span_end=span[1],
        currencies=currencies,
        unsupported=_unsupported(db, lo, hi, currencies),
        uncovered_days=len(gaps),
        requests=ranges[:cap],
        remaining_requests=max(0, len(ranges) - cap),
    )


def _frankfurter_rows(start: date, end: date) -> list[dict[str, Any]]:
    fetched_at = datetime.now(tz=timezone.utc).isoformat()
    return [
        {"rate_date": day.isoformat(), "base": "EUR", "quote": quote, "rate": rate, "source": "frankfurter", "fetched_at": fetched_at}
        for day, table in fx._fetch_frankfurter(start, end).items()
        for quote, rate in table.items()
        if rate and rate > 0 and quote != "EUR"
    ]


def run_backfill(
    db: Session, user_id: int, base: str, *, trigger: str = "manual", today: Optional[date] = None
) -> dict[str, Any]:
    """Fetch and store the planned ranges. Returns the plan plus what happened.
    Never raises for a provider failure: a failed range is counted and the rest go on."""
    from app.core.job_runs import STATUS_FAILED, STATUS_NO_NEW_DATA, STATUS_PARTIAL, STATUS_SUCCESS, record_job_run

    started_at = datetime.now(tz=timezone.utc)
    plan = plan_backfill(db, user_id, base, today=today)
    result: dict[str, Any] = {**plan.as_dict(), "fetched_requests": 0, "failed_requests": 0, "rows_stored": 0}
    if not plan.requests:
        result["status"] = "up_to_date"
    elif not fx.remote_enabled():
        result["status"] = "remote_disabled"
    else:
        last_error: Optional[BaseException] = None
        for start, end in plan.requests:
            try:
                rows = _frankfurter_rows(start, end)
                result["rows_stored"] += fx._store_rows(rows)
                result["fetched_requests"] += 1
            except Exception as exc:  # noqa: BLE001 - one failed range must not stop the rest
                result["failed_requests"] += 1
                last_error = exc
                logger.warning(
                    "fx_backfill_request_failed",
                    extra={"event": "fx_backfill_request_failed", "error_class": exc.__class__.__name__},
                )
        if result["failed_requests"] and not result["fetched_requests"]:
            result["status"] = "failed"
        elif result["failed_requests"] or plan.remaining_requests:
            result["status"] = "partial"
        else:
            result["status"] = "completed"
        job_status = {
            "failed": STATUS_FAILED,
            "partial": STATUS_PARTIAL,
            "completed": STATUS_SUCCESS if result["rows_stored"] else STATUS_NO_NEW_DATA,
        }[result["status"]]
        record_job_run(
            db,
            job=JOB_FX_BACKFILL,
            trigger=trigger,
            status=job_status,
            started_at=started_at,
            data_as_of=plan.requests[0][1] if result["fetched_requests"] else None,
            data_advanced=bool(result["rows_stored"]),
            error=last_error,
            details={k: result[k] for k in ("fetched_requests", "failed_requests", "rows_stored", "remaining_requests")},
        )
    logger.info(
        "fx_backfill_finished",
        extra={
            "event": "fx_backfill_finished",
            "status": result["status"],
            "rows": result["rows_stored"],
            "requests": result["fetched_requests"],
        },
    )
    return result


def _after_import_enabled() -> bool:
    # The env itself, like fx._http_get_json: tests set FX_DISABLE_REMOTE=1.
    return os.getenv("FX_DISABLE_REMOTE", "0") != "1" and os.getenv("FX_BACKFILL_AFTER_IMPORT", "1") != "0"


def backfill_in_background(user_id: int, base: str = "SGD") -> Optional[threading.Thread]:
    """After an import: back-fill in a daemon thread with its own session, so the
    upload response doesn't wait on the provider. Off when remote FX is off."""
    if not _after_import_enabled():
        return None

    def _run() -> None:
        from app.core.job_runs import TRIGGER_SCHEDULED
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            run_backfill(db, user_id, base, trigger=TRIGGER_SCHEDULED)
        except Exception as exc:  # noqa: BLE001 - background work must never surface
            logger.warning("fx_backfill_failed", extra={"event": "fx_backfill_failed", "error_class": exc.__class__.__name__})
        finally:
            db.close()

    thread = threading.Thread(target=_run, name=f"fx-backfill-{user_id}", daemon=True)
    thread.start()
    return thread
