"""Response models for the market-data GET routes (#361), same JSON as before."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import IsoDateTime


class MarketDataRunOut(BaseModel):
    """A market_data_runs row."""

    id: int
    provider: Optional[str] = None
    exchange_code: Optional[str] = None
    trade_date: Optional[date] = None
    status: Optional[str] = None
    requested_symbols: int = 0
    received_rows: int = 0
    upserted_rows: int = 0
    missing_symbols: int = 0
    started_at: Optional[IsoDateTime] = None
    finished_at: Optional[IsoDateTime] = None
    error_summary: Optional[str] = None


class MarketDataRunsResponse(BaseModel):
    runs: List[MarketDataRunOut]


class MarketDataDiagnosticsSummary(BaseModel):
    active_symbols: int
    refreshed: int
    failed: int
    deferred: int
    fresh: int
    stale: int
    missing: int


class MarketDataSymbolStatus(BaseModel):
    asset_id: int
    symbol: Optional[str] = None
    mapped_symbol: Optional[str] = None
    provider_symbol: Optional[str] = None
    provider: Optional[str] = None
    source: Optional[str] = None
    currency: Optional[str] = None
    latest_price: Optional[float] = None
    latest_trade_date: Optional[str] = None
    age_days: Optional[int] = None
    freshness_status: str
    refresh_status: Optional[str] = None
    failure_reason: Optional[str] = None
    reason_code: Optional[str] = None
    attempt_status: Optional[str] = None


class MarketDataExchangeStatus(BaseModel):
    """One exchange: its latest run's fields (absent when it has never run), then its symbols."""

    # The latest run's row (every field optional: an exchange may not have run yet).
    id: Optional[int] = None
    provider: Optional[str] = None
    trade_date: Optional[date] = None
    status: Optional[str] = None
    requested_symbols: Optional[int] = None
    received_rows: Optional[int] = None
    upserted_rows: Optional[int] = None
    missing_symbols: Optional[int] = None
    started_at: Optional[IsoDateTime] = None
    finished_at: Optional[IsoDateTime] = None
    error_summary: Optional[str] = None
    exchange_code: str
    diagnostics_summary: MarketDataDiagnosticsSummary
    symbols: List[MarketDataSymbolStatus]


class MarketDataStatusResponse(BaseModel):
    status: List[MarketDataExchangeStatus]


class UnpricedHolding(BaseModel):
    instrument_id: int
    asset_id: Optional[int] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    currency: Optional[str] = None
    exchange_code: Optional[str] = None
    platform: Optional[str] = None
    reason: str
    suggested_yahoo_symbols: List[str]


class UnpricedResponse(BaseModel):
    """GET /market-data/unpriced (#320)."""

    items: List[UnpricedHolding]
    can_fix: bool
