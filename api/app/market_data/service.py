from __future__ import annotations

import os
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.core.clock import app_today
from app.market_data.providers import (
    YAHOO_QUALIFIED_SUFFIXES,
    EODHDProvider,
    EodQuote,
    FinnhubProvider,
    YahooProvider,
    YFinanceProvider,
)
from app.portfolio.effective_facts import BROKER_ACCOUNT_OWNER, POSITIONS, effective_rows_sql


YAHOO_SUFFIX = {
    "US": "",
    "SGX": ".SI",
    "HKEX": ".HK",
    "NSE": ".NS",
}

_EXCHANGE_DEFAULT_CCY = {
    "US": "USD",
    "SGX": "SGD",
    "HKEX": "HKD",
    "NSE": "INR",
}

EODHD_SUFFIX = {
    "US": ".US",
    "SGX": ".SI",
    "HKEX": ".HK",
    "NSE": ".NS",
}


class MarketDataReasonCode(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    NO_TRADE_REPORTED = "NO_TRADE_REPORTED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_PRICE = "INVALID_PRICE"


def _reason_code_for_exception(exc: Exception) -> MarketDataReasonCode:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError) and current.response.status_code == 429:
            return MarketDataReasonCode.RATE_LIMITED
        if type(current).__name__ == "YFRateLimitError":
            return MarketDataReasonCode.RATE_LIMITED
        current = current.__cause__ or current.__context__
    return MarketDataReasonCode.PROVIDER_ERROR


@dataclass
class SymbolMapRow:
    asset_id: int
    exchange_code: str
    exchange_symbol: str
    quote_currency: str
    eodhd_symbol: str
    finnhub_symbol: str
    yahoo_symbol: str
    # The map row carries a Yahoo override (#222): the automatic BSE fallback (#320)
    # never replaces one somebody set.
    has_yahoo_override: bool = False



def configured_exchanges() -> list[str]:
    raw = os.getenv("STOCK_EXCHANGES", "US,SGX,HKEX,NSE")
    return [p.strip().upper() for p in raw.split(",") if p.strip()]



def _daily_limit() -> int:
    return int(os.getenv("STOCK_DAILY_SYMBOL_LIMIT", "20"))


def _refresh_batch_size() -> int:
    raw = os.getenv("STOCK_REFRESH_BATCH_SIZE", "25")
    try:
        size = int(raw)
    except ValueError:
        size = 25
    return max(1, size)


def _quote_stale_days() -> int:
    raw = os.getenv("QUOTE_STALE_DAYS", "3")
    try:
        days = int(raw)
    except ValueError:
        days = 3
    return max(1, days)



def _provider_chain(exchange_code: str) -> list[str]:
    exchange_code = exchange_code.upper()
    if exchange_code == "US":
        raw = os.getenv("STOCK_PROVIDER_CHAIN_US", "finnhub,yahoo")
    else:
        raw = os.getenv("STOCK_PROVIDER_CHAIN_NON_US", "yfinance,yahoo")
    chain = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return [p for p in chain if p in {"finnhub", "eodhd", "yahoo", "yfinance"}]



def _default_eodhd_symbol(exchange_symbol: str, exchange_code: str) -> str:
    return f"{exchange_symbol}{EODHD_SUFFIX.get(exchange_code, f'.{exchange_code}')}"



def _default_finnhub_symbol(exchange_symbol: str) -> str:
    return exchange_symbol



def _default_yahoo_symbol(exchange_symbol: str, exchange_code: str) -> str:
    base = (exchange_symbol or "").strip().upper()
    ex = exchange_code.upper()
    if base.startswith(f"{ex}:"):
        base = base.split(":", 1)[1].strip().upper()
    if base.endswith(".NSE"):
        base = f"{base[:-4]}.NS"
    if base.endswith(".SGX"):
        base = f"{base[:-4]}.SI"
    if ex == "US" and "." in base and not base.endswith(YAHOO_QUALIFIED_SUFFIXES):
        # Yahoo uses dashed class-share tickers for US equities (e.g. BRK-B).
        parts = base.split(".")
        if len(parts) == 2 and parts[0] and parts[1]:
            base = f"{parts[0]}-{parts[1]}"
    suffix = YAHOO_SUFFIX.get(ex, "")
    symbol = base
    if suffix and not symbol.endswith(YAHOO_QUALIFIED_SUFFIXES):
        symbol = f"{symbol}{suffix}"
    if ex == "HKEX" and symbol.endswith(".HK"):
        hk_base = symbol[:-3]
        if hk_base.isdigit() and len(hk_base) < 4:
            return f"{hk_base.zfill(4)}.HK"
    return symbol



def _resolved_exchange_symbol(row: Any) -> tuple[str, str | None]:
    """(exchange code, ticker to quote) for a market_symbol_map row; no ticker
    means the row is skipped."""
    ex = str(row["exchange_code"]).strip().upper()
    mapped_symbol = str(row["exchange_symbol"] or "").strip().upper()
    asset_symbol = str(row.get("asset_symbol") or "").strip().upper()
    # US maps can drift to company-name-like symbols; prefer canonical asset symbol when present.
    asset_candidate = _ticker_candidate(asset_symbol)
    mapped_candidate = _ticker_candidate(mapped_symbol)
    sym = asset_candidate if ex == "US" and asset_candidate else mapped_candidate
    return ex, sym


def _load_symbols(db: Session, exchange_code: str, *, daily_limit: int) -> list[SymbolMapRow]:
    limit_clause = ""
    params: dict[str, Any] = {"exchange_code": exchange_code}
    if daily_limit > 0:
        limit_clause = "LIMIT :daily_limit"
        params["daily_limit"] = daily_limit

    rows = db.execute(
        text(
            f"""
            SELECT m.asset_id,
                   m.exchange_code,
                   m.exchange_symbol,
                   a.symbol AS asset_symbol,
                   m.quote_currency,
                   m.eodhd_symbol_override,
                   m.yahoo_symbol_override,
                   lp.latest_trade_date
            FROM market_symbol_map m
            JOIN assets a ON a.id = m.asset_id
            LEFT JOIN (
              SELECT asset_id, MAX(trade_date) AS latest_trade_date
              FROM prices
              WHERE trade_date IS NOT NULL
              GROUP BY asset_id
            ) lp ON lp.asset_id = m.asset_id
            WHERE m.exchange_code = :exchange_code
              AND m.is_active = TRUE
              AND a.asset_class IN ('STOCK', 'FUND')
            ORDER BY
              CASE WHEN lp.latest_trade_date IS NULL THEN 0 ELSE 1 END,
              lp.latest_trade_date ASC,
              m.asset_id ASC
            {limit_clause}
            """
        ),
        params,
    ).mappings().all()

    out: list[SymbolMapRow] = []
    for row in rows:
        ex, sym = _resolved_exchange_symbol(row)
        if not sym:
            continue
        eod_symbol = (row.get("eodhd_symbol_override") or _default_eodhd_symbol(sym, ex)).strip().upper()
        yahoo_symbol = _default_yahoo_symbol(
            str(row.get("yahoo_symbol_override") or sym).strip().upper(),
            ex,
        )
        out.append(
            SymbolMapRow(
                asset_id=int(row["asset_id"]),
                exchange_code=ex,
                exchange_symbol=sym,
                quote_currency=str(row["quote_currency"]).upper(),
                eodhd_symbol=eod_symbol,
                finnhub_symbol=_default_finnhub_symbol(sym),
                yahoo_symbol=yahoo_symbol,
                has_yahoo_override=bool(str(row.get("yahoo_symbol_override") or "").strip()),
            )
        )
    return out


