from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import httpx

from app.crypto.http import request_with_retry
from app.market_data.generic import CorporateAction, CorporateActionType, GenericMarketDataProvider, MarketPrice


EodQuote = MarketPrice


class MarketDataProvider(Protocol):
    def provider_name(self) -> str:
        ...


def _normalize_hk_yahoo_symbol(symbol: str) -> str:
    upper = (symbol or "").strip().upper()
    if not upper.endswith(".HK"):
        return upper
    base = upper[:-3]
    if base.isdigit() and len(base) < 4:
        return f"{base.zfill(4)}.HK"
    return upper


class EODHDProvider(GenericMarketDataProvider):
    def __init__(self, api_key: str | None = None, timeout: int = 15):
        self.api_key = (api_key or os.getenv("EODHD_API_KEY", "")).strip()
        self.timeout = timeout
        self.base_url = os.getenv("EODHD_BASE_URL", "https://eodhd.com")

    def provider_name(self) -> str:
        return "eodhd"

    def fetch_prices(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        trade_date: date | None = None,
    ) -> dict[str, MarketPrice]:
        if not self.api_key:
            raise ValueError("Missing EODHD_API_KEY")
        if not symbols:
            return {}
        as_of = trade_date or datetime.now(tz=timezone.utc).date()
        lookback_days = int(os.getenv("EODHD_LOOKBACK_DAYS", "7"))
        from_date = as_of - timedelta(days=max(1, lookback_days))

        out: dict[str, EodQuote] = {}
        last_exc: Exception | None = None
        for symbol in symbols:
            try:
                url = f"{self.base_url}/api/eod/{symbol}"
                resp = request_with_retry(
                    "GET",
                    url,
                    params={
                        "api_token": self.api_key,
                        "fmt": "json",
                        "period": "d",
                        "from": from_date.isoformat(),
                        "to": as_of.isoformat(),
                        "order": "d",
                    },
                    timeout=self.timeout,
                    max_attempts=int(os.getenv("EODHD_MAX_ATTEMPTS", "2")),
                )
                resp.raise_for_status()
                payload = resp.json()
                row = None
                if isinstance(payload, list) and payload:
                    row = payload[-1]
                elif isinstance(payload, dict) and payload.get("date"):
                    row = payload
                if not row:
                    continue

                close = row.get("adjusted_close")
                if close is None:
                    close = row.get("close")
                if close is None:
                    continue

                trade_date_raw = row.get("date")
                resolved_trade_date = as_of
                if trade_date_raw:
                    try:
                        resolved_trade_date = datetime.fromisoformat(str(trade_date_raw)).date()
                    except ValueError:
                        resolved_trade_date = as_of

                currency = (row.get("currency") or "USD").upper()
                out[symbol.upper()] = MarketPrice(
                    provider=self.provider_name(),
                    symbol=symbol,
                    trade_date=resolved_trade_date,
                    close=float(close),
                    currency=currency,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        if not out and last_exc:
            raise last_exc
        return out

    def fetch_eod_single(self, symbols: list[str], *, trade_date: date | None = None) -> dict[str, EodQuote]:
        return self.fetch_prices(symbols, trade_date=trade_date)

    def fetch_eod_bulk(self, exchange_code: str, symbols: list[str]) -> dict[str, EodQuote]:
        if not self.api_key:
            raise ValueError("Missing EODHD_API_KEY")
        if not symbols:
            return {}
        url = f"{self.base_url}/api/eod-bulk-last-day/{exchange_code}"
        resp = request_with_retry(
            "GET",
            url,
            params={
                "api_token": self.api_key,
                "fmt": "json",
                "symbols": ",".join(symbols),
            },
            timeout=self.timeout,
            max_attempts=3,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            rows = data.get("data") or []
        else:
            rows = data or []

        out: dict[str, EodQuote] = {}
        for item in rows:
            code = (item.get("code") or item.get("symbol") or "").strip()
            if not code:
                continue
            close = item.get("adjusted_close")
            if close is None:
                close = item.get("close")
            if close is None:
                continue
            date_raw = item.get("date")
            trade_date: date
            if date_raw:
                try:
                    trade_date = datetime.fromisoformat(str(date_raw)).date()
                except ValueError:
                    trade_date = datetime.now(tz=timezone.utc).date()
            else:
                trade_date = datetime.now(tz=timezone.utc).date()
            currency = (item.get("currency") or "USD").upper()
            out[code.upper()] = MarketPrice(
                provider=self.provider_name(),
                symbol=code,
                trade_date=trade_date,
                close=float(close),
                currency=currency,
            )
        return out

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[CorporateAction]]:
        return {}


class FinnhubProvider(GenericMarketDataProvider):
    def __init__(self, api_key: str | None = None, timeout: int = 15):
        self.api_key = (api_key or os.getenv("FINNHUB_API_KEY", "")).strip()
        self.timeout = timeout
        self.base_url = os.getenv("FINNHUB_BASE_URL", "https://finnhub.io/api/v1")

    def provider_name(self) -> str:
        return "finnhub"

    def fetch_prices(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        trade_date: date | None = None,
    ) -> dict[str, MarketPrice]:
        if not self.api_key:
            raise ValueError("Missing FINNHUB_API_KEY")
        if not symbols:
            return {}

        out: dict[str, EodQuote] = {}
        sleep_ms = int(os.getenv("FINNHUB_SLEEP_MS", "150"))
        max_attempts = int(os.getenv("FINNHUB_MAX_ATTEMPTS", "2"))
        for idx, symbol in enumerate(symbols):
            resp = request_with_retry(
                "GET",
                f"{self.base_url}/quote",
                params={"symbol": symbol, "token": self.api_key},
                timeout=self.timeout,
                max_attempts=max_attempts,
            )
            resp.raise_for_status()
            item = resp.json() or {}
            price = item.get("c")
            if price is None or float(price) <= 0:
                if idx < len(symbols) - 1 and sleep_ms > 0:
                    time.sleep(sleep_ms / 1000.0)
                continue
            ts = item.get("t")
            if ts:
                trade_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            else:
                trade_date = datetime.now(tz=timezone.utc).date()

            out[symbol.upper()] = MarketPrice(
                provider=self.provider_name(),
                symbol=symbol,
                trade_date=trade_date,
                close=float(price),
                currency="USD",
            )
            if idx < len(symbols) - 1 and sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        return out

    def fetch_quotes(self, symbols: list[str]) -> dict[str, EodQuote]:
        return self.fetch_prices(symbols)

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[CorporateAction]]:
        return {}


