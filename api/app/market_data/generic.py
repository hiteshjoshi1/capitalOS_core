from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Protocol


@dataclass
class MarketPrice:
    provider: str
    symbol: str
    trade_date: date
    close: float
    currency: str


class CorporateActionType(str, Enum):
    DIVIDEND = "dividend"
    SPLIT = "split"
    OTHER = "other"


@dataclass
class CorporateAction:
    provider: str
    symbol: str
    action_type: CorporateActionType
    ex_date: date
    value: float | None = None
    currency: str | None = None
    pay_date: date | None = None
    record_date: date | None = None
    split_ratio: float | None = None


class GenericMarketDataProvider(Protocol):
    def provider_name(self) -> str:
        ...

    def fetch_prices(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        trade_date: date | None = None,
    ) -> dict[str, MarketPrice]:
        ...

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        *,
        exchange_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[CorporateAction]]:
        ...