def _ticker_candidate(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}\s+[A-Z0-9]{1,2}", raw):
        raw = re.sub(r"\s+", ".", raw)
    if not raw or " " in raw or len(raw) > 24:
        return None
    if not re.fullmatch(r"[A-Z0-9&.\-]+", raw):
        return None
    return raw


def _asset_matches_exchange(row: dict[str, Any], exchange_code: str) -> bool:
    country = (row.get("home_country") or "").strip().upper()
    quote_ccy = (row.get("quote_currency") or "").strip().upper()
    if exchange_code == "NSE":
        return country == "IN" or quote_ccy == "INR"
    if exchange_code == "SGX":
        return country == "SG" or quote_ccy == "SGD"
    if exchange_code == "HKEX":
        return country == "HK" or quote_ccy == "HKD"
    if exchange_code == "US":
        return country == "US" or quote_ccy == "USD"
    return False


def _backfill_symbol_map_for_exchange(db: Session, exchange_code: str) -> int:
    rows = db.execute(
        text(
            """
            SELECT a.id AS asset_id, a.symbol, a.name, a.quote_currency, a.home_country
            FROM assets a
            LEFT JOIN market_symbol_map m
              ON m.asset_id = a.id
             AND m.exchange_code = :exchange_code
             AND COALESCE(m.is_active, TRUE) = TRUE
            WHERE a.asset_class IN ('STOCK', 'FUND')
              AND m.id IS NULL
            ORDER BY a.id ASC
            """
        ),
        {"exchange_code": exchange_code},
    ).mappings().all()

    created = 0
    for row in rows:
        if not _asset_matches_exchange(row, exchange_code):
            continue
        exchange_symbol = _ticker_candidate(row.get("symbol")) or _ticker_candidate(row.get("name"))
        if not exchange_symbol:
            continue
        quote_currency = (row.get("quote_currency") or _EXCHANGE_DEFAULT_CCY.get(exchange_code) or "USD").upper()
        result = db.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, created_at, updated_at)
                VALUES
                  (:asset_id, :exchange_code, :exchange_symbol, :quote_currency, TRUE, :now, :now)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "asset_id": int(row["asset_id"]),
                "exchange_code": exchange_code,
                "exchange_symbol": exchange_symbol,
                "quote_currency": quote_currency,
                "now": datetime.now(tz=timezone.utc),
            },
        )
        if result.rowcount and result.rowcount > 0:
            created += 1
    return created



# market_data_runs.provider for a run that found no active symbols to fetch (#137).
EMPTY_EXCHANGE_PROVIDER = "none"


def _insert_run(db: Session, provider: str, exchange_code: str, trade_date: date) -> int:
    row = db.execute(
        text(
            """
            INSERT INTO market_data_runs (provider, exchange_code, trade_date, status, started_at)
            VALUES (:provider, :exchange_code, :trade_date, 'started', :started_at)
            RETURNING id
            """
        ),
        {
            "provider": provider,
            "exchange_code": exchange_code,
            "trade_date": trade_date,
            "started_at": datetime.now(tz=timezone.utc),
        },
    ).fetchone()
    return int(row[0])



def _finish_run(
    db: Session,
    run_id: int,
    *,
    status: str,
    requested_symbols: int,
    received_rows: int,
    upserted_rows: int,
    missing_symbols: int,
    error_summary: str | None = None,
) -> None:
    db.execute(
        text(
            """
            UPDATE market_data_runs
            SET status = :status,
                requested_symbols = :requested_symbols,
                received_rows = :received_rows,
                upserted_rows = :upserted_rows,
                missing_symbols = :missing_symbols,
                error_summary = :error_summary,
                finished_at = :finished_at
            WHERE id = :id
            """
        ),
        {
            "id": run_id,
            "status": status,
            "requested_symbols": requested_symbols,
            "received_rows": received_rows,
            "upserted_rows": upserted_rows,
            "missing_symbols": missing_symbols,
            "error_summary": error_summary,
            "finished_at": datetime.now(tz=timezone.utc),
        },
    )