class EODDataProvider(GenericMarketDataProvider):
    def __init__(self, api_key: str | None = None, timeout: int = 15):
        self.api_key = (api_key or os.getenv("EODDATA_API_KEY", "")).strip()
        self.timeout = timeout
        self.base_url = os.getenv("EODDATA_BASE_URL", "https://api.eoddata.com")

    def provider_name(self) -> str:
        return "eoddata"

    def fetch_prices(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        trade_date: date | None = None,
    ) -> dict[str, MarketPrice]:
        if not self.api_key:
            raise ValueError("Missing EODDATA_API_KEY")
        if not symbols:
            return {}
        if not exchange_code:
            raise ValueError("EODDataProvider requires exchange_code")

        out: dict[str, EodQuote] = {}
        max_attempts = int(os.getenv("EODDATA_MAX_ATTEMPTS", "1"))
        sleep_ms = int(os.getenv("EODDATA_SLEEP_MS", "6500"))
        last_exc: Exception | None = None
        for idx, symbol in enumerate(symbols):
            try:
                resp = request_with_retry(
                    "GET",
                    f"{self.base_url}/Quote/Get/{exchange_code}/{symbol}",
                    params={"ApiKey": self.api_key},
                    timeout=self.timeout,
                    max_attempts=max_attempts,
                )
                resp.raise_for_status()
                item = resp.json() or {}
                close = item.get("adjustedClose")
                if close is None:
                    close = item.get("close")
                if close is None:
                    if idx < len(symbols) - 1 and sleep_ms > 0:
                        time.sleep(sleep_ms / 1000.0)
                    continue

                date_raw = item.get("dateStamp")
                if date_raw:
                    try:
                        trade_date = datetime.fromisoformat(str(date_raw).split(" ")[0]).date()
                    except ValueError:
                        trade_date = datetime.now(tz=timezone.utc).date()
                else:
                    trade_date = datetime.now(tz=timezone.utc).date()
                currency = (item.get("currency") or "USD").upper()
                out[symbol.upper()] = MarketPrice(
                    provider=self.provider_name(),
                    symbol=symbol,
                    trade_date=trade_date,
                    close=float(close),
                    currency=currency,
                )
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                # Membership-level restrictions or not-found should not block later providers.
                code = int(exc.response.status_code) if exc.response is not None else 0
                if code in (401, 404, 429):
                    if code == 401:
                        break
                else:
                    continue
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            if idx < len(symbols) - 1 and sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        if not out and last_exc and not isinstance(last_exc, httpx.HTTPStatusError):
            raise last_exc
        return out

    def fetch_quotes(self, exchange_code: str, symbols: list[str]) -> dict[str, EodQuote]:
        return self.fetch_prices(symbols, exchange_code=exchange_code)

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[CorporateAction]]:
        return {}


