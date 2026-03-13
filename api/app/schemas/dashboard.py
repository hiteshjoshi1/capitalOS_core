from pydantic import BaseModel


class PlatformAllocationItem(BaseModel):
    platform: str
    platform_type: str | None = None
    country: str | None = None
    value: float
    percent: float


class PlatformAllocationOut(BaseModel):
    as_of: str | None = None
    total: float
    items: list[PlatformAllocationItem]


class CashDepositsItem(BaseModel):
    source: str
    value: float
    percent: float


class CashDepositsOut(BaseModel):
    total: float
    items: list[CashDepositsItem]


class StockExposureItem(BaseModel):
    key: str
    value: float
    percent: float


class StockExposureOut(BaseModel):
    as_of: str | None = None
    base_currency: str
    total: float
    by_country: list[StockExposureItem]
    by_platform: list[StockExposureItem]