def _insert_item(
    db: Session,
    *,
    run_id: int,
    asset_id: int,
    provider: str,
    exchange_code: str,
    symbol: str,
    trade_date: date,
    status: str,
    price: float | None,
    currency: str | None,
    source_note: str | None,
    reason_code: MarketDataReasonCode | None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO market_data_run_items
              (run_id, asset_id, provider, exchange_code, symbol, trade_date, status, price, currency, source_note, reason_code, created_at)
            VALUES
              (:run_id, :asset_id, :provider, :exchange_code, :symbol, :trade_date, :status, :price, :currency, :source_note, :reason_code, :created_at)
            """
        ),
        {
            "run_id": run_id,
            "asset_id": asset_id,
            "provider": provider,
            "exchange_code": exchange_code,
            "symbol": symbol,
            "trade_date": trade_date,
            "status": status,
            "price": price,
            "currency": currency,
            "source_note": source_note,
            "reason_code": reason_code.value if reason_code is not None else None,
            "created_at": datetime.now(tz=timezone.utc),
        },
    )



def _upsert_price(
    db: Session,
    *,
    asset_id: int,
    trade_date: date,
    price: float | None,
    currency: str,
    source: str,
    exchange_code: str,
    provider_symbol: str,
) -> bool:
    # Do not write anything if provider has no usable price.
    if price is None or not math.isfinite(float(price)) or float(price) <= 0:
        return False
    now = datetime.now(tz=timezone.utc)
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    is_sqlite = getattr(dialect, "name", "") == "sqlite"
    if is_sqlite:
        existing = db.execute(
            text(
                """
                SELECT id FROM prices
                WHERE asset_id = :asset_id AND trade_date = :trade_date AND source = :source
                LIMIT 1
                """
            ),
            {"asset_id": asset_id, "trade_date": trade_date, "source": source},
        ).fetchone()
        if existing:
            db.execute(
                text(
                    """
                    UPDATE prices
                    SET price = :price,
                        currency = :currency,
                        ts = :ts,
                        exchange_code = :exchange_code,
                        provider_symbol = :provider_symbol
                    WHERE id = :id
                    """
                ),
                {
                    "id": int(existing[0]),
                    "price": price,
                    "currency": currency,
                    "ts": now,
                    "exchange_code": exchange_code,
                    "provider_symbol": provider_symbol,
                },
            )
        else:
            db.execute(
                text(
                    """
                    INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol)
                    VALUES (:asset_id, :ts, :price, :currency, :source, :trade_date, :exchange_code, :provider_symbol)
                    """
                ),
                {
                    "asset_id": asset_id,
                    "ts": now,
                    "price": price,
                    "currency": currency,
                    "source": source,
                    "trade_date": trade_date,
                    "exchange_code": exchange_code,
                    "provider_symbol": provider_symbol,
                },
            )
        return True

    db.execute(
        text(
            """
            INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol)
            VALUES (:asset_id, :ts, :price, :currency, :source, :trade_date, :exchange_code, :provider_symbol)
            ON CONFLICT (asset_id, trade_date, source) WHERE trade_date IS NOT NULL
            DO UPDATE SET
              ts = EXCLUDED.ts,
              price = EXCLUDED.price,
              currency = EXCLUDED.currency,
              exchange_code = EXCLUDED.exchange_code,
              provider_symbol = EXCLUDED.provider_symbol
            """
        ),
        {
            "asset_id": asset_id,
            "ts": now,
            "price": price,
            "currency": currency,
            "source": source,
            "trade_date": trade_date,
            "exchange_code": exchange_code,
            "provider_symbol": provider_symbol,
        },
    )
    return True



def _upsert_dividend_snapshot(
    db: Session,
    *,
    asset_id: int,
    as_of_date: date,
    yield_rate: float | None,
    annual_dividend_per_share: float | None,
    price: float | None,
    currency: str,
    source: str,
    exchange_code: str,
    provider_symbol: str,
) -> bool:
    if yield_rate is None or not math.isfinite(float(yield_rate)) or float(yield_rate) < 0:
        return False
    now = datetime.now(tz=timezone.utc)
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    is_sqlite = getattr(dialect, "name", "") == "sqlite"

    params = {
        "asset_id": asset_id,
        "as_of_date": as_of_date,
        "yield_rate": float(yield_rate),
        "annual_dividend_per_share": annual_dividend_per_share,
        "price": price,
        "currency": currency,
        "source": source,
        "exchange_code": exchange_code,
        "provider_symbol": provider_symbol,
        "created_at": now,
        "updated_at": now,
    }

    if is_sqlite:
        existing = db.execute(
            text(
                """
                SELECT id
                FROM market_dividend_yields
                WHERE asset_id = :asset_id
                  AND as_of_date = :as_of_date
                  AND source = :source
                LIMIT 1
                """
            ),
            params,
        ).fetchone()
        if existing:
            db.execute(
                text(
                    """
                    UPDATE market_dividend_yields
                    SET yield_rate = :yield_rate,
                        annual_dividend_per_share = :annual_dividend_per_share,
                        price = :price,
                        currency = :currency,
                        exchange_code = :exchange_code,
                        provider_symbol = :provider_symbol,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {**params, "id": int(existing[0])},
            )
        else:
            db.execute(
                text(
                    """
                    INSERT INTO market_dividend_yields
                      (asset_id, as_of_date, yield_rate, annual_dividend_per_share, price, currency, source, exchange_code, provider_symbol, created_at, updated_at)
                    VALUES
                      (:asset_id, :as_of_date, :yield_rate, :annual_dividend_per_share, :price, :currency, :source, :exchange_code, :provider_symbol, :created_at, :updated_at)
                    """
                ),
                params,
            )
        return True

    db.execute(
        text(
            """
            INSERT INTO market_dividend_yields
              (asset_id, as_of_date, yield_rate, annual_dividend_per_share, price, currency, source, exchange_code, provider_symbol, created_at, updated_at)
            VALUES
              (:asset_id, :as_of_date, :yield_rate, :annual_dividend_per_share, :price, :currency, :source, :exchange_code, :provider_symbol, :created_at, :updated_at)
            ON CONFLICT (asset_id, as_of_date, source)
            DO UPDATE SET
              yield_rate = EXCLUDED.yield_rate,
              annual_dividend_per_share = EXCLUDED.annual_dividend_per_share,
              price = EXCLUDED.price,
              currency = EXCLUDED.currency,
              exchange_code = EXCLUDED.exchange_code,
              provider_symbol = EXCLUDED.provider_symbol,
              updated_at = EXCLUDED.updated_at
            """
        ),
        params,
    )
    return True


def _refresh_dividend_yields_for_exchange(
    db: Session,
    *,
    exchange_code: str,
    trade_date: date,
    symbols: list[SymbolMapRow],
    yfinance: YFinanceProvider,
) -> int:
    by_symbol: dict[str, list[SymbolMapRow]] = {}
    for row in symbols:
        provider_symbol = row.yahoo_symbol.strip().upper()
        if not provider_symbol:
            continue
        by_symbol.setdefault(provider_symbol, []).append(row)
    if not by_symbol:
        return 0
    try:
        snapshots = yfinance.fetch_dividend_yields(
            list(by_symbol.keys()),
            exchange_code=exchange_code,
            as_of_date=trade_date,
        )
    except Exception:  # noqa: BLE001
        return 0

    upserted = 0
    for provider_symbol, mapped_rows in by_symbol.items():
        payload = snapshots.get(provider_symbol.upper())
        if not payload:
            continue
        try:
            yield_rate = float(payload.get("yield_rate") or 0.0)
        except Exception:  # noqa: BLE001
            continue
        annual_dividend = payload.get("annual_dividend")
        price = payload.get("price")
        for row in mapped_rows:
            currency = str(payload.get("currency") or row.quote_currency or "USD").upper()
            written = _upsert_dividend_snapshot(
                db,
                asset_id=row.asset_id,
                as_of_date=trade_date,
                yield_rate=yield_rate,
                annual_dividend_per_share=float(annual_dividend) if annual_dividend is not None else None,
                price=float(price) if price is not None else None,
                currency=currency,
                source="yfinance_dividend",
                exchange_code=exchange_code,
                provider_symbol=provider_symbol,
            )
            if written:
                upserted += 1
    return upserted


def _symbols_for_provider(provider_name: str, symbols: list[SymbolMapRow]) -> dict[str, list[SymbolMapRow]]:
    out: dict[str, list[SymbolMapRow]] = {}
    for row in symbols:
        if provider_name == "eodhd":
            symbol = row.eodhd_symbol
        elif provider_name == "finnhub":
            symbol = row.finnhub_symbol
        elif provider_name == "yfinance":
            symbol = row.yahoo_symbol
        else:
            symbol = row.yahoo_symbol
        symbol = symbol.strip().upper()
        if symbol:
            out.setdefault(symbol, []).append(row)
    return out


def _batched(values: list[str], size: int) -> list[list[str]]:
    return [values[idx : idx + size] for idx in range(0, len(values), size)]


