"""Source freshness (#252, D-67): one row per data source with its newest data
date, its expected cadence, and whether it is overdue.

Sources (all the caller's own):

- each open **account**: an IBKR account with an active Flex connection
  (``ibkr_flex``), any other broker or fund account (``broker_statement``), a
  bank (``bank_statement``), a card (``card_statement``) or anything else
  (``account_statement``). The data date is the newest fact the canonical read
  layer counts for it (``canonical_latest_fact_dates``, D-56); a card also counts
  its newest statement transaction, since a card statement without a closing
  balance leaves only transactions;
- each active **crypto wallet**: its newest snapshot;
- the **quote feed** of each configured exchange the caller holds something on:
  the newest price date of those holdings;
- the **FX feed** (stored daily rates), when the caller has any other source.

Cadence: each source type has a default (``DEFAULTS``), which a user can
override per source (``source_freshness_overrides``, migration 080). A cadence
gives the date by which data newer than the last one should have arrived
(``due_date``); a source is overdue once today is past it:

- ``daily``: next data the day after; due ``grace`` days after that.
- ``weekdays``: on a weekday the newest data should be the previous weekday's,
  less ``grace`` weekdays (weekends never count; ``grace`` absorbs holidays and
  a feed that reports a day late, like IBKR Flex at 18:30 SGT, D-19).
- ``weekly`` / ``monthly`` / ``quarterly``: one week / one calendar month / three
  months after the last data date (31 Jan + 1 month is 28 or 29 Feb), plus
  ``grace`` days.
- ``off``: never overdue.

A source with no data at all is ``never_loaded`` and counts as overdue (unless
its cadence is ``off``): an account that should have data but has none is the
same gap as an old one.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.core.clock import app_timezone, app_today
from app.market_data.service import configured_exchanges, held_position_rows
from app.models.source_freshness import SourceFreshnessOverride
from app.portfolio.account_open import account_open_sql
from app.portfolio.canonical_reads import canonical_latest_fact_dates
from app.valuation.clock import _date_only, _normalize_ts

CADENCES = ("daily", "weekdays", "weekly", "monthly", "quarterly", "off")
MAX_GRACE_DAYS = 90

KIND_IBKR_FLEX = "ibkr_flex"
KIND_BROKER_STATEMENT = "broker_statement"
KIND_BANK_STATEMENT = "bank_statement"
KIND_CARD_STATEMENT = "card_statement"
KIND_ACCOUNT_STATEMENT = "account_statement"
KIND_CRYPTO_WALLET = "crypto_wallet"
KIND_MARKET_DATA = "market_data"
KIND_FX = "fx"

# (cadence, grace days) per source type. Statements: the next month's statement,
# with ten days for it to be issued and uploaded. Flex: two weekdays (it reports
# the previous US day at 18:30 SGT, so on a Tuesday morning Friday's is the newest,
# plus one for a holiday or a failed run). Quotes and FX: one weekday (a holiday).
# Wallets refresh daily: one day of slack for a run that hasn't happened yet today.
DEFAULTS: dict[str, tuple[str, int]] = {
    KIND_IBKR_FLEX: ("weekdays", 2),
    KIND_BROKER_STATEMENT: ("monthly", 10),
    KIND_BANK_STATEMENT: ("monthly", 10),
    KIND_CARD_STATEMENT: ("monthly", 10),
    KIND_ACCOUNT_STATEMENT: ("monthly", 10),
    KIND_CRYPTO_WALLET: ("daily", 1),
    KIND_MARKET_DATA: ("weekdays", 1),
    KIND_FX: ("weekdays", 1),
}

# Table order: what the user uploads or connects first, then the shared feeds.
_KIND_ORDER = {kind: i for i, kind in enumerate(DEFAULTS)}

STATUS_ON_TIME = "on_time"
STATUS_OVERDUE = "overdue"
STATUS_NEVER_LOADED = "never_loaded"
STATUS_NO_SCHEDULE = "no_schedule"

FX_SOURCE_KEY = "fx"


# ─── Cadence arithmetic (pure) ───────────────────────────────────────────────


def _is_weekday(day: date) -> bool:
    return day.weekday() < 5


def _previous_weekday(day: date) -> date:
    """The newest weekday strictly before ``day``."""
    day -= timedelta(days=1)
    while not _is_weekday(day):
        day -= timedelta(days=1)
    return day


def _weekdays_back(day: date, count: int) -> date:
    for _ in range(count):
        day = _previous_weekday(day)
    return day


def _weekdays_expected(today: date, grace_days: int) -> date:
    """The oldest data date still on time today on a ``weekdays`` cadence."""
    return _weekdays_back(_previous_weekday(today), grace_days)


def add_months(day: date, months: int) -> date:
    """``day`` plus ``months`` calendar months, clamped to the month's last day."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def due_date(last_data: Optional[date], cadence: str, grace_days: int) -> Optional[date]:
    """The last day on which ``last_data`` is still on time (None: never due,
    or no data)."""
    if last_data is None or cadence == "off":
        return None
    if cadence == "daily":
        return last_data + timedelta(days=1 + grace_days)
    if cadence == "weekly":
        return last_data + timedelta(days=7 + grace_days)
    if cadence == "monthly":
        return add_months(last_data, 1) + timedelta(days=grace_days)
    if cadence == "quarterly":
        return add_months(last_data, 3) + timedelta(days=grace_days)
    if cadence == "weekdays":
        # The expected date only moves forward, so walk days until it passes the data.
        day = last_data
        while _weekdays_expected(day + timedelta(days=1), grace_days) <= last_data:
            day += timedelta(days=1)
        return day
    raise ValueError(f"unknown cadence {cadence!r}")


