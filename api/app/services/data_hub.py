"""The Data Hub card (/dashboard/data-hub-summary): linked accounts, imports,
market data, wallets and recent activity, plus per-source job status (#156)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, allow_legacy_null_ownership
from app.core.job_runs import JOB_CRYPTO, JOB_FX, JOB_FX_BACKFILL, JOB_IBKR_FLEX, JOB_MARKET_DATA, job_status
from app.market_data.service import (
    EMPTY_EXCHANGE_PROVIDER,
    configured_exchanges,
    freshness_counts_by_exchange,
    held_asset_ids,
    unpriced_held_positions,
)
from app.schemas.dashboard import (
    DataHubActivityItem,
    DataHubImportHealth,
    DataHubJobStatus,
    DataHubMarketData,
    DataHubSummaryResponse,
    DataHubUnpricedHolding,
)


def _wallet_scope_sql_for_summary(alias: str = "w") -> str:
    if allow_legacy_null_ownership():
        return f"({alias}.user_id = :current_user_id OR {alias}.user_id IS NULL)"
    return f"{alias}.user_id = :current_user_id"


def _data_hub_job_status(db: Session, current_user: CurrentUser) -> list[DataHubJobStatus]:
    """Per source: last success, data as of, failure streak (#156), limited to
    the scopes that still exist for this user (a deleted wallet's old failures
    don't keep the source red)."""
    params = {"current_user_id": current_user.id}
    ibkr_rows = db.execute(
        text(
            """
            SELECT DISTINCT ba.legacy_account_id, a.name
            FROM broker_accounts ba
            JOIN broker_connections bc ON bc.id = ba.connection_id
            JOIN accounts a ON a.id = ba.legacy_account_id
            WHERE bc.platform_code = 'IBKR'
              AND bc.connection_type = 'flex_api'
              AND bc.status = 'active'
              AND ba.status = 'active'
              AND bc.user_id = :current_user_id
            """
        ),
        params,
    ).fetchall()
    ibkr_labels = {f"account:{row[0]}": str(row[1] or f"Account {row[0]}") for row in ibkr_rows}
    wallet_rows = db.execute(
        text(
            "SELECT id, label, chain FROM crypto_wallets w WHERE w.status = 'active' AND "
            + _wallet_scope_sql_for_summary("w")
        ),
        params,
    ).fetchall()
    wallet_labels = {f"wallet:{row[0]}": str(row[1] or row[2]) for row in wallet_rows}
    exchange_labels = {f"exchange:{code}": code for code in configured_exchanges()}
    plan: list[tuple[str, dict[str, str]]] = [
        (JOB_IBKR_FLEX, ibkr_labels),
        (JOB_MARKET_DATA, exchange_labels),
        (JOB_CRYPTO, wallet_labels),
        (JOB_FX, {"all": "Daily fill"}),
    ]
    # The FX back-fill (#290) shows once it has run: a card that never ran would only
    # say "never run" for something that runs by itself after an import.
    if db.execute(text("SELECT 1 FROM job_runs WHERE job = :job LIMIT 1"), {"job": JOB_FX_BACKFILL}).first():
        plan.append((JOB_FX_BACKFILL, {"all": "Past rates"}))
    return [
        DataHubJobStatus(**job_status(db, job, user_id=current_user.id, scopes=labels.keys(), scope_labels=labels))
        for job, labels in plan
    ]


def _relative_time_label(occurred_at: datetime) -> str:
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - occurred_at
    seconds = max(0, delta.total_seconds())
    if seconds < 3600:
        minutes = max(1, int(seconds // 60))
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


def data_hub_summary(db: Session, current_user: CurrentUser) -> DataHubSummaryResponse:
    account_rows = db.execute(
        text(
            """
            SELECT a.platform_id, a.currency
            FROM accounts a
            WHERE """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    linked_accounts = len(account_rows)
    platform_count = len({row[0] for row in account_rows if row[0] is not None})
    currency_count = len({row[1] for row in account_rows if row[1] is not None})

    pending_count_row = db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE ij.status NOT IN ('IMPORTED', 'FAILED')
              AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user.id},
    ).fetchone()
    pending_count = int(pending_count_row[0]) if pending_count_row else 0

    last_import_row = db.execute(
        text(
            """
            SELECT ij.platform, ij.created_at
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE """
            + account_scope_sql("a")
            + """
            ORDER BY ij.created_at DESC
            LIMIT 1
            """
        ),
        {"current_user_id": current_user.id},
    ).fetchone()

    # The caller's own symbols only, admin or not: this card is about your data (#153).
    market_freshness = freshness_counts_by_exchange(db, asset_ids=held_asset_ids(db, current_user.id))
    fresh_total = sum(counts["fresh"] for counts in market_freshness.values())
    stale_total = sum(counts["stale"] for counts in market_freshness.values())
    # Held stocks/funds the quote refresh can't price, so they'd sit at their
    # uploaded price unnoticed (#222). The caller's own holdings only.
    unpriced = unpriced_held_positions(db, user_id=current_user.id)

    wallet_rows = db.execute(
        text(
            "SELECT label, chain FROM crypto_wallets w WHERE w.status = 'active' AND "
            + _wallet_scope_sql_for_summary("w")
            + " ORDER BY w.verified_at DESC"
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    connected_wallet_labels = [row[0] or row[1] for row in wallet_rows]

    activity_rows: list[dict[str, Any]] = []
    import_activity = db.execute(
        text(
            """
            SELECT ij.platform, ij.original_filename, ij.created_at
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE """
            + account_scope_sql("a")
            + """
            ORDER BY ij.created_at DESC
            LIMIT 5
            """
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    for platform, filename, created_at in import_activity:
        if created_at is None:
            continue
        activity_rows.append(
            {
                "kind": "import",
                "title": f"Imported {platform} statement",
                "meta": filename or "",
                "occurred_at": created_at,
            }
        )

    market_activity = db.execute(
        text(
            """
            SELECT exchange_code, provider, finished_at, upserted_rows
            FROM market_data_runs
            WHERE finished_at IS NOT NULL
              AND provider <> :empty_provider
            ORDER BY finished_at DESC
            LIMIT 5
            """
        ),
        # A 0-symbol run on an exchange with nothing held refreshed nothing (#137):
        # it stays in /market-data/runs but isn't "Refreshed ... market data" activity.
        {"empty_provider": EMPTY_EXCHANGE_PROVIDER},
    ).fetchall()
    for exchange_code, provider, finished_at, upserted_rows in market_activity:
        if finished_at is None:
            continue
        activity_rows.append(
            {
                "kind": "market_data",
                "title": f"Refreshed {exchange_code} market data",
                "meta": f"{upserted_rows or 0} quotes upserted · {provider}",
                "occurred_at": finished_at,
            }
        )

    platform_activity = db.execute(
        text(
            """
            SELECT name, platform_type, country, created_at
            FROM platforms
            WHERE created_at IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 5
            """
        )
    ).fetchall()
    for name, platform_type, country, created_at in platform_activity:
        if created_at is None:
            continue
        activity_rows.append(
            {
                "kind": "platform",
                "title": f"Added platform {name}",
                "meta": f"{platform_type.replace('_', ' ').title()} · {country}",
                "occurred_at": created_at,
            }
        )

    wallet_activity = db.execute(
        text(
            "SELECT label, chain, verified_at FROM crypto_wallets w WHERE w.status = 'active' AND verified_at IS NOT NULL AND "
            + _wallet_scope_sql_for_summary("w")
            + " ORDER BY w.verified_at DESC LIMIT 5"
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    for label, chain, verified_at in wallet_activity:
        if verified_at is None:
            continue
        activity_rows.append(
            {
                "kind": "wallet",
                "title": f"Connected {label or chain} wallet",
                "meta": chain,
                "occurred_at": verified_at,
            }
        )

    def _as_dt(value: Any) -> datetime:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    activity_rows.sort(key=lambda row: _as_dt(row["occurred_at"]), reverse=True)

    return DataHubSummaryResponse(
        linked_accounts=linked_accounts,
        platform_count=platform_count,
        currency_count=currency_count,
        import_health=DataHubImportHealth(
            pending_count=pending_count,
            last_import_platform=last_import_row[0] if last_import_row else None,
            last_import_at=_as_dt(last_import_row[1]).isoformat() if last_import_row and last_import_row[1] else None,
        ),
        market_data=DataHubMarketData(
            fresh=fresh_total,
            stale=stale_total,
            unpriced=len(unpriced),
            unpriced_holdings=[
                DataHubUnpricedHolding(
                    symbol=item["symbol"],
                    name=item["name"],
                    currency=item["currency"],
                    exchange_code=item["exchange_code"],
                    platform=item["platform"],
                    reason=item["reason"],
                )
                for item in unpriced
            ],
        ),
        connected_wallet_count=len(connected_wallet_labels),
        connected_wallet_labels=connected_wallet_labels,
        recent_activity=[
            DataHubActivityItem(
                kind=row["kind"],
                title=row["title"],
                meta=row["meta"],
                occurred_at=_relative_time_label(_as_dt(row["occurred_at"])),
            )
            for row in activity_rows[:10]
        ],
        job_status=_data_hub_job_status(db, current_user),
    )