def _latest_price_details(db: Session, asset_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(str(int(asset_id)) for asset_id in sorted(asset_ids))
    rows = db.execute(
        text(
            f"""
            SELECT p.asset_id, p.price, p.currency, p.trade_date, p.source, p.provider_symbol, p.exchange_code
            FROM prices p
            JOIN (
              SELECT asset_id, MAX(trade_date) AS trade_date
              FROM prices
              WHERE asset_id IN ({placeholders}) AND trade_date IS NOT NULL
              GROUP BY asset_id
            ) latest ON latest.asset_id = p.asset_id AND latest.trade_date = p.trade_date
            """
        )
    ).mappings().all()
    return {
        int(row["asset_id"]): {
            "price": float(row["price"]) if row["price"] is not None else None,
            "currency": row["currency"],
            "trade_date": row["trade_date"],
            "source": row["source"],
            "provider_symbol": row["provider_symbol"],
            "exchange_code": row["exchange_code"],
        }
        for row in rows
    }


def _latest_run_items(db: Session, exchange_code: str, asset_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(str(int(asset_id)) for asset_id in sorted(asset_ids))
    rows = db.execute(
        text(
            f"""
            SELECT i.asset_id, i.provider, i.symbol, i.status, i.trade_date, i.source_note, i.reason_code, i.created_at
            FROM market_data_run_items i
            JOIN (
              SELECT asset_id, MAX(id) AS id
              FROM market_data_run_items
              WHERE exchange_code = :exchange_code AND asset_id IN ({placeholders})
              GROUP BY asset_id
            ) latest ON latest.id = i.id
            """
        ),
        {"exchange_code": exchange_code},
    ).mappings().all()
    return {int(row["asset_id"]): dict(row) for row in rows}


def _latest_exchange_run_summary(db: Session, exchange_code: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT id, provider, exchange_code, trade_date, status,
                   requested_symbols, received_rows, upserted_rows, missing_symbols,
                   started_at, finished_at, error_summary
            FROM market_data_runs
            WHERE exchange_code = :exchange_code
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ),
        {"exchange_code": exchange_code},
    ).mappings().one_or_none()
    return dict(row) if row else None


def _normalize_trade_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def _freshness_status(trade_date_value: Any) -> tuple[str, int | None]:
    trade_date = _normalize_trade_date(trade_date_value)
    if trade_date is None:
        return "missing", None
    age_days = max(0, (datetime.now(tz=timezone.utc).date() - trade_date).days)
    return ("stale" if age_days > _quote_stale_days() else "fresh"), age_days


def _provider_from_source(source: str | None) -> str | None:
    if not source:
        return None
    provider = source.split("_", 1)[0].strip()
    return provider or None


def _exchange_diagnostics(
    db: Session,
    exchange_code: str,
    *,
    attempted_asset_ids: set[int] | None = None,
    deferred_asset_ids: set[int] | None = None,
) -> dict[str, Any]:
    symbols = _load_symbols(db, exchange_code, daily_limit=0)
    asset_ids = {row.asset_id for row in symbols}
    latest_prices = _latest_price_details(db, asset_ids)
    latest_items = _latest_run_items(db, exchange_code, asset_ids)
    latest_run = _latest_exchange_run_summary(db, exchange_code)
    latest_run_started_at = latest_run.get("started_at") if latest_run else None
    deferred_lookup = deferred_asset_ids or set()

    items: list[dict[str, Any]] = []
    for row in symbols:
        latest_price = latest_prices.get(row.asset_id, {})
        latest_item = latest_items.get(row.asset_id, {})
        freshness_status, age_days = _freshness_status(latest_price.get("trade_date"))

        attempt_status = str(latest_item.get("status") or "").lower()
        refresh_status = freshness_status
        if attempted_asset_ids is not None:
            if row.asset_id in deferred_lookup:
                refresh_status = "deferred"
            elif attempt_status in {"upserted", "fallback_upserted"}:
                refresh_status = "refreshed"
            elif attempt_status in {"missing", "invalid"}:
                refresh_status = "failed"
        else:
            if attempt_status in {"upserted", "fallback_upserted"}:
                refresh_status = "refreshed"
            elif attempt_status in {"missing", "invalid"}:
                refresh_status = "failed"
            elif latest_run_started_at is not None and not latest_item:
                refresh_status = "deferred"

        items.append(
            {
                "asset_id": row.asset_id,
                "symbol": row.exchange_symbol,
                "mapped_symbol": row.exchange_symbol,
                "provider_symbol": latest_item.get("symbol") or latest_price.get("provider_symbol"),
                "provider": latest_item.get("provider") or _provider_from_source(latest_price.get("source")),
                "source": latest_price.get("source"),
                "currency": latest_price.get("currency") or row.quote_currency,
                "latest_price": latest_price.get("price"),
                "latest_trade_date": (
                    _normalize_trade_date(latest_price.get("trade_date")).isoformat()
                    if _normalize_trade_date(latest_price.get("trade_date"))
                    else None
                ),
                "age_days": age_days,
                "freshness_status": freshness_status,
                "refresh_status": refresh_status,
                "failure_reason": latest_item.get("source_note"),
                "reason_code": latest_item.get("reason_code"),
                "attempt_status": attempt_status or None,
            }
        )

    items.sort(key=lambda item: ((item["refresh_status"] != "failed"), (item["freshness_status"] == "fresh"), item["symbol"]))
    return {
        "exchange_code": exchange_code,
        "latest_run": latest_run,
        "diagnostics_summary": _diagnostics_summary(items),
        "symbols": items,
    }


def _diagnostics_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "active_symbols": len(items),
        "refreshed": 0,
        "failed": 0,
        "deferred": 0,
        "fresh": 0,
        "stale": 0,
        "missing": 0,
    }
    for item in items:
        summary[item["freshness_status"]] += 1
        if item["refresh_status"] in {"refreshed", "failed", "deferred"}:
            summary[item["refresh_status"]] += 1
    return summary


def held_asset_ids(db: Session, user_id: int) -> set[int]:
    """Assets the user holds or has held: a canonical position snapshot or a
    transaction in one of their accounts (#153). Market-data diagnostics are
    scoped to these so one user never sees another's tickers. (The legacy
    positions table is gone, #359.)"""
    scope = account_scope_sql("acc")
    rows = db.execute(
        text(
            f"""
            SELECT bi.asset_id
            FROM portfolio_position_snapshots ps
            JOIN broker_instruments bi ON bi.id = ps.broker_instrument_id
            JOIN broker_accounts ba ON ba.id = ps.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE bi.asset_id IS NOT NULL AND {scope}
            UNION
            SELECT t.asset_id
            FROM transactions t
            JOIN accounts acc ON acc.id = t.account_id
            WHERE t.asset_id IS NOT NULL AND {scope}
            """
        ),
        {"current_user_id": user_id},
    ).fetchall()
    return {int(row[0]) for row in rows}


def scope_exchange_diagnostics(diagnostics: dict[str, Any], asset_ids: set[int]) -> dict[str, Any]:
    """The same diagnostics restricted to ``asset_ids``, summary recounted.
    Run-level fields (latest_run, exchange_code) are kept as they are."""
    items = [item for item in diagnostics.get("symbols") or [] if item.get("asset_id") in asset_ids]
    return {**diagnostics, "diagnostics_summary": _diagnostics_summary(items), "symbols": items}


# Why a held position gets no live price (#222).
UNPRICED_NO_ASSET = "no_asset"  # its instrument isn't linked to an asset
UNPRICED_NO_SYMBOL = "no_symbol"  # the asset has no ticker on a configured exchange
UNPRICED_NO_QUOTE = "no_quote"  # it has a ticker, but no provider has returned a price
_PRICEABLE_SECURITY_TYPES = ("STK", "STOCK", "FUND", "ETF", "MF")