def evaluate(last_data: Optional[date], cadence: str, grace_days: int, today: date) -> dict[str, Any]:
    """Status, due date, overdue flag and days overdue of one source today."""
    if cadence == "off":
        return {"status": STATUS_NO_SCHEDULE, "due_date": None, "overdue": False, "days_overdue": None}
    if last_data is None:
        return {"status": STATUS_NEVER_LOADED, "due_date": None, "overdue": True, "days_overdue": None}
    due = due_date(last_data, cadence, grace_days)
    assert due is not None
    if today > due:
        return {"status": STATUS_OVERDUE, "due_date": due, "overdue": True, "days_overdue": (today - due).days}
    return {"status": STATUS_ON_TIME, "due_date": due, "overdue": False, "days_overdue": None}


# ─── The caller's sources ────────────────────────────────────────────────────


@dataclass
class Source:
    source_key: str
    kind: str
    label: str
    platform: Optional[str]
    last_data_date: Optional[date]


def _account_kind(account_type: str, is_flex: bool) -> str:
    if is_flex:
        return KIND_IBKR_FLEX
    if account_type in ("BROKER", "MUTUAL_FUND"):
        return KIND_BROKER_STATEMENT
    if account_type == "BANK":
        return KIND_BANK_STATEMENT
    if account_type == "CREDIT_CARD":
        return KIND_CARD_STATEMENT
    return KIND_ACCOUNT_STATEMENT


