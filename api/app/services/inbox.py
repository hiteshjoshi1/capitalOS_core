"""The Data Hub inbox (#316): everything that needs the user, each with one action.

One list, built from the checks the Data Hub already runs, so the Inbox page, the
header bell (#317) and the Alerts page can't disagree:
- sources overdue or never loaded (source freshness, #252), action per kind;
- uploads in an unknown format (import job NEEDS_MAPPING: no parser matched, #315);
- uploads still in progress (another status that isn't IMPORTED or FAILED);
- held stocks or funds without a quote (#222);
- past exchange rates missing for the data's span, or a currency the provider
  doesn't publish (#290, D-30);
- scheduled jobs failing (job_runs, #156);
- transactions of this or last month without a category (Map transactions);
- card payments due within 5 days or overdue, from the due date a statement printed
  (#352, D-94), until the card's payments since the statement cover it;
- backups: no verified backup in 48 hours, or the last daily run failed (#399, D-111);
- about the money itself (#410, D-114, ``app.services.insight_alerts``): a month that closed
  with stale data, one holding above a share of net worth, an unusual monthly move, a new
  recurring card charge or one above its usual amount.
Items are ordered high, medium, low; within a severity, as listed above.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql
from app.core.clock import app_today
from app.fx_backfill import plan_backfill
from app.schemas.inbox import InboxAction, InboxItem, InboxResponse
from app.services import data_hub
from app.services.backup_status import backup_status
from app.services.insight_alerts import insight_items
from app.services.source_freshness import (
    KIND_ACCOUNT_STATEMENT,
    KIND_BANK_STATEMENT,
    KIND_BROKER_STATEMENT,
    KIND_CARD_STATEMENT,
    KIND_CRYPTO_WALLET,
    KIND_FX,
    KIND_IBKR_FLEX,
    KIND_MARKET_DATA,
    source_freshness,
)

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
KIND_ORDER = {
    kind: i
    for i, kind in enumerate(
        [
            "job_failing",
            "backup_stale",
            "card_overdue",
            "source_overdue",
            "card_due_soon",
            "unknown_format",
            "source_never_loaded",
            "import_pending",
            "unpriced_holding",
            "fx_gap",
            "fx_unsupported",
            "unmapped_transactions",
            "month_closed_stale",
            "concentration",
            "unusual_move",
            "recurring_up",
            "recurring_new",
        ]
    )
}
UPLOAD_KINDS = {KIND_BROKER_STATEMENT, KIND_BANK_STATEMENT, KIND_CARD_STATEMENT, KIND_ACCOUNT_STATEMENT}
# A source this many days past its due date is high; less is medium (#252's grace already passed).
OVERDUE_HIGH_DAYS = 7

UNPRICED_REASONS = {
    "no_asset": "not linked to an asset",
    "no_symbol": "no ticker on a configured exchange",
    "no_quote": "no quote from any provider",
}
JOB_ACTIONS = {
    "ibkr_flex": ("Refresh IBKR", "refresh_ibkr", False),
    "market_data": ("Refresh prices", "refresh_prices", True),
    "crypto_refresh": ("Refresh wallets", "refresh_crypto", False),
    "fx_fill": ("Open market data", None, False),
    "fx_backfill": ("Fetch past rates", "fx_backfill", True),
}


def _plural(n: int, word: str, plural: Optional[str] = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _source_action(row: dict[str, Any]) -> InboxAction:
    kind = row["kind"]
    if kind in UPLOAD_KINDS:
        # The page builds the prefilled Upload link from `source` (#278); this is the fallback.
        account_id = str(row["source_key"]).split(":", 1)[-1]
        return InboxAction(label="Upload", route="/ingest", params={"account_id": account_id})
    if kind == KIND_IBKR_FLEX:
        account_id = str(row["source_key"]).split(":", 1)[-1]
        return InboxAction(label="Refresh IBKR", run="refresh_ibkr", params={"account_id": account_id})
    if kind == KIND_CRYPTO_WALLET:
        return InboxAction(label="Refresh wallets", run="refresh_crypto")
    if kind == KIND_MARKET_DATA:
        return InboxAction(label="Refresh prices", run="refresh_prices", admin_only=True)
    if kind == KIND_FX:
        return InboxAction(label="Open market data", route="/market-data")
    return InboxAction(label="Open", route="/operations")


def _source_items(rows: list[dict[str, Any]]) -> tuple[list[InboxItem], int]:
    items: list[InboxItem] = []
    on_time = 0
    for row in rows:
        status = row.get("status")
        if status == "never_loaded":
            items.append(InboxItem(
                id=f"source:{row['source_key']}",
                kind="source_never_loaded",
                severity="medium",
                title=f"{row['label']}: no data yet",
                detail="Nothing has been loaded for this source.",
                action=_source_action(row),
                source=row,
            ))
        elif row.get("overdue"):
            days = row.get("days_overdue")
            items.append(InboxItem(
                id=f"source:{row['source_key']}",
                kind="source_overdue",
                severity="high" if (days or 0) >= OVERDUE_HIGH_DAYS else "medium",
                title=f"{row['label']}: {_plural(int(days), 'day')} overdue" if days else f"{row['label']}: overdue",
                detail=f"Last data {row['last_data_date']}" if row.get("last_data_date") else None,
                action=_source_action(row),
                source=row,
            ))
        elif status == "on_time":
            on_time += 1
    return items, on_time


def _import_items(db: Session, user: CurrentUser) -> list[InboxItem]:
    rows = db.execute(
        text(
            """
            SELECT ij.id, ij.status, ij.original_filename, a.name AS account_name
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE ij.status NOT IN ('IMPORTED', 'FAILED')
              AND ij.removed_at IS NULL
              AND """
            + account_scope_sql("a")
            + " ORDER BY ij.created_at DESC, ij.id DESC"
        ),
        {"current_user_id": user.id},
    ).mappings().all()
    items: list[InboxItem] = []
    for row in rows:
        name = row["original_filename"] or f"upload {row['id']}"
        if row["status"] == "NEEDS_MAPPING":
            # No parser matched the file (#315): open that upload and register its format.
            items.append(InboxItem(
                id=f"import:{row['id']}",
                kind="unknown_format",
                severity="medium",
                title=f"{row['account_name']}: file format not recognised",
                detail=name,
                action=InboxAction(label="Fix format", route="/ingest", params={"job": str(row["id"])}),
            ))
        else:
            items.append(InboxItem(
                id=f"import:{row['id']}",
                kind="import_pending",
                severity="low",
                title=f"{row['account_name']}: upload not finished",
                detail=f"{name} ({str(row['status']).lower().replace('_', ' ')})",
                action=InboxAction(label="Open upload", route="/ingest", params={"job": str(row["id"])}),
            ))
    return items


def _unpriced_items(summary: Any) -> list[InboxItem]:
    items: list[InboxItem] = []
    for holding in summary.market_data.unpriced_holdings or []:
        label = holding.symbol or holding.name or "A holding"
        where = ", ".join(x for x in [holding.platform, holding.exchange_code or holding.currency] if x)
        items.append(InboxItem(
            id=f"unpriced:{holding.platform or ''}:{label}",
            kind="unpriced_holding",
            severity="medium",
            title=f"{label}: no live price",
            detail="; ".join(x for x in [where, UNPRICED_REASONS.get(holding.reason, holding.reason)] if x),
            # #320: straight to the Market data page's "Needs a fix" list (set its ticker there).
            action=InboxAction(label="Fix ticker", route="/market-data#needs-fix"),
        ))
    return items


def _fx_items(db: Session, user: CurrentUser, base: str) -> tuple[list[InboxItem], bool]:
    plan = plan_backfill(db, user.id, base)
    items: list[InboxItem] = []
    if plan.uncovered_days > 0:
        items.append(InboxItem(
            id="fx:gap",
            kind="fx_gap",
            severity="medium",
            title=f"Past exchange rates missing for {_plural(plan.uncovered_days, 'day')}",
            detail="Past months leave out foreign holdings on those days.",
            action=InboxAction(label="Fetch past rates", run="fx_backfill", admin_only=True),
        ))
    if plan.unsupported:
        items.append(InboxItem(
            id="fx:unsupported",
            kind="fx_unsupported",
            severity="low",
            title=f"No exchange-rate source for {', '.join(plan.unsupported)}",
            detail="Holdings in these currencies are left out of totals (never counted at 1.0).",
        ))
    return items, plan.span_start is not None and not items


def _job_items(summary: Any) -> tuple[list[InboxItem], int]:
    items: list[InboxItem] = []
    healthy = 0
    for job in summary.job_status:
        if job.state == "failing":
            label, run, admin_only = JOB_ACTIONS.get(job.job, ("Open", None, False))
            detail = f"{_plural(job.consecutive_failures, 'failed run')} in a row"
            if job.last_error:
                detail += f": {job.last_error}"
            items.append(InboxItem(
                id=f"job:{job.job}",
                kind="job_failing",
                severity="high",
                title=f"{job.label} is failing",
                detail=detail,
                action=InboxAction(label=label, run=run, route=None if run else "/market-data", admin_only=admin_only),
            ))
        elif job.state == "ok":
            healthy += 1
    return items, healthy


def _unmapped_items(db: Session, user: CurrentUser, today: date) -> list[InboxItem]:
    first_this = today.replace(day=1)
    first_last = (first_this - timedelta(days=1)).replace(day=1)
    count = db.execute(
        text(
            """
            SELECT count(*)
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN category_overrides co ON co.transaction_id = t.id
            WHERE t.ts >= :start
              AND co.id IS NULL
              AND (t.category IS NULL OR TRIM(t.category) = ''
                   OR LOWER(TRIM(t.category)) IN ('uncategorized', 'creditcard::purchase'))
              AND """
            + account_scope_sql("a")
        ),
        {"start": first_last, "current_user_id": user.id},
    ).scalar()
    n = int(count or 0)
    if n == 0:
        return []
    return [InboxItem(
        id="unmapped",
        kind="unmapped_transactions",
        severity="low",
        title=f"{_plural(n, 'transaction')} without a category",
        detail="This month and last: Cash Flow can't sort them.",
        action=InboxAction(label="Map transactions", route="/cash-flow/map-transactions"),
    )]


def _money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def _card_due_items(db: Session, user: CurrentUser, today: date) -> tuple[list[InboxItem], bool]:
    """Card payments due soon or overdue (#352): (items, every known due is paid)."""
    from app.valuation.card_dues import card_due_states

    states = card_due_states(db, user.id, today=today)
    if not states:
        return [], False
    names = {
        int(row["id"]): (str(row["name"]), str(row["currency"] or "SGD").upper())
        for row in db.execute(
            text("SELECT a.id, a.name, a.currency FROM accounts a WHERE a.account_type = 'CREDIT_CARD' AND "
                 + account_scope_sql("a")),
            {"current_user_id": user.id},
        ).mappings()
    }
    items: list[InboxItem] = []
    for account_id, state in sorted(states.items()):
        if state.status not in ("overdue", "due_soon") or account_id not in names:
            continue
        name, currency = names[account_id]
        due_label = f"{state.due_date.day} {state.due_date.strftime('%b')}"
        amount = state.remaining if state.remaining is not None else None
        what = f"{_money(amount, currency)} " if amount is not None else "payment "
        if state.status == "overdue":
            title = f"{name}: {what}overdue since {due_label}"
        elif state.days_until == 0:
            title = f"{name}: {what}due today"
        else:
            title = f"{name}: {what}due {due_label} ({_plural(state.days_until, 'day')})"
        detail_parts = [f"Statement of {state.statement_date.isoformat()}"]
        if state.paid > 0.005:
            detail_parts.append(f"{_money(state.paid, currency)} paid since")
        if state.minimum_paid:
            detail_parts.append("minimum paid: interest still runs on the rest")
        elif state.minimum_due is not None:
            detail_parts.append(f"minimum {_money(state.minimum_due, currency)}")
        items.append(InboxItem(
            id=f"card_due:{account_id}:{state.statement_date.isoformat()}",
            kind="card_overdue" if state.status == "overdue" else "card_due_soon",
            severity="high" if state.status == "overdue" else "medium",
            title=title,
            detail="; ".join(detail_parts) + ".",
            action=InboxAction(label="Open card balances", route="/liabilities", params={"card": str(account_id)}),
        ))
    all_paid = all(state.status == "paid" for state in states.values())
    return items, all_paid


def _backup_items() -> tuple[list[InboxItem], Optional[str]]:
    """An item when the backups are stale (#399); else the all-good line, or nothing where no
    backup reports (worktrees, the test instance)."""
    status = backup_status()
    if not status.available:
        return [], None
    if not status.stale:
        hours = status.age_hours or 0
        when = "under an hour" if hours < 1 else _plural(int(hours), "hour")
        return [], f"Backup verified {when} ago"
    if status.last_run_ok is False:
        title, detail = "The last daily backup failed", "The newest good backup is older than the failed run."
    elif status.last_verified_at is None:
        title, detail = "No verified backup yet", None
    else:
        days = int((status.age_hours or 0) // 24)
        title, detail = f"No verified backup for {_plural(days, 'day')}", None
    hint = "On the Mac, run make backup-now (or make backup-status to see why)."
    return [
        InboxItem(
            id="backup_stale",
            kind="backup_stale",
            severity="high" if status.very_stale else "medium",
            title=title,
            detail=f"{detail} {hint}" if detail else hint,
            # Nothing the app can run: the backups run on the Mac (launchd), not in the API.
            action=None,
        )
    ], None


def _saved_base_currency(db: Session, user_id: int) -> str:
    row = db.execute(
        text("SELECT base_currency FROM user_preferences WHERE user_id = :uid"), {"uid": user_id}
    ).fetchone()
    return str(row[0]).upper() if row and row[0] else "SGD"


def _safe(build: Callable[[], Any], fallback: Any) -> Any:
    # One failing check must not hide the others: the inbox is where problems surface.
    try:
        return build()
    except Exception:  # noqa: BLE001
        return fallback


def build_inbox(db: Session, user: CurrentUser, *, today: Optional[date] = None) -> InboxResponse:
    today = today or app_today()
    summary = data_hub.data_hub_summary(db, user)
    freshness = _safe(lambda: source_freshness(db, user.id, today), {"sources": []})
    source_items, on_time = _source_items(freshness["sources"])
    job_items, healthy_jobs = _job_items(summary)
    fx_items, fx_ok = _safe(lambda: _fx_items(db, user, _saved_base_currency(db, user.id)), ([], False))
    card_items, cards_paid = _safe(lambda: _card_due_items(db, user, today), ([], False))
    backup_items, backup_ok = _safe(_backup_items, ([], None))
    items = (
        source_items
        + _safe(lambda: _import_items(db, user), [])
        + _unpriced_items(summary)
        + fx_items
        + job_items
        + _safe(lambda: _unmapped_items(db, user, today), [])
        + card_items
        + backup_items
        + _safe(lambda: insight_items(db, user, _saved_base_currency(db, user.id), _safe), [])
    )
    items.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), KIND_ORDER.get(i.kind, 99), i.title.lower()))

    all_good: list[str] = []
    if on_time:
        all_good.append(f"{_plural(on_time, 'source')} on time")
    fresh = summary.market_data.fresh
    if fresh and not summary.market_data.stale:
        all_good.append(f"All {_plural(fresh, 'quote')} fresh")
    if healthy_jobs:
        all_good.append(f"{_plural(healthy_jobs, 'scheduled job')} healthy")
    if fx_ok:
        all_good.append("Past exchange rates complete")
    if cards_paid:
        all_good.append("Card payments up to date")
    if summary.import_health.pending_count == 0 and summary.import_health.last_import_at:
        all_good.append("No uploads waiting")
    if backup_ok:
        all_good.append(backup_ok)

    return InboxResponse(
        as_of=today.isoformat(),
        count=len(items),
        items=items,
        all_good=all_good,
        recent_activity=list(summary.recent_activity[:5]),
    )