def _exchange_for(country: Any, currency: Any) -> str | None:
    row = {"home_country": country, "quote_currency": currency}
    for exchange_code in configured_exchanges():
        if _asset_matches_exchange(row, exchange_code):
            return exchange_code
    return None


def held_position_rows(db: Session, *, today: date, user_id: int | None) -> list[dict[str, Any]]:
    """Held stocks and funds on ``today``, one row per instrument: a non-zero
    quantity in its broker account's newest position snapshot on or before
    ``today`` (the read layer's rules, newest per broker account, without Flex
    routing or NAV coverage: every held instrument needs a price), in an open
    account (``user_id``'s accounts, or every account when None)."""
    params: dict[str, Any] = {
        "today": today,
        **{f"st{i}": t for i, t in enumerate(_PRICEABLE_SECURITY_TYPES)},
    }
    if user_id is not None:
        params["current_user_id"] = user_id
    security_types = ",".join(f":st{i}" for i in range(len(_PRICEABLE_SECURITY_TYPES)))
    held = effective_rows_sql(POSITIONS, BROKER_ACCOUNT_OWNER, anchor=":today", scoped=user_id is not None)
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT
              bi.id AS instrument_id,
              bi.asset_id,
              COALESCE(a.symbol, bi.symbol) AS symbol,
              COALESCE(a.name, bi.description, bi.symbol) AS name,
              COALESCE(a.quote_currency, bi.currency) AS currency,
              COALESCE(a.home_country, bi.country) AS country,
              bi.platform_code
            FROM ({held}) ps
            JOIN broker_instruments bi ON bi.id = ps.broker_instrument_id
            LEFT JOIN assets a ON a.id = bi.asset_id
            WHERE ps.quantity IS NOT NULL
              AND CAST(ps.quantity AS DOUBLE PRECISION) <> 0
              AND (
                CAST(a.asset_class AS TEXT) IN ('STOCK', 'FUND')
                OR (a.id IS NULL AND UPPER(COALESCE(bi.security_type, '')) IN ({security_types}))
              )
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def unpriced_held_positions(
    db: Session,
    *,
    user_id: int | None = None,
    exchange_code: str | None = None,
) -> list[dict[str, Any]]:
    """Held stocks and funds that the quote refresh can't price (#222), one row
    per instrument: not linked to an asset, no ticker on a configured exchange,
    or never quoted. Held means a non-zero quantity in its account's newest
    authoritative position snapshot on or before today, in an open account.
    "Today" is the app clock's date (the request user's timezone, else ``TZ``;
    D-62), the calendar uploads are dated by (D-34), not the UTC date: between
    00:00 and 08:00 in Singapore a statement dated today already counts.
    ``user_id`` limits it
    to that user's accounts (None: every account, for the refresh job's own
    check); ``exchange_code`` to the exchange each position would be priced on
    (its symbol map's, else the one its country or currency points to)."""
    rows = held_position_rows(db, today=app_today(), user_id=user_id)
    if not rows:
        return []

    asset_ids = {int(row["asset_id"]) for row in rows if row["asset_id"] is not None}
    tickers: dict[int, str] = {}
    if asset_ids:
        placeholders = ",".join(str(asset_id) for asset_id in sorted(asset_ids))
        exchanges = set(configured_exchanges())
        map_rows = db.execute(
            text(
                f"""
                SELECT m.asset_id, m.exchange_code, m.exchange_symbol, a.symbol AS asset_symbol
                FROM market_symbol_map m
                JOIN assets a ON a.id = m.asset_id
                WHERE m.is_active = TRUE AND m.asset_id IN ({placeholders})
                ORDER BY m.asset_id, m.exchange_code
                """
            )
        ).mappings().all()
        for map_row in map_rows:
            ex, sym = _resolved_exchange_symbol(map_row)
            if sym and ex in exchanges:
                tickers.setdefault(int(map_row["asset_id"]), ex)
    quoted = set(_latest_price_details(db, set(tickers)).keys())

    wanted = exchange_code.upper() if exchange_code else None
    out: list[dict[str, Any]] = []
    for row in rows:
        asset_id = int(row["asset_id"]) if row["asset_id"] is not None else None
        if asset_id is None:
            reason, ex = UNPRICED_NO_ASSET, _exchange_for(row["country"], row["currency"])
        elif asset_id not in tickers:
            reason, ex = UNPRICED_NO_SYMBOL, _exchange_for(row["country"], row["currency"])
        elif asset_id not in quoted:
            reason, ex = UNPRICED_NO_QUOTE, tickers[asset_id]
        else:
            continue
        if wanted is not None and ex != wanted:
            continue
        out.append(
            {
                "instrument_id": int(row["instrument_id"]),
                "asset_id": asset_id,
                "symbol": row["symbol"],
                "name": row["name"],
                "currency": row["currency"],
                "exchange_code": ex,
                "platform": row["platform_code"],
                "reason": reason,
            }
        )
    out.sort(key=lambda item: (item["exchange_code"] or "", str(item["symbol"] or "")))
    return out


def unpriced_summary(exchange_code: str, count: int) -> str:
    return (
        f"{count} held position{'s' if count != 1 else ''} on {exchange_code} "
        "can't be priced (no linked asset, ticker or quote)"
    )


def _fetch_quotes(
    provider_name: str,
    *,
    exchange_code: str,
    symbols: list[str],
    trade_date: date,
    eodhd: EODHDProvider,
    finnhub: FinnhubProvider,
    yfinance: YFinanceProvider,
    yahoo: YahooProvider,
) -> dict[str, EodQuote]:
    if provider_name == "eodhd":
        return eodhd.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)
    if provider_name == "finnhub":
        return finnhub.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)
    if provider_name == "yfinance":
        return yfinance.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)
    return yahoo.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)



# #320: an Indian stock Yahoo lists only on BSE (NSE Ltd itself, NSDL) has no <CODE>.NS quote.
# After the provider chain, each NSE symbol still unpriced and without an override is tried
# once as <CODE>.BO; when Yahoo has it, the price is stored and <CODE>.BO is saved as the
# symbol's Yahoo override, so later refreshes ask for it directly. MARKET_DATA_BSE_FALLBACK=0
# turns it off.
BSE_FALLBACK_PROVIDER = "yfinance_bse"
BSE_FALLBACK_NOTE = "auto: no NSE quote on Yahoo; BSE ticker {symbol} saved as the Yahoo override (#320)"


def _bse_fallback_enabled() -> bool:
    return os.getenv("MARKET_DATA_BSE_FALLBACK", "1").strip().lower() not in {"0", "false", "no", "off"}


def bse_symbol_for(yahoo_symbol: str) -> str | None:
    """``<CODE>.NS`` → ``<CODE>.BO``; None for anything else."""
    symbol = (yahoo_symbol or "").strip().upper()
    if symbol.endswith(".NS") and len(symbol) > 3:
        return f"{symbol[:-3]}.BO"
    return None