def _newer(a: Optional[date], b: Optional[date]) -> Optional[date]:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _account_sources(db: Session, user_id: int, today: date) -> list[Source]:
    params = {"current_user_id": user_id, "anchor_date": today}
    accounts = db.execute(
        text(
            "SELECT acc.id, acc.name, acc.platform, acc.account_type FROM accounts acc WHERE "
            + account_scope_sql("acc")
            + " AND "
            + account_open_sql("acc")
            + " ORDER BY acc.id"
        ),
        params,
    ).mappings().all()
    if not accounts:
        return []
    flex_ids = {
        int(row[0])
        for row in db.execute(
            text(
                """
                SELECT DISTINCT ba.legacy_account_id
                FROM broker_accounts ba
                JOIN broker_connections bc ON bc.id = ba.connection_id
                JOIN accounts acc ON acc.id = ba.legacy_account_id
                WHERE bc.platform_code = 'IBKR'
                  AND bc.connection_type = 'flex_api'
                  AND bc.status = 'active'
                  AND ba.status = 'active'
                  AND """
                + account_scope_sql("acc")
            ),
            params,
        ).fetchall()
    }
    fact_dates = {
        int(row["account_id"]): _date_only(row["as_of_date"])
        for row in canonical_latest_fact_dates(db, current_user_id=user_id, anchor_date=today)
    }
    # A card's newest statement transaction, as a date in the user's timezone.
    card_txn: dict[int, Optional[date]] = {}
    for account_id, newest in db.execute(
        text(
            "SELECT t.account_id, MAX(t.ts) FROM transactions t JOIN accounts acc ON acc.id = t.account_id "
            "WHERE acc.account_type = 'CREDIT_CARD' AND "
            + account_scope_sql("acc")
            + " GROUP BY t.account_id"
        ),
        params,
    ).fetchall():
        ts = _normalize_ts(newest)
        if ts is not None:
            day = ts.astimezone(app_timezone()).date()
            card_txn[int(account_id)] = day if day <= today else today
    out = []
    for row in accounts:
        account_id = int(row["id"])
        out.append(
            Source(
                source_key=f"account:{account_id}",
                kind=_account_kind(str(row["account_type"]), account_id in flex_ids),
                label=str(row["name"]),
                platform=row["platform"] or None,
                last_data_date=_newer(fact_dates.get(account_id), card_txn.get(account_id)),
            )
        )
    return out


def _wallet_sources(db: Session, user_id: int, today: date) -> list[Source]:
    rows = db.execute(
        text(
            """
            SELECT w.id, w.label, w.chain, MAX(s.as_of_date) AS as_of_date
            FROM crypto_wallets w
            LEFT JOIN crypto_wallet_snapshots s ON s.wallet_id = w.id AND s.as_of_date <= :today
            WHERE w.status = 'active' AND """
            + account_scope_sql("w")
            + """
            GROUP BY w.id, w.label, w.chain
            ORDER BY w.id
            """
        ),
        {"current_user_id": user_id, "today": today},
    ).mappings().all()
    return [
        Source(
            source_key=f"wallet:{row['id']}",
            kind=KIND_CRYPTO_WALLET,
            label=str(row["label"] or row["chain"]),
            platform=str(row["chain"]) if row["chain"] else None,
            last_data_date=_date_only(row["as_of_date"]),
        )
        for row in rows
    ]


def _market_data_sources(db: Session, user_id: int, today: date) -> list[Source]:
    """One quote feed per configured exchange the user holds a stock or fund on
    today: the newest price date among those holdings."""
    asset_ids = sorted(
        {int(row["asset_id"]) for row in held_position_rows(db, today=today, user_id=user_id) if row["asset_id"] is not None}
    )
    exchanges = configured_exchanges()
    if not asset_ids or not exchanges:
        return []
    statement = text(
        """
        SELECT m.exchange_code, MAX(p.trade_date) AS trade_date
        FROM market_symbol_map m
        LEFT JOIN prices p ON p.asset_id = m.asset_id AND p.trade_date IS NOT NULL AND p.trade_date <= :today
        WHERE m.is_active = TRUE
          AND m.asset_id IN :asset_ids
          AND m.exchange_code IN :exchanges
        GROUP BY m.exchange_code
        """
    ).bindparams(bindparam("asset_ids", expanding=True), bindparam("exchanges", expanding=True))
    rows = db.execute(statement, {"today": today, "asset_ids": asset_ids, "exchanges": exchanges}).mappings().all()
    by_exchange = {str(row["exchange_code"]): _date_only(row["trade_date"]) for row in rows}
    return [
        Source(
            source_key=f"exchange:{code}",
            kind=KIND_MARKET_DATA,
            label=f"{code} quotes",
            platform=code,
            last_data_date=by_exchange[code],
        )
        for code in exchanges
        if code in by_exchange
    ]


