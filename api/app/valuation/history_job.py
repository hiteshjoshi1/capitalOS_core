"""History generation in the background (#292, D-88).

"Generate history" used to be one blocking request: every month of the range valued in
turn, each one free to ask the FX provider for its own dates. On a first run that is
dozens of months and as many provider calls, behind a spinner with no progress.

Now a run is a background thread with a progress record the History page polls:

1. **Past rates first, capped.** ``fx_backfill.run_backfill`` fetches the missing rates
   for the user's data span once, at most ``FX_BACKFILL_MAX_REQUESTS`` requests (#290).
   What the cap leaves is reported; the next run continues from there.
2. **Then every month from stored rates only** (``fx.stored_rates_only``): a month with
   no rate within the lookback uses the newest older stored one (flagged stale, as any
   read does), never another provider call.

The default range is the span of the user's data (``history_span``): from the month of
the earliest imported fact (balances, positions, cash, transactions, wallet snapshots)
to now, at most 120 months. One run per user and currency at a time: starting again
while one runs returns the running one.

Progress lives in memory (one API process, D-88); a finished run also leaves a
``job_runs`` row (job ``history_generate``). A restart mid-run loses the progress
record, not data: rows are written in one transaction at the end, as before.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app import fx, fx_backfill
from app.core.clock import use_timezone
from app.services.user_preferences import effective_timezone
from app.valuation import clock
from app.valuation.history import _refresh_wealth_rollups, _trailing_month_keys

logger = logging.getLogger("capitalos.history_job")

MAX_MONTHS = 120
DEFAULT_MONTHS = 24


@dataclass
class HistoryRun:
    user_id: int
    base_currency: str
    months: int
    status: str = "running"  # running | completed | failed
    stage: str = "fx"  # fx | months | done
    months_total: int = 0
    months_done: int = 0
    current_month: Optional[str] = None
    months_written: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    finished_at: Optional[datetime] = None
    fx: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stage": self.stage,
            "base_currency": self.base_currency,
            "months": self.months,
            "months_total": self.months_total,
            "months_done": self.months_done,
            "current_month": self.current_month,
            "months_written": self.months_written,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "fx": self.fx,
            "error": self.error,
        }


_RUNS: dict[tuple[int, str], HistoryRun] = {}
_THREADS: dict[tuple[int, str], threading.Thread] = {}
_LOCK = threading.Lock()


def _key(user_id: int, base_currency: str) -> tuple[int, str]:
    return (user_id, base_currency.upper())


def _as_date(value: Any) -> Optional[date]:
    return fx_backfill._as_date(value)


def history_span(db: Session, user_id: int) -> Optional[dict[str, Any]]:
    """The span History should cover by default: the month of the user's earliest
    dated fact to the current month (at most MAX_MONTHS). None with no data."""
    span = fx_backfill.data_span(db, user_id)
    first = span[0] if span else None
    row = db.execute(
        text(
            "SELECT MIN(s.as_of_date) FROM crypto_wallet_snapshots s "
            "JOIN crypto_wallets w ON w.id = s.wallet_id WHERE w.user_id = :user_id"
        ),
        {"user_id": user_id},
    ).first()
    crypto_first = _as_date(row[0]) if row else None
    if crypto_first is not None and (first is None or crypto_first < first):
        first = crypto_first
    if first is None:
        return None
    current = clock._current_anchor_ts()
    months = (current.year - first.year) * 12 + (current.month - first.month) + 1
    months = max(1, min(MAX_MONTHS, months))
    return {"first_month": f"{first.year:04d}-{first.month:02d}", "months": months}


def default_months(db: Session, user_id: int) -> int:
    span = history_span(db, user_id)
    return span["months"] if span else DEFAULT_MONTHS


def status(user_id: int, base_currency: str) -> dict[str, Any]:
    """The newest run's progress for this user and currency, or ``idle``."""
    with _LOCK:
        run = _RUNS.get(_key(user_id, base_currency))
        if run is None:
            return {
                **HistoryRun(user_id, base_currency.upper(), 0, status="idle", stage="done").as_dict(),
                "started_at": None,
            }
        return run.as_dict()


