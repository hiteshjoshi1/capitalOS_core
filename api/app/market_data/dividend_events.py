"""Dividend events for the calendar (#417, U17, D-117): fetched with the market-data refresh.

Per active symbol of an exchange, the provider (yfinance) gives its past dividends (ex-date and
amount per share) and the next listed ex-date. They are shared market data, like
market_dividend_yields, written only here (the refresh runs as an admin or the scheduler).

Requests are bounded: a symbol fetched within DIVIDEND_EVENTS_MIN_AGE_HOURS (default 20) is
skipped, and at most DIVIDEND_EVENTS_MAX_SYMBOLS (default 120) are fetched per exchange per run;
each fetch is two provider calls (dividends, calendar).
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _recently_fetched(db: Session, asset_ids: Iterable[int], since: datetime) -> set[int]:
    ids = sorted({int(a) for a in asset_ids})
    if not ids:
        return set()
    placeholders = ",".join(str(a) for a in ids)
    rows = db.execute(
        text(
            f"""
            SELECT asset_id, MAX(fetched_at) AS fetched_at
            FROM market_dividend_events
            WHERE asset_id IN ({placeholders})
            GROUP BY asset_id
            """
        )
    ).mappings().all()
    out: set[int] = set()
    for row in rows:
        fetched = row.get("fetched_at")
        if isinstance(fetched, str):
            try:
                fetched = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
            except ValueError:
                continue
        if isinstance(fetched, datetime):
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            if fetched >= since:
                out.add(int(row["asset_id"]))
    return out


def _upsert_event(
    db: Session,
    *,
    asset_id: int,
    kind: str,
    ex_date: date,
    pay_date: date | None,
    amount_per_share: float | None,
    currency: str,
    exchange_code: str,
    provider_symbol: str,
    fetched_at: datetime,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO market_dividend_events
              (asset_id, kind, ex_date, pay_date, amount_per_share, currency, source, exchange_code, provider_symbol, fetched_at)
            VALUES
              (:asset_id, :kind, :ex_date, :pay_date, :amount_per_share, :currency, 'yfinance', :exchange_code, :provider_symbol, :fetched_at)
            ON CONFLICT (asset_id, kind, ex_date)
            DO UPDATE SET
              pay_date = EXCLUDED.pay_date,
              amount_per_share = EXCLUDED.amount_per_share,
              currency = EXCLUDED.currency,
              exchange_code = EXCLUDED.exchange_code,
              provider_symbol = EXCLUDED.provider_symbol,
              fetched_at = EXCLUDED.fetched_at
            """
        ),
        {
            "asset_id": asset_id,
            "kind": kind,
            "ex_date": ex_date,
            "pay_date": pay_date,
            "amount_per_share": amount_per_share,
            "currency": currency,
            "exchange_code": exchange_code,
            "provider_symbol": provider_symbol,
            "fetched_at": fetched_at,
        },
    )


def refresh_dividend_events_for_exchange(
    db: Session,
    *,
    exchange_code: str,
    symbols: list[Any],
    yfinance: Any,
    now: datetime | None = None,
) -> int:
    """Fetch and store dividend events for an exchange's active symbols (SymbolMapRow-like:
    asset_id, yahoo_symbol, quote_currency). Returns the number of event rows written. Never
    raises: a provider failure leaves the stored events as they were."""
    now = now or datetime.now(tz=timezone.utc)
    by_symbol: dict[str, list[Any]] = {}
    for row in symbols:
        provider_symbol = (getattr(row, "yahoo_symbol", "") or "").strip().upper()
        if provider_symbol:
            by_symbol.setdefault(provider_symbol, []).append(row)
    if not by_symbol:
        return 0

    fresh = _recently_fetched(
        db,
        (r.asset_id for rows in by_symbol.values() for r in rows),
        now - timedelta(hours=_env_int("DIVIDEND_EVENTS_MIN_AGE_HOURS", 20)),
    )
    due = [s for s, rows in by_symbol.items() if not all(int(r.asset_id) in fresh for r in rows)]
    due = due[: _env_int("DIVIDEND_EVENTS_MAX_SYMBOLS", 120)]
    if not due:
        return 0
    try:
        fetched = yfinance.fetch_dividend_events(due, exchange_code=exchange_code)
    except Exception:  # noqa: BLE001
        return 0

    today = now.date()
    written = 0
    for provider_symbol in due:
        payload = fetched.get(provider_symbol.upper())
        if not payload:
            continue
        history = payload.get("history") or []
        announced = payload.get("announced")
        for row in by_symbol[provider_symbol]:
            currency = (getattr(row, "quote_currency", None) or "USD").upper()
            asset_id = int(row.asset_id)
            for ex_date, amount in history:
                if amount is None or not math.isfinite(float(amount)) or float(amount) <= 0:
                    continue
                _upsert_event(
                    db,
                    asset_id=asset_id,
                    kind="history",
                    ex_date=ex_date,
                    pay_date=None,
                    amount_per_share=float(amount),
                    currency=currency,
                    exchange_code=exchange_code,
                    provider_symbol=provider_symbol,
                    fetched_at=now,
                )
                written += 1
            # A listed date can move: drop the asset's still-ahead listing before storing the new one.
            db.execute(
                text(
                    "DELETE FROM market_dividend_events "
                    "WHERE asset_id = :asset_id AND kind = 'announced' AND ex_date >= :today"
                ),
                {"asset_id": asset_id, "today": today},
            )
            if announced and announced.get("ex_date"):
                _upsert_event(
                    db,
                    asset_id=asset_id,
                    kind="announced",
                    ex_date=announced["ex_date"],
                    pay_date=announced.get("pay_date"),
                    amount_per_share=None,
                    currency=currency,
                    exchange_code=exchange_code,
                    provider_symbol=provider_symbol,
                    fetched_at=now,
                )
                written += 1
            elif not history:
                # Nothing to store, but remember the fetch so the next run skips it for a while.
                _upsert_event(
                    db,
                    asset_id=asset_id,
                    kind="history",
                    ex_date=date(1970, 1, 1),
                    pay_date=None,
                    amount_per_share=None,
                    currency=currency,
                    exchange_code=exchange_code,
                    provider_symbol=provider_symbol,
                    fetched_at=now,
                )
    return written
