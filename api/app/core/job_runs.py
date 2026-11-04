"""Job status (#156): one `job_runs` row per finished run of a data job.

Every scheduled or manual run of the IBKR Flex import, the quote refresh, the
crypto wallet refresh and the daily FX fill records a row per scope (an IBKR
account, an exchange, a wallet, or 'all'): when it ran, whether the data is as
current as it should be (`status`), whether it moved forward (`data_advanced`),
how current it is now (`data_as_of`), a scrubbed error summary, and the failure
streak (`attempt`). The Data Hub reads its per-source status from here.

Recording never breaks the job: a failed insert is rolled back and logged.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.catchup import coerce_utc

logger = logging.getLogger("capitalos.job_runs")

JOB_IBKR_FLEX = "ibkr_flex"
JOB_MARKET_DATA = "market_data"
JOB_CRYPTO = "crypto_refresh"
JOB_FX = "fx_fill"

JOB_LABELS = {
    JOB_IBKR_FLEX: "IBKR Flex import",
    JOB_MARKET_DATA: "Quote refresh",
    JOB_CRYPTO: "Crypto wallet refresh",
    JOB_FX: "FX rates",
}

STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_NO_NEW_DATA = "no_new_data"
STATUS_FAILED = "failed"
_STATUSES = {STATUS_SUCCESS, STATUS_PARTIAL, STATUS_NO_NEW_DATA, STATUS_FAILED}
# Runs that left the data current (a partial run advanced what it could).
SUCCESS_STATUSES = (STATUS_SUCCESS, STATUS_PARTIAL)

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_MANUAL = "manual"

# A source turns red after this many consecutive failed runs of one scope. A due
# run that fails is retried every SCHEDULER_RETRY_MINUTES (30 by default, D-19),
# so one failure is usually a provider hiccup or a wake from sleep without
# network, and the retry fixes it. Three in a row is an hour of failing retries:
# the source is broken until someone looks. One or two show amber.
FAILURE_THRESHOLD = 3

ERROR_SUMMARY_MAX = 300

# Scrub order matters: whole URLs first (they can carry keys in the path or the
# query), then key=value secrets, then anything that looks like an address,
# account number or token.
_SCRUBBERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>]+"), "[url]"),
    (
        re.compile(
            r"(?i)\b(token|key|secret|password|passwd|pwd|authorization|bearer|signature|apikey|api_key|access_key)"
            r"\s*[=:]\s*[^\s,;'\"&]+"
        ),
        r"\1=[redacted]",
    ),
    (re.compile(r"\b0x[0-9a-fA-F]{8,}\b"), "[address]"),
    (re.compile(r"\b[A-Za-z]{1,3}\d{5,}\b"), "[account]"),
    (re.compile(r"\b\d{5,}\b"), "[number]"),
    # Long mixed strings with a digit (API keys, session tokens), not class names.
    (re.compile(r"\b(?=[A-Za-z_\-+/=]*\d)[A-Za-z0-9_\-+/=]{20,}"), "[redacted]"),
)


def safe_error_summary(error: BaseException | str | None) -> str | None:
    """A short, storable description of a failure: the error class plus its text
    with URLs, credentials, addresses, account numbers and long tokens removed."""
    if error is None:
        return None
    if isinstance(error, BaseException):
        detail = str(error).strip()
        raw = f"{error.__class__.__name__}: {detail}" if detail else error.__class__.__name__
    else:
        raw = str(error).strip()
    if not raw:
        return None
    for pattern, replacement in _SCRUBBERS:
        raw = pattern.sub(replacement, raw)
    raw = " ".join(raw.split())
    if len(raw) > ERROR_SUMMARY_MAX:
        raw = raw[: ERROR_SUMMARY_MAX - 1] + "…"
    return raw


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (coerce_utc(value) or value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _previous_attempt(db: Session, job: str, scope: str) -> int:
    row = db.execute(
        text(
            """
            SELECT status, attempt
            FROM job_runs
            WHERE job = :job AND scope = :scope
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """
        ),
        {"job": job, "scope": scope},
    ).fetchone()
    if row is None or row[0] != STATUS_FAILED:
        return 0
    return int(row[1] or 1)


def record_job_run(
    db: Session,
    *,
    job: str,
    scope: str = "all",
    trigger: str,
    status: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    user_id: int | None = None,
    data_as_of: Any = None,
    data_advanced: bool = False,
    error: BaseException | str | None = None,
    details: dict[str, Any] | None = None,
) -> int | None:
    """Insert one finished run and commit. Call it after the job's own commit or
    rollback; it never raises (a status row must not fail the job it describes)."""
    if status not in _STATUSES:
        raise ValueError(f"unknown job run status {status!r}")
    finished = finished_at or datetime.now(tz=timezone.utc)
    try:
        attempt = _previous_attempt(db, job, scope) + 1 if status == STATUS_FAILED else 1
        row = db.execute(
            text(
                """
                INSERT INTO job_runs
                  (job, scope, user_id, trigger, status, started_at, finished_at,
                   data_advanced, data_as_of, error_summary, attempt, details)
                VALUES
                  (:job, :scope, :user_id, :trigger, :status, :started_at, :finished_at,
                   :data_advanced, :data_as_of, :error_summary, :attempt, :details)
                RETURNING id
                """
            ),
            {
                "job": job,
                "scope": scope,
                "user_id": user_id,
                "trigger": trigger,
                "status": status,
                "started_at": started_at,
                "finished_at": finished,
                "data_advanced": bool(data_advanced),
                "data_as_of": _iso(data_as_of),
                "error_summary": safe_error_summary(error) if status != STATUS_SUCCESS else None,
                "attempt": attempt,
                "details": json.dumps(details or {}, default=str),
            },
        ).fetchone()
        db.commit()
        return int(row[0]) if row else None
    except Exception as exc:  # noqa: BLE001 - status recording must not fail the job
        db.rollback()
        logger.warning(
            "job_run_not_recorded",
            extra={"event": "job_run_not_recorded", "job": job, "error_class": exc.__class__.__name__},
        )
        return None


def last_data_as_of(db: Session, job: str, scope: str) -> str | None:
    """The newest recorded data-as-of of a (job, scope), for "did it advance?"."""
    row = db.execute(
        text(
            """
            SELECT data_as_of
            FROM job_runs
            WHERE job = :job AND scope = :scope AND data_as_of IS NOT NULL
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """
        ),
        {"job": job, "scope": scope},
    ).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


def job_status(
    db: Session,
    job: str,
    *,
    user_id: int,
    scopes: Iterable[str] | None = None,
    scope_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Status of one job for one user: their own runs plus shared ones (user_id
    NULL), per scope, limited to `scopes` (the scopes that still exist) if given.

    The job's `last_success_at` and `data_as_of` are the *oldest* across scopes:
    a source is only as current as its stalest account / exchange / wallet.
    """
    params: dict[str, Any] = {"job": job, "user_id": user_id}
    scope_filter = ""
    scope_list = sorted(set(scopes)) if scopes is not None else None
    if scope_list is not None:
        if not scope_list:
            # Nothing to run for this user (no IBKR account, no wallet, ...).
            return _empty_status(job, state="not_configured")
        scope_filter = "AND scope IN :scopes"
        params["scopes"] = scope_list

    def _query(sql: str):
        statement = text(sql)
        if scope_list is not None:
            statement = statement.bindparams(bindparam("scopes", expanding=True))
        return db.execute(statement, params).fetchall()

    latest_rows = _query(
        f"""
        SELECT scope, status, finished_at, data_as_of, error_summary, attempt, trigger, data_advanced
        FROM job_runs
        WHERE job = :job AND (user_id = :user_id OR user_id IS NULL) {scope_filter}
        ORDER BY finished_at DESC, id DESC
        LIMIT 500
        """
    )
    success_rows = _query(
        f"""
        SELECT scope, MAX(finished_at) AS last_success_at
        FROM job_runs
        WHERE job = :job AND (user_id = :user_id OR user_id IS NULL)
          AND status IN ('success', 'partial') {scope_filter}
        GROUP BY scope
        """
    )
    last_success = {str(r[0]): coerce_utc(r[1]) for r in success_rows}

    per_scope: dict[str, dict[str, Any]] = {}
    for raw in latest_rows:
        row = _row_dict(raw)
        scope = str(row["scope"])
        entry = per_scope.get(scope)
        if entry is None:
            failed = row["status"] == STATUS_FAILED
            entry = {
                "scope": scope,
                "label": (scope_labels or {}).get(scope),
                "last_run_at": _iso(coerce_utc(row["finished_at"])),
                "last_run_status": row["status"],
                "last_run_trigger": row["trigger"],
                "last_success_at": _iso(last_success.get(scope)),
                "data_as_of": row["data_as_of"],
                "consecutive_failures": int(row["attempt"] or 1) if failed else 0,
                "last_error": row["error_summary"] if failed or row["status"] != STATUS_SUCCESS else None,
            }
            per_scope[scope] = entry
        elif entry["data_as_of"] is None and row["data_as_of"] is not None:
            entry["data_as_of"] = row["data_as_of"]
    for scope, success_at in last_success.items():
        if scope not in per_scope:
            # Older than the window of recent rows: still show when it last worked.
            per_scope[scope] = {
                "scope": scope,
                "label": (scope_labels or {}).get(scope),
                "last_run_at": None,
                "last_run_status": None,
                "last_run_trigger": None,
                "last_success_at": _iso(success_at),
                "data_as_of": None,
                "consecutive_failures": 0,
                "last_error": None,
            }

    if not per_scope:
        return _empty_status(job)

    entries = sorted(per_scope.values(), key=lambda e: (e["label"] or e["scope"]).lower())
    max_failures = max(e["consecutive_failures"] for e in entries)
    if max_failures >= FAILURE_THRESHOLD:
        state = "failing"
    elif max_failures > 0 or any(e["last_run_status"] == STATUS_NO_NEW_DATA for e in entries):
        state = "warning"
    else:
        state = "ok"
    run_times = [e["last_run_at"] for e in entries if e["last_run_at"]]
    successes = [e["last_success_at"] for e in entries]
    as_ofs = [e["data_as_of"] for e in entries]
    failing_entry = next((e for e in entries if e["consecutive_failures"] == max_failures and max_failures), None)
    latest_entry = max(entries, key=lambda e: e["last_run_at"] or "")
    return {
        "job": job,
        "label": JOB_LABELS.get(job, job),
        "state": state,
        "failure_threshold": FAILURE_THRESHOLD,
        "last_run_at": max(run_times) if run_times else None,
        "last_run_status": latest_entry["last_run_status"],
        "last_success_at": None if any(s is None for s in successes) else min(successes),
        "data_as_of": None if any(a is None for a in as_ofs) else min(as_ofs),
        "consecutive_failures": max_failures,
        "last_error": failing_entry["last_error"] if failing_entry else None,
        "scopes": entries,
    }


def _empty_status(job: str, *, state: str = "never_run") -> dict[str, Any]:
    return {
        "job": job,
        "label": JOB_LABELS.get(job, job),
        "state": state,
        "failure_threshold": FAILURE_THRESHOLD,
        "last_run_at": None,
        "last_run_status": None,
        "last_success_at": None,
        "data_as_of": None,
        "consecutive_failures": 0,
        "last_error": None,
        "scopes": [],
    }