def store_yahoo_override(db: Session, *, asset_id: int, exchange_code: str, yahoo_symbol: str) -> str:
    """Save ``yahoo_symbol`` as the asset's Yahoo override on ``exchange_code``, creating the
    map row if there's none. Returns "set", "create_map" or "unchanged". Doesn't commit."""
    exchange_code = exchange_code.strip().upper()
    yahoo_symbol = yahoo_symbol.strip().upper()
    now = datetime.now(tz=timezone.utc)
    row = db.execute(
        text(
            """
            SELECT id, yahoo_symbol_override FROM market_symbol_map
            WHERE asset_id = :asset_id AND exchange_code = :exchange_code
            ORDER BY id LIMIT 1
            """
        ),
        {"asset_id": asset_id, "exchange_code": exchange_code},
    ).mappings().first()
    if row is not None:
        if str(row["yahoo_symbol_override"] or "").strip().upper() == yahoo_symbol:
            return "unchanged"
        db.execute(
            text(
                """
                UPDATE market_symbol_map
                SET yahoo_symbol_override = :override, is_active = TRUE, updated_at = :now
                WHERE id = :id
                """
            ),
            {"override": yahoo_symbol, "now": now, "id": int(row["id"])},
        )
        return "set"
    asset = db.execute(
        text("SELECT symbol, quote_currency FROM assets WHERE id = :id"), {"id": asset_id}
    ).mappings().first()
    if asset is None:
        raise ValueError(f"No asset {asset_id}")
    db.execute(
        text(
            """
            INSERT INTO market_symbol_map
              (asset_id, exchange_code, exchange_symbol, quote_currency, is_active,
               yahoo_symbol_override, created_at, updated_at)
            VALUES (:asset_id, :exchange_code, :exchange_symbol, :currency, TRUE, :override, :now, :now)
            """
        ),
        {
            "asset_id": asset_id,
            "exchange_code": exchange_code,
            "exchange_symbol": str(asset["symbol"] or "").strip().upper(),
            "currency": str(asset["quote_currency"] or _EXCHANGE_DEFAULT_CCY.get(exchange_code, "USD")).upper(),
            "override": yahoo_symbol,
            "now": now,
        },
    )
    return "create_map"


def _try_bse_fallback(
    db: Session,
    *,
    exchange_code: str,
    rows: list[SymbolMapRow],
    trade_date: date,
    yfinance: YFinanceProvider,
) -> tuple[list[SymbolMapRow], int, int | None]:
    """(still unresolved, prices written, run id or None) after trying ``.BO`` for the
    NSE rows left without a quote that have no override of their own."""
    if exchange_code != "NSE" or not rows or not _bse_fallback_enabled():
        return rows, 0, None
    candidates: dict[str, list[SymbolMapRow]] = {}
    for row in rows:
        bse = None if row.has_yahoo_override else bse_symbol_for(row.yahoo_symbol)
        if bse:
            candidates.setdefault(bse, []).append(row)
    if not candidates:
        return rows, 0, None

    run_id = _insert_run(db, provider=BSE_FALLBACK_PROVIDER, exchange_code=exchange_code, trade_date=trade_date)
    error: str | None = None
    try:
        quotes = yfinance.fetch_prices(list(candidates), exchange_code=exchange_code, trade_date=trade_date)
    except Exception as exc:  # noqa: BLE001
        quotes, error = {}, str(exc)
    written = 0
    resolved: set[int] = set()
    for bse, mapped_rows in candidates.items():
        quote = quotes.get(bse.upper())
        if quote is None or quote.close is None or not math.isfinite(float(quote.close)) or float(quote.close) <= 0:
            continue
        for row in mapped_rows:
            if not _upsert_price(
                db,
                asset_id=row.asset_id,
                trade_date=quote.trade_date,
                price=quote.close,
                currency=row.quote_currency,
                source="yfinance_market",
                exchange_code=exchange_code,
                provider_symbol=bse,
            ):
                continue
            store_yahoo_override(db, asset_id=row.asset_id, exchange_code=exchange_code, yahoo_symbol=bse)
            _insert_item(
                db,
                run_id=run_id,
                asset_id=row.asset_id,
                provider=BSE_FALLBACK_PROVIDER,
                exchange_code=exchange_code,
                symbol=bse,
                trade_date=quote.trade_date,
                status="fallback_upserted",
                price=quote.close,
                currency=row.quote_currency,
                source_note=BSE_FALLBACK_NOTE.format(symbol=bse),
                reason_code=None,
            )
            written += 1
            resolved.add(row.asset_id)
    still = [row for row in rows if row.asset_id not in resolved]
    _finish_run(
        db,
        run_id,
        status="failed" if error and not written else ("success" if written == sum(map(len, candidates.values())) else "partial"),
        requested_symbols=len(candidates),
        received_rows=len(quotes),
        upserted_rows=written,
        missing_symbols=sum(map(len, candidates.values())) - written,
        error_summary=error,
    )
    return still, written, run_id


def probe_yahoo_ticker(
    yahoo_symbol: str, *, exchange_code: str | None = None, yfinance: YFinanceProvider | None = None
) -> dict[str, Any]:
    """Ask Yahoo (yfinance) for one ticker's latest close (#320): {found, yahoo_symbol, close,
    trade_date, currency, error}. A ticker without a market suffix gets the exchange's."""
    candidate = _ticker_candidate(yahoo_symbol)
    if candidate is None:
        return {"found": False, "yahoo_symbol": (yahoo_symbol or "").strip().upper(), "error": "Not a ticker"}
    symbol = _default_yahoo_symbol(candidate, exchange_code) if exchange_code else candidate
    provider = yfinance or YFinanceProvider()
    try:
        quotes = provider.fetch_prices([symbol], exchange_code=exchange_code)
    except Exception as exc:  # noqa: BLE001
        return {"found": False, "yahoo_symbol": symbol, "error": str(exc)}
    quote = quotes.get(symbol.upper())
    if quote is None or quote.close is None or not math.isfinite(float(quote.close)) or float(quote.close) <= 0:
        return {"found": False, "yahoo_symbol": symbol, "error": f"Yahoo has no quote for {symbol}"}
    return {
        "found": True,
        "yahoo_symbol": symbol,
        "close": float(quote.close),
        "trade_date": quote.trade_date.isoformat() if quote.trade_date else None,
        "currency": quote.currency,
        "error": None,
    }