def start(
    session_factory: Callable[[], Session],
    user_id: int,
    base_currency: str,
    months: int,
) -> dict[str, Any]:
    """Start a run in a daemon thread with its own session; a running one is returned as is."""
    key = _key(user_id, base_currency)
    with _LOCK:
        running = _RUNS.get(key)
        if running is not None and running.status == "running":
            return running.as_dict()
        run = HistoryRun(user_id, key[1], max(1, min(MAX_MONTHS, months)))
        _RUNS[key] = run
        thread = threading.Thread(
            target=_run, args=(session_factory, run), name=f"history-{user_id}-{key[1]}", daemon=True
        )
        _THREADS[key] = thread
        snapshot = run.as_dict()
    thread.start()
    return snapshot


def session_factory_for(db: Session) -> Callable[[], Session]:
    """A factory bound to the same database as the request's session."""
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


def wait(user_id: int, base_currency: str, timeout: float = 30.0) -> None:
    """Join the run's thread (tests, scripts)."""
    thread = _THREADS.get(_key(user_id, base_currency))
    if thread is not None:
        thread.join(timeout)


def _update(run: HistoryRun, **changes: Any) -> None:
    with _LOCK:
        for name, value in changes.items():
            setattr(run, name, value)


def _run(session_factory: Callable[[], Session], run: HistoryRun) -> None:
    from app.core.job_runs import JOB_HISTORY, STATUS_FAILED, STATUS_NO_NEW_DATA, STATUS_SUCCESS, TRIGGER_MANUAL, record_job_run

    db = session_factory()
    error: Optional[BaseException] = None
    try:
        with use_timezone(effective_timezone(db, run.user_id)):
            if fx.remote_enabled():
                result = fx_backfill.run_backfill(db, run.user_id, run.base_currency, trigger=TRIGGER_MANUAL)
                _update(run, fx={
                    k: result.get(k)
                    for k in ("status", "fetched_requests", "failed_requests", "remaining_requests", "unsupported_currencies")
                })
            else:
                _update(run, fx={"status": "remote_disabled"})

            month_keys = _trailing_month_keys(run.months)
            _update(run, stage="months", months_total=len(month_keys))

            def _progress(done: int, _total: int, month: str) -> None:
                _update(run, months_done=done, current_month=month)

            with fx.stored_rates_only():
                result = _refresh_wealth_rollups(
                    db, run.user_id, run.base_currency, months=month_keys, force=True, on_month=_progress,
                )
            _update(
                run,
                status="completed",
                stage="done",
                months_done=len(month_keys),
                current_month=None,
                months_written=result["written"],
                finished_at=datetime.now(tz=timezone.utc),
            )
    except Exception as exc:  # noqa: BLE001 - the page shows the failure; nothing else may break
        error = exc
        db.rollback()
        logger.warning("history_generate_failed", extra={"event": "history_generate_failed", "error_class": exc.__class__.__name__})
        _update(
            run,
            status="failed",
            stage="done",
            error="History generation failed. Try again; if it keeps failing, check the API log.",
            finished_at=datetime.now(tz=timezone.utc),
        )
    finally:
        try:
            record_job_run(
                db,
                job=JOB_HISTORY,
                scope=f"user:{run.user_id}:{run.base_currency}",
                trigger=TRIGGER_MANUAL,
                status=STATUS_FAILED if error else (STATUS_SUCCESS if run.months_written else STATUS_NO_NEW_DATA),
                started_at=run.started_at,
                user_id=run.user_id,
                data_advanced=bool(run.months_written),
                error=error,
                details={"months": run.months, "months_written": run.months_written, "fx": run.fx},
            )
        finally:
            db.close()