class YahooProvider(GenericMarketDataProvider):
    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def provider_name(self) -> str:
        return "yahoo"

    def fetch_prices(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        trade_date: date | None = None,
    ) -> dict[str, MarketPrice]:
        if not symbols:
            return {}
        out: dict[str, MarketPrice] = {}
        batch_size = max(1, int(os.getenv("YAHOO_BATCH_SIZE", "1")))
        max_attempts = int(os.getenv("YAHOO_MAX_ATTEMPTS", "1"))
        sleep_ms = int(os.getenv("YAHOO_SLEEP_MS", "750"))
        last_exc: Exception | None = None
        for i in range(0, len(symbols), batch_size):
            chunk = [_normalize_hk_yahoo_symbol(symbol) for symbol in symbols[i : i + batch_size]]
            try:
                resp = request_with_retry(
                    "GET",
                    "https://query1.finance.yahoo.com/v7/finance/quote",
                    params={"symbols": ",".join(chunk)},
                    timeout=self.timeout,
                    max_attempts=max_attempts,
                )
                resp.raise_for_status()
                data = resp.json()
                rows = ((data or {}).get("quoteResponse") or {}).get("result") or []

                for item in rows:
                    symbol = (item.get("symbol") or "").strip()
                    if not symbol:
                        continue
                    price = item.get("regularMarketPrice")
                    if price is None:
                        continue
                    ts = item.get("regularMarketTime")
                    if ts:
                        resolved_trade_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
                    else:
                        resolved_trade_date = datetime.now(tz=timezone.utc).date()
                    currency = (item.get("currency") or "USD").upper()
                    out[symbol.upper()] = MarketPrice(
                        provider=self.provider_name(),
                        symbol=symbol,
                        trade_date=resolved_trade_date,
                        close=float(price),
                        currency=currency,
                    )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            if i + batch_size < len(symbols) and sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        if not out and last_exc:
            raise last_exc
        return out

    def fetch_quotes(self, symbols: list[str]) -> dict[str, EodQuote]:
        return self.fetch_prices(symbols)

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[CorporateAction]]:
        return {}


class YFinanceProvider(GenericMarketDataProvider):
    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def provider_name(self) -> str:
        return "yfinance"

    def _load_yfinance(self):
        try:
            import yfinance as yf  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Missing yfinance dependency; install yfinance in API environment") from exc
        return yf

    def _normalize_symbol(self, symbol: str, exchange_code: str | None) -> str:
        upper = (symbol or "").strip().upper()
        if exchange_code and exchange_code.upper() == "HKEX":
            return _normalize_hk_yahoo_symbol(upper)
        if upper.endswith(".HK"):
            return _normalize_hk_yahoo_symbol(upper)
        return upper

    def fetch_prices(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        trade_date: date | None = None,
    ) -> dict[str, MarketPrice]:
        if not symbols:
            return {}
        yf = self._load_yfinance()
        out: dict[str, MarketPrice] = {}
        last_exc: Exception | None = None
        sleep_ms = max(0, int(os.getenv("YFINANCE_SLEEP_MS", "250")))
        period = os.getenv("YFINANCE_PRICE_PERIOD", "1mo")

        for idx, original_symbol in enumerate(symbols):
            symbol = self._normalize_symbol(original_symbol, exchange_code)
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period=period)
                if hist is None or hist.empty:
                    continue
                last_row = hist.iloc[-1]
                close = last_row.get("Close")
                if close is None:
                    continue
                trade_date_idx = hist.index[-1]
                resolved_trade_date = trade_date_idx.date() if hasattr(trade_date_idx, "date") else datetime.now(tz=timezone.utc).date()

                currency = "USD"
                try:
                    fast_info = getattr(ticker, "fast_info", None) or {}
                    candidate = fast_info.get("currency")
                    if candidate:
                        currency = str(candidate).upper()
                except Exception:  # noqa: BLE001
                    pass

                out[original_symbol.strip().upper()] = MarketPrice(
                    provider=self.provider_name(),
                    symbol=symbol,
                    trade_date=resolved_trade_date,
                    close=float(close),
                    currency=currency,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            if idx < len(symbols) - 1 and sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

        if not out and last_exc:
            raise last_exc
        return out

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[CorporateAction]]:
        if not symbols:
            return {}
        yf = self._load_yfinance()
        out: dict[str, list[CorporateAction]] = {}
        sleep_ms = max(0, int(os.getenv("YFINANCE_SLEEP_MS", "250")))

        for idx, original_symbol in enumerate(symbols):
            key = original_symbol.strip().upper()
            symbol = self._normalize_symbol(original_symbol, exchange_code)
            actions: list[CorporateAction] = []
            try:
                ticker = yf.Ticker(symbol)
                table = ticker.actions
                if table is not None and not table.empty:
                    for ts, row in table.iterrows():
                        event_date = ts.date() if hasattr(ts, "date") else None
                        if event_date is None:
                            continue
                        if start_date and event_date < start_date:
                            continue
                        if end_date and event_date > end_date:
                            continue

                        dividend = row.get("Dividends")
                        if dividend is not None and float(dividend) > 0:
                            actions.append(
                                CorporateAction(
                                    provider=self.provider_name(),
                                    symbol=symbol,
                                    action_type=CorporateActionType.DIVIDEND,
                                    ex_date=event_date,
                                    value=float(dividend),
                                )
                            )
                        split = row.get("Stock Splits")
                        if split is not None and float(split) > 0:
                            actions.append(
                                CorporateAction(
                                    provider=self.provider_name(),
                                    symbol=symbol,
                                    action_type=CorporateActionType.SPLIT,
                                    ex_date=event_date,
                                    split_ratio=float(split),
                                )
                            )
            except Exception:  # noqa: BLE001
                pass
            out[key] = actions
            if idx < len(symbols) - 1 and sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        return out