def apply_yahoo_ticker(
    db: Session,
    *,
    asset_id: int,
    exchange_code: str,
    yahoo_symbol: str,
    yfinance: YFinanceProvider | None = None,
) -> dict[str, Any]:
    """Test ``yahoo_symbol``; when Yahoo has it, save it as the asset's override on
    ``exchange_code`` and store the quote, so the holding is priced at once (#320).
    Raises ValueError when the asset is unknown or Yahoo has no quote."""
    exchange_code = exchange_code.strip().upper()
    asset = db.execute(
        text("SELECT id, quote_currency FROM assets WHERE id = :id"), {"id": asset_id}
    ).mappings().first()
    if asset is None:
        raise ValueError(f"No asset {asset_id}")
    tested = probe_yahoo_ticker(yahoo_symbol, exchange_code=exchange_code, yfinance=yfinance)
    if not tested["found"]:
        raise ValueError(tested["error"] or f"Yahoo has no quote for {tested['yahoo_symbol']}")
    action = store_yahoo_override(db, asset_id=asset_id, exchange_code=exchange_code, yahoo_symbol=tested["yahoo_symbol"])
    currency = str(asset["quote_currency"] or tested.get("currency") or "USD").upper()
    _upsert_price(
        db,
        asset_id=asset_id,
        trade_date=date.fromisoformat(tested["trade_date"]) if tested.get("trade_date") else datetime.now(tz=timezone.utc).date(),
        price=tested["close"],
        currency=currency,
        source="yfinance_market",
        exchange_code=exchange_code,
        provider_symbol=tested["yahoo_symbol"],
    )
    db.commit()
    return {**tested, "asset_id": asset_id, "exchange_code": exchange_code, "action": action, "currency": currency}


