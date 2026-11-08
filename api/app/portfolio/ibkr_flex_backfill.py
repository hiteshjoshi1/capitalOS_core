"""One-off IBKR Flex back-fill of an earlier period (#313).

The app's IBKR history starts where the daily Flex query started (2025-11-03 on the real data),
so a year before it has no trades and no realised P&L. This asks IBKR for the same Flex query
over an earlier period, using the Flex Web Service date override (``fd``/``td``, at most 365
days per request), and imports each statement through the regular path
(``run_ibkr_flex_import_from_xml``): the raw XML is kept in raw_broker_documents, trades are
replaced by execution id (so a period fetched twice, or one overlapping stored trades, adds
nothing twice), and facts dated outside the IBKR authority window are kept as reference only
(#140), so earlier holdings don't override what other sources say for those dates.

Dry run (default): lists the requests and the accounts; nothing is fetched. ``apply``: one
request per window, paced (IBKR allows 1 per second, 10 per minute). Never prints the token.

If IBKR refuses the override for this query (e.g. ErrorCode 1003), create a separate Activity
Flex Query in the IBKR portal whose period covers the year, and pass its id (QUERY_ID).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio.ibkr_flex import (
    IbkrFlexClient,
    _authorized_flex_user_id,
    run_ibkr_flex_import_from_xml,
)

MAX_WINDOW_DAYS = 365
# IBKR: 1 SendRequest per second, at most 10 per minute.
PACING_SECONDS = 7.0

PORTAL_HINT = (
    "If IBKR refused the date override for this query: in the IBKR portal, Performance & Reports → "
    "Flex Queries → create an Activity Flex Query with the same sections as the daily one (at least "
    "Trades, with FIFO P&L Realized and FX Rate To Base, plus Cash Report, Net Asset Value, Open "
    "Positions), Period = Custom Date Range covering the year, Format = XML. Then run "
    "make ibkr-flex-backfill FROM=... TO=... QUERY_ID=<its id> NO_OVERRIDE=1 (its own period is used)."
)


def plan_windows(start: date, end: date, max_days: int = MAX_WINDOW_DAYS) -> List[tuple[date, date]]:
    """Consecutive windows covering start..end inclusive, each at most ``max_days`` long. Pure."""
    if start > end:
        raise ValueError("FROM is after TO")
    windows: List[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        last = min(cursor + timedelta(days=max_days - 1), end)
        windows.append((cursor, last))
        cursor = last + timedelta(days=1)
    return windows


@dataclass
class WindowResult:
    start: date
    end: date
    status: str = "planned"  # planned | imported | failed
    trades_in_report: int = 0
    trades_added: int = 0
    report_from: Optional[str] = None
    report_to: Optional[str] = None
    error: Optional[str] = None


@dataclass
class BackfillRun:
    user_id: Optional[int] = None
    legacy_account_ids: List[int] = field(default_factory=list)
    query_source: str = ".env"
    override_dates: bool = True
    windows: List[WindowResult] = field(default_factory=list)


def _flex_accounts(db: Session, user_id: int) -> List[int]:
    rows = db.execute(
        text(
            """
            SELECT ba.legacy_account_id
            FROM broker_accounts ba
            JOIN broker_connections bc ON bc.id = ba.connection_id
            WHERE bc.platform_code = 'IBKR'
              AND bc.connection_type = 'flex_api'
              AND bc.status = 'active'
              AND ba.status = 'active'
              AND ba.legacy_account_id IS NOT NULL
              AND bc.user_id = :user_id
            ORDER BY ba.id
            """
        ),
        {"user_id": user_id},
    ).scalars().all()
    return [int(value) for value in rows]


def _trade_count(db: Session, legacy_account_id: int) -> int:
    return int(
        db.execute(
            text(
                """
                SELECT COUNT(*) FROM portfolio_trades t
                JOIN broker_accounts ba ON ba.id = t.broker_account_id
                WHERE ba.legacy_account_id = :account
                """
            ),
            {"account": legacy_account_id},
        ).scalar()
        or 0
    )


def run_backfill(
    db: Session,
    start: date,
    end: date,
    *,
    apply: bool,
    query_id: Optional[str] = None,
    override_dates: bool = True,
    account_id: Optional[int] = None,
    client_factory: Callable[[Optional[str]], Any] = IbkrFlexClient.from_env,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillRun:
    run = BackfillRun(query_source="QUERY_ID override" if query_id else ".env", override_dates=override_dates)
    windows = plan_windows(start, end) if override_dates else [(start, end)]
    run.windows = [WindowResult(a, b) for a, b in windows]
    run.user_id = _authorized_flex_user_id(db)
    accounts = _flex_accounts(db, run.user_id)
    if account_id is not None:
        accounts = [a for a in accounts if a == account_id]
    run.legacy_account_ids = accounts
    if not apply:
        return run
    if len(accounts) != 1:
        raise ValueError(
            f"Expected one active IBKR Flex account, found {len(accounts)}: pass ACCOUNT=<legacy account id>"
        )
    legacy_account_id = accounts[0]
    client = client_factory(query_id)
    for index, window in enumerate(run.windows):
        if index:
            sleep(PACING_SECONDS)
        before = _trade_count(db, legacy_account_id)
        try:
            db.commit()  # no transaction stays open across the IBKR wait
            if override_dates:
                reference_code, xml_text = client.fetch_statement(from_date=window.start, to_date=window.end)
            else:
                reference_code, xml_text = client.fetch_statement()
            result = run_ibkr_flex_import_from_xml(
                db,
                current_user_id=run.user_id,
                legacy_account_id=legacy_account_id,
                xml_text=xml_text,
                reference_code=reference_code,
            )
        except Exception as exc:  # noqa: BLE001 - reported per window; the token is never in it
            db.rollback()
            window.status = "failed"
            window.error = f"{exc.__class__.__name__}: {str(exc)[:200]}"
            continue
        window.status = "imported"
        window.trades_in_report = int((result.get("counts") or {}).get("trades") or 0)
        window.trades_added = _trade_count(db, legacy_account_id) - before
        window.report_from = result.get("report_date_from")
        window.report_to = result.get("report_date_to")
    return run


def summary_lines(run: BackfillRun, *, applied: bool) -> List[str]:
    lines = [
        f"IBKR Flex back-fill for user {run.user_id}, account(s) {', '.join(map(str, run.legacy_account_ids)) or 'none'}; "
        f"query from {run.query_source}; "
        + ("date override (fd/td) per window" if run.override_dates else "the query's own period (no override)")
    ]
    for w in run.windows:
        span = f"{w.start.isoformat()} → {w.end.isoformat()}"
        if not applied:
            lines.append(f"  request {span}")
        elif w.status == "imported":
            lines.append(
                f"  {span}: imported report {w.report_from} → {w.report_to}; "
                f"{w.trades_in_report} trades in it, {w.trades_added} new"
            )
        else:
            lines.append(f"  {span}: FAILED ({w.error})")
    if applied and any(w.status == "failed" for w in run.windows):
        lines.append(PORTAL_HINT)
    if applied:
        lines.append("Done. Then: make realised-pnl-backfill (dry run), and History recomputes the marked months.")
    else:
        lines.append("Dry run: nothing fetched. APPLY=1 to fetch from IBKR.")
    return lines