def _fx_source(db: Session, today: date) -> Source:
    newest = db.execute(
        text("SELECT MAX(rate_date) FROM fx_rates WHERE rate_date <= :today"), {"today": today}
    ).scalar()
    return Source(
        source_key=FX_SOURCE_KEY,
        kind=KIND_FX,
        label="FX rates",
        platform=None,
        last_data_date=_date_only(newest),
    )


def user_sources(db: Session, user_id: int, today: date) -> list[Source]:
    sources = _account_sources(db, user_id, today) + _wallet_sources(db, user_id, today)
    sources += _market_data_sources(db, user_id, today)
    if sources:
        # Rates are shared data: a user with nothing to convert has no FX source.
        sources.append(_fx_source(db, today))
    return sources


def _overrides(db: Session, user_id: int) -> dict[str, SourceFreshnessOverride]:
    rows = db.query(SourceFreshnessOverride).filter(SourceFreshnessOverride.user_id == user_id).all()
    return {row.source_key: row for row in rows}


def _row(source: Source, override: Optional[SourceFreshnessOverride], today: date) -> dict[str, Any]:
    default_cadence, default_grace = DEFAULTS[source.kind]
    cadence = override.cadence if override is not None else default_cadence
    grace = int(override.grace_days) if override is not None else default_grace
    result = evaluate(source.last_data_date, cadence, grace, today)
    return {
        "source_key": source.source_key,
        "kind": source.kind,
        "label": source.label,
        "platform": source.platform,
        "last_data_date": source.last_data_date.isoformat() if source.last_data_date else None,
        "cadence": cadence,
        "grace_days": grace,
        "default_cadence": default_cadence,
        "default_grace_days": default_grace,
        "overridden": override is not None,
        "due_date": result["due_date"].isoformat() if result["due_date"] else None,
        "status": result["status"],
        "overdue": result["overdue"],
        "days_overdue": result["days_overdue"],
    }


def source_freshness(db: Session, user_id: int, today: Optional[date] = None) -> dict[str, Any]:
    """The table: every source of the user, overdue first, then by type and label."""
    today = today or app_today()
    overrides = _overrides(db, user_id)
    rows = [_row(source, overrides.get(source.source_key), today) for source in user_sources(db, user_id, today)]
    rows.sort(key=lambda r: (not r["overdue"], _KIND_ORDER[r["kind"]], r["label"].lower(), r["source_key"]))
    return {
        "as_of": today.isoformat(),
        "overdue_count": sum(1 for r in rows if r["overdue"]),
        "cadences": list(CADENCES),
        "sources": rows,
    }


class UnknownSource(LookupError):
    """The key isn't one of the user's sources."""


def _source(db: Session, user_id: int, source_key: str, today: date) -> Source:
    for source in user_sources(db, user_id, today):
        if source.source_key == source_key:
            return source
    raise UnknownSource(source_key)


def set_override(
    db: Session, user_id: int, source_key: str, cadence: str, grace_days: int, today: Optional[date] = None
) -> dict[str, Any]:
    """Store the user's cadence for one of their sources; returns its row."""
    if cadence not in CADENCES:
        raise ValueError(f"cadence must be one of {', '.join(CADENCES)}")
    if not 0 <= grace_days <= MAX_GRACE_DAYS:
        raise ValueError(f"grace_days must be between 0 and {MAX_GRACE_DAYS}")
    today = today or app_today()
    source = _source(db, user_id, source_key, today)
    override = db.get(SourceFreshnessOverride, (user_id, source_key))
    if override is None:
        override = SourceFreshnessOverride(user_id=user_id, source_key=source_key)
        db.add(override)
    override.cadence = cadence
    override.grace_days = grace_days
    override.updated_at = datetime.now(tz=timezone.utc)
    db.commit()
    return _row(source, override, today)


def clear_override(db: Session, user_id: int, source_key: str, today: Optional[date] = None) -> dict[str, Any]:
    """Back to the source type's default; returns its row."""
    today = today or app_today()
    source = _source(db, user_id, source_key, today)
    override = db.get(SourceFreshnessOverride, (user_id, source_key))
    if override is not None:
        db.delete(override)
        db.commit()
    return _row(source, None, today)