def run_exchange_refresh(
    db: Session,
    exchange_code: str,
    *,
    trade_date: date | None = None,
    full_coverage: bool = False,
    batch_size: int | None = None,
    eodhd: EODHDProvider | None = None,
    finnhub: FinnhubProvider | None = None,
    yfinance: YFinanceProvider | None = None,
    yahoo: YahooProvider | None = None,
) -> dict[str, Any]:
    exchange_code = exchange_code.upper()
    trade_date = trade_date or datetime.now(tz=timezone.utc).date()
    eodhd = eodhd or EODHDProvider()
    finnhub = finnhub or FinnhubProvider()
    yfinance = yfinance or YFinanceProvider()
    yahoo = yahoo or YahooProvider()

    backfilled_symbols = _backfill_symbol_map_for_exchange(db, exchange_code)
    daily_limit = _daily_limit()
    batch_size = batch_size or _refresh_batch_size()
    all_symbols = _load_symbols(db, exchange_code, daily_limit=0)
    symbols = all_symbols if full_coverage else all_symbols[:daily_limit]
    deferred_symbols = all_symbols[len(symbols) :] if not full_coverage else []
    if not symbols:
        run_ids_empty: dict[str, int] = {}
        unpriced = len(unpriced_held_positions(db, exchange_code=exchange_code))
        if not all_symbols:
            # Nothing to fetch on this exchange (#137): still record the run, as a
            # 0-symbol run by provider "none", so the scheduler's done-check (a
            # success or partial row per exchange since the window's close) is
            # satisfied and the window runs once a day, not every retry interval.
            # Held positions that should have been priced here make it "partial"
            # with the reason, not a silent success (#222, D-54).
            run_id = _insert_run(db, provider=EMPTY_EXCHANGE_PROVIDER, exchange_code=exchange_code, trade_date=trade_date)
            _finish_run(
                db,
                run_id,
                status="partial" if unpriced else "success",
                requested_symbols=0,
                received_rows=0,
                upserted_rows=0,
                missing_symbols=0,
                error_summary=unpriced_summary(exchange_code, unpriced) if unpriced else None,
            )
            run_ids_empty[EMPTY_EXCHANGE_PROVIDER] = run_id
        diagnostics = _exchange_diagnostics(
            db,
            exchange_code,
            attempted_asset_ids=set(),
            deferred_asset_ids={row.asset_id for row in deferred_symbols},
        )
        db.commit()
        return {
            "exchange_code": exchange_code,
            "trade_date": trade_date.isoformat(),
            "requested_symbols": 0,
            "total_active_symbols": len(all_symbols),
            "upserted_rows": 0,
            "dividend_rows_upserted": 0,
            "missing_symbols": 0,
            "backfilled_symbols": backfilled_symbols,
            "status": "partial" if (deferred_symbols or unpriced) else "success",
            "unpriced_holdings": unpriced,
            "providers": [],
            "run_ids": run_ids_empty,
            "daily_limit": daily_limit,
            "full_coverage": full_coverage,
            "batch_size": batch_size,
            "deferred_symbols": len(deferred_symbols),
            "diagnostics": diagnostics,
        }

    unresolved = list(symbols)
    requested_symbols = len(symbols)
    total_upserted = 0
    total_invalid = 0
    providers_used: list[str] = []
    run_ids: dict[str, int] = {}
    attempted_asset_ids: set[int] = set()

    for step_idx, provider_name in enumerate(_provider_chain(exchange_code)):
        if not unresolved:
            break

        by_symbol = _symbols_for_provider(provider_name, unresolved)
        if not by_symbol:
            continue

        provider_symbols = list(by_symbol.keys())
        run_id = _insert_run(db, provider=provider_name, exchange_code=exchange_code, trade_date=trade_date)
        providers_used.append(provider_name)
        run_ids[provider_name] = run_id

        provider_error: str | None = None
        provider_failures: dict[str, tuple[str, MarketDataReasonCode]] = {}
        quotes: dict[str, EodQuote] = {}
        for batch_symbols in _batched(provider_symbols, batch_size):
            try:
                quotes.update(
                    _fetch_quotes(
                        provider_name,
                        exchange_code=exchange_code,
                        symbols=batch_symbols,
                        trade_date=trade_date,
                        eodhd=eodhd,
                        finnhub=finnhub,
                        yfinance=yfinance,
                        yahoo=yahoo,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                provider_error = str(exc)
                reason_code = _reason_code_for_exception(exc)
                for failed_symbol in batch_symbols:
                    provider_failures[failed_symbol.upper()] = (provider_error, reason_code)

        upserted_rows = 0
        invalid_rows = 0
        next_unresolved: list[SymbolMapRow] = []
        for provider_symbol, mapped_rows in by_symbol.items():
            for row in mapped_rows:
                attempted_asset_ids.add(row.asset_id)
            quote = quotes.get(provider_symbol.upper())
            if quote is None:
                failure = provider_failures.get(provider_symbol.upper())
                for row in mapped_rows:
                    next_unresolved.append(row)
                    _insert_item(
                        db,
                        run_id=run_id,
                        asset_id=row.asset_id,
                        provider=provider_name,
                        exchange_code=exchange_code,
                        symbol=provider_symbol,
                        trade_date=trade_date,
                        status="missing",
                        price=None,
                        currency=row.quote_currency,
                        source_note=failure[0] if failure else None,
                        reason_code=failure[1] if failure else MarketDataReasonCode.NO_TRADE_REPORTED,
                    )
                continue

            # If provider returns an invalid quote, record it and do not
            # override existing rows or attempt fallback writes for this symbol.
            if quote.close is None or not math.isfinite(float(quote.close)) or float(quote.close) <= 0:
                invalid_rows += len(mapped_rows)
                total_invalid += len(mapped_rows)
                for row in mapped_rows:
                    _insert_item(
                        db,
                        run_id=run_id,
                        asset_id=row.asset_id,
                        provider=provider_name,
                        exchange_code=exchange_code,
                        symbol=quote.symbol,
                        trade_date=trade_date,
                        status="invalid",
                        price=quote.close,
                        currency=(row.quote_currency or quote.currency or "USD").upper(),
                        source_note="missing/invalid price from provider",
                        reason_code=MarketDataReasonCode.INVALID_PRICE,
                    )
                continue

            for row in mapped_rows:
                source = f"{provider_name}_market"
                # Asset quote currency is source of truth for valuation conversion.
                resolved_currency = (row.quote_currency or quote.currency or "USD").upper()
                written = _upsert_price(
                    db,
                    asset_id=row.asset_id,
                    trade_date=quote.trade_date,
                    price=quote.close,
                    currency=resolved_currency,
                    source=source,
                    exchange_code=exchange_code,
                    provider_symbol=quote.symbol,
                )
                if not written:
                    next_unresolved.append(row)
                    _insert_item(
                        db,
                        run_id=run_id,
                        asset_id=row.asset_id,
                        provider=provider_name,
                        exchange_code=exchange_code,
                        symbol=quote.symbol,
                        trade_date=trade_date,
                        status="missing",
                        price=None,
                        currency=resolved_currency,
                        source_note="missing/invalid price from provider",
                        reason_code=MarketDataReasonCode.INVALID_PRICE,
                    )
                    continue
                upserted_rows += 1
                total_upserted += 1

                _insert_item(
                    db,
                    run_id=run_id,
                    asset_id=row.asset_id,
                    provider=provider_name,
                    exchange_code=exchange_code,
                    symbol=quote.symbol,
                    trade_date=quote.trade_date,
                    status="upserted" if step_idx == 0 else "fallback_upserted",
                    price=quote.close,
                    currency=resolved_currency,
                    source_note=None if step_idx == 0 else "resolved via fallback",
                    reason_code=None,
                )

        missing_symbols = len(next_unresolved) + invalid_rows
        run_status = "failed" if provider_error and upserted_rows == 0 else ("partial" if missing_symbols else "success")
        _finish_run(
            db,
            run_id,
            status=run_status,
            requested_symbols=len(provider_symbols),
            received_rows=len(quotes),
            upserted_rows=upserted_rows,
            missing_symbols=missing_symbols,
            error_summary=provider_error,
        )
        unresolved = next_unresolved

    unresolved, bse_upserted, bse_run_id = _try_bse_fallback(
        db, exchange_code=exchange_code, rows=unresolved, trade_date=trade_date, yfinance=yfinance
    )
    if bse_run_id is not None:
        total_upserted += bse_upserted
        providers_used.append(BSE_FALLBACK_PROVIDER)
        run_ids[BSE_FALLBACK_PROVIDER] = bse_run_id

    dividend_rows_upserted = _refresh_dividend_yields_for_exchange(
        db,
        exchange_code=exchange_code,
        trade_date=trade_date,
        symbols=all_symbols,
        yfinance=yfinance,
    )

    diagnostics = _exchange_diagnostics(
        db,
        exchange_code,
        attempted_asset_ids=attempted_asset_ids,
        deferred_asset_ids={row.asset_id for row in deferred_symbols},
    )
    unpriced = len(unpriced_held_positions(db, exchange_code=exchange_code))
    db.commit()
    return {
        "exchange_code": exchange_code,
        "trade_date": trade_date.isoformat(),
        "requested_symbols": requested_symbols,
        "total_active_symbols": len(all_symbols),
        "upserted_rows": total_upserted,
        "dividend_rows_upserted": dividend_rows_upserted,
        "missing_symbols": len(unresolved) + total_invalid,
        "backfilled_symbols": backfilled_symbols,
        "status": (
            "success" if (not unresolved and total_invalid == 0 and not deferred_symbols and not unpriced) else "partial"
        ),
        "unpriced_holdings": unpriced,
        "providers": providers_used,
        "run_ids": run_ids,
        "daily_limit": daily_limit,
        "full_coverage": full_coverage,
        "batch_size": batch_size,
        "deferred_symbols": len(deferred_symbols),
        "diagnostics": diagnostics,
    }



def run_all_exchanges(
    db: Session,
    exchanges: list[str] | None = None,
    *,
    full_coverage: bool = True,
    batch_size: int | None = None,
) -> dict[str, Any]:
    exchanges = exchanges or configured_exchanges()
    results = [
        run_exchange_refresh(db, ex, full_coverage=full_coverage, batch_size=batch_size)
        for ex in exchanges
    ]
    return {"exchanges": results}



def latest_status_by_exchange(db: Session, *, asset_ids: set[int] | None = None) -> list[dict[str, Any]]:
    """Per-exchange run status and per-symbol diagnostics. ``asset_ids`` limits
    the symbols (and their counts) to those assets; None means every symbol
    (admins, schedulers)."""
    payload: list[dict[str, Any]] = []
    for exchange_code in configured_exchanges():
        diagnostics = _exchange_diagnostics(db, exchange_code)
        if asset_ids is not None:
            diagnostics = scope_exchange_diagnostics(diagnostics, asset_ids)
        latest_run = diagnostics.pop("latest_run", None) or {}
        payload.append(
            {
                **latest_run,
                "exchange_code": exchange_code,
                **diagnostics,
            }
        )
    return payload



def freshness_counts_by_exchange(db: Session, *, asset_ids: set[int] | None = None) -> dict[str, dict[str, int]]:
    """{exchange: {"fresh", "stale", "missing"}} for the configured exchanges:
    the diagnostics_summary freshness counts latest_status_by_exchange reports,
    from one query instead of four per exchange (#147). Each active symbol's
    freshness is the age of its newest dated price. ``asset_ids`` limits the
    count to those assets (#153); None counts every symbol."""
    exchanges = configured_exchanges()
    counts = {ex: {"fresh": 0, "stale": 0, "missing": 0} for ex in exchanges}
    if not exchanges:
        return counts
    params = {f"ex{i}": ex for i, ex in enumerate(exchanges)}
    rows = db.execute(
        text(
            f"""
            SELECT m.asset_id,
                   m.exchange_code,
                   m.exchange_symbol,
                   a.symbol AS asset_symbol,
                   lp.latest_trade_date
            FROM market_symbol_map m
            JOIN assets a ON a.id = m.asset_id
            LEFT JOIN (
              SELECT asset_id, MAX(trade_date) AS latest_trade_date
              FROM prices
              WHERE trade_date IS NOT NULL
              GROUP BY asset_id
            ) lp ON lp.asset_id = m.asset_id
            WHERE m.exchange_code IN ({",".join(f":ex{i}" for i in range(len(exchanges)))})
              AND m.is_active = TRUE
              AND a.asset_class IN ('STOCK', 'FUND')
            """
        ),
        params,
    ).mappings().all()
    for row in rows:
        if row["exchange_code"] not in counts:
            continue
        if asset_ids is not None and int(row["asset_id"]) not in asset_ids:
            continue
        _ex, sym = _resolved_exchange_symbol(row)
        if not sym:
            continue
        status, _age = _freshness_status(row["latest_trade_date"])
        counts[row["exchange_code"]][status] += 1
    return counts


def list_runs(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT id, provider, exchange_code, trade_date, status,
                   requested_symbols, received_rows, upserted_rows, missing_symbols,
                   started_at, finished_at, error_summary
            FROM market_data_runs
            ORDER BY started_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]
