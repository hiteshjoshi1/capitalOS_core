from __future__ import annotations

import os
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.market_data.providers import EODDataProvider, EODHDProvider, FinnhubProvider, YahooProvider, YFinanceProvider, EodQuote


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


@dataclass
class SymbolMapRow:
    asset_id: int
    exchange_code: str
    exchange_symbol: str
    quote_currency: str
    eodhd_symbol: str
    finnhub_symbol: str
    yahoo_symbol: str



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
    return [p for p in chain if p in {"finnhub", "eodhd", "eoddata", "yahoo", "yfinance"}]



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
    if ex == "US" and "." in base and not base.endswith((".NS", ".SI", ".HK")):
        # Yahoo uses dashed class-share tickers for US equities (e.g. BRK-B).
        parts = base.split(".")
        if len(parts) == 2 and parts[0] and parts[1]:
            base = f"{parts[0]}-{parts[1]}"
    suffix = YAHOO_SUFFIX.get(ex, "")
    symbol = base
    if suffix and not symbol.endswith(suffix):
        symbol = f"{symbol}{suffix}"
    if ex == "HKEX" and symbol.endswith(".HK"):
        hk_base = symbol[:-3]
        if hk_base.isdigit() and len(hk_base) < 4:
            return f"{hk_base.zfill(4)}.HK"
    return symbol



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
        ex = str(row["exchange_code"]).strip().upper()
        mapped_symbol = str(row["exchange_symbol"] or "").strip().upper()
        asset_symbol = str(row.get("asset_symbol") or "").strip().upper()
        # US maps can drift to company-name-like symbols; prefer canonical asset symbol when present.
        asset_candidate = _ticker_candidate(asset_symbol)
        mapped_candidate = _ticker_candidate(mapped_symbol)
        sym = asset_candidate if ex == "US" and asset_candidate else mapped_candidate
        ex = str(row["exchange_code"]).strip().upper()
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
) -> None:
    db.execute(
        text(
            """
            INSERT INTO market_data_run_items
              (run_id, asset_id, provider, exchange_code, symbol, trade_date, status, price, currency, source_note, created_at)
            VALUES
              (:run_id, :asset_id, :provider, :exchange_code, :symbol, :trade_date, :status, :price, :currency, :source_note, :created_at)
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
        elif provider_name == "eoddata":
            symbol = row.exchange_symbol
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
            SELECT i.asset_id, i.provider, i.symbol, i.status, i.trade_date, i.source_note, i.created_at
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

    summary = {
        "active_symbols": len(symbols),
        "refreshed": 0,
        "failed": 0,
        "deferred": 0,
        "fresh": 0,
        "stale": 0,
        "missing": 0,
    }
    items: list[dict[str, Any]] = []
    for row in symbols:
        latest_price = latest_prices.get(row.asset_id, {})
        latest_item = latest_items.get(row.asset_id, {})
        freshness_status, age_days = _freshness_status(latest_price.get("trade_date"))
        summary[freshness_status] += 1

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

        if refresh_status in {"refreshed", "failed", "deferred"}:
            summary[refresh_status] += 1

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
                "attempt_status": attempt_status or None,
            }
        )

    items.sort(key=lambda item: ((item["refresh_status"] != "failed"), (item["freshness_status"] == "fresh"), item["symbol"]))
    return {
        "exchange_code": exchange_code,
        "latest_run": latest_run,
        "diagnostics_summary": summary,
        "symbols": items,
    }


def _fetch_quotes(
    provider_name: str,
    *,
    exchange_code: str,
    symbols: list[str],
    trade_date: date,
    eodhd: EODHDProvider,
    finnhub: FinnhubProvider,
    eoddata: EODDataProvider,
    yfinance: YFinanceProvider,
    yahoo: YahooProvider,
) -> dict[str, EodQuote]:
    if provider_name == "eodhd":
        return eodhd.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)
    if provider_name == "finnhub":
        return finnhub.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)
    if provider_name == "eoddata":
        return eoddata.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)
    if provider_name == "yfinance":
        return yfinance.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)
    return yahoo.fetch_prices(symbols, exchange_code=exchange_code, trade_date=trade_date)



def run_exchange_refresh(
    db: Session,
    exchange_code: str,
    *,
    trade_date: date | None = None,
    full_coverage: bool = False,
    batch_size: int | None = None,
    eodhd: EODHDProvider | None = None,
    finnhub: FinnhubProvider | None = None,
    eoddata: EODDataProvider | None = None,
    yfinance: YFinanceProvider | None = None,
    yahoo: YahooProvider | None = None,
) -> dict[str, Any]:
    exchange_code = exchange_code.upper()
    trade_date = trade_date or datetime.now(tz=timezone.utc).date()
    eodhd = eodhd or EODHDProvider()
    finnhub = finnhub or FinnhubProvider()
    eoddata = eoddata or EODDataProvider()
    yfinance = yfinance or YFinanceProvider()
    yahoo = yahoo or YahooProvider()

    backfilled_symbols = _backfill_symbol_map_for_exchange(db, exchange_code)
    daily_limit = _daily_limit()
    batch_size = batch_size or _refresh_batch_size()
    all_symbols = _load_symbols(db, exchange_code, daily_limit=0)
    symbols = all_symbols if full_coverage else all_symbols[:daily_limit]
    deferred_symbols = all_symbols[len(symbols) :] if not full_coverage else []
    if not symbols:
        diagnostics = _exchange_diagnostics(
            db,
            exchange_code,
            attempted_asset_ids=set(),
            deferred_asset_ids={row.asset_id for row in deferred_symbols},
        )
        return {
            "exchange_code": exchange_code,
            "trade_date": trade_date.isoformat(),
            "requested_symbols": 0,
            "total_active_symbols": len(all_symbols),
            "upserted_rows": 0,
            "dividend_rows_upserted": 0,
            "missing_symbols": 0,
            "backfilled_symbols": backfilled_symbols,
            "status": "partial" if deferred_symbols else "success",
            "providers": [],
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
                        eoddata=eoddata,
                        yfinance=yfinance,
                        yahoo=yahoo,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                provider_error = str(exc)

        upserted_rows = 0
        invalid_rows = 0
        next_unresolved: list[SymbolMapRow] = []
        for provider_symbol, mapped_rows in by_symbol.items():
            for row in mapped_rows:
                attempted_asset_ids.add(row.asset_id)
            quote = quotes.get(provider_symbol.upper())
            if quote is None:
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
                        source_note=provider_error,
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
        "status": "success" if (not unresolved and total_invalid == 0 and not deferred_symbols) else "partial",
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



def latest_status_by_exchange(db: Session) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for exchange_code in configured_exchanges():
        diagnostics = _exchange_diagnostics(db, exchange_code)
        latest_run = diagnostics.pop("latest_run", None) or {}
        payload.append(
            {
                **latest_run,
                "exchange_code": exchange_code,
                **diagnostics,
            }
        )
    return payload



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
