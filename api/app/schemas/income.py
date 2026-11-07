"""Income (#267): /income/summary."""
from __future__ import annotations

from typing import List, Optional

from app.schemas.fx import FxStatusFields
from pydantic import BaseModel, Field


class IncomeWindowOut(BaseModel):
    """Dividends (net of withholding) plus interest over [from_date, to_date], both inclusive."""

    from_date: str
    to_date: str
    dividends: float
    interest: float
    total: float


class IncomeMonthOut(BaseModel):
    month: str
    dividends: float
    interest: float
    total: float


class IncomeSummaryOut(FxStatusFields):
    month: str
    base_currency: str
    as_of: str = Field(..., description="Last day counted: the month's last day, or today for the current month")
    partial_month: bool
    trailing_12: IncomeWindowOut
    prior_12: IncomeWindowOut
    trailing_12_change_pct: Optional[float] = Field(None, description="Fraction; null when the prior 12 months had none")
    ytd: IncomeWindowOut
    prior_ytd: IncomeWindowOut = Field(..., description="The same dates one year earlier")
    ytd_change_pct: Optional[float] = None
    months: List[IncomeMonthOut] = Field(..., description="The 12 months ending at `month`, oldest first")
