"""Source freshness (#252, D-67): /dashboard/source-freshness."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SourceFreshnessRow(BaseModel):
    """One data source. ``kind``: ibkr_flex, broker_statement, bank_statement,
    card_statement, account_statement, crypto_wallet, market_data or fx.
    ``status``: on_time, overdue, never_loaded (no data at all; counts as
    overdue) or no_schedule (cadence off). ``due_date``: the last day the newest
    data is on time. ``days_overdue``: days since then (None unless overdue with
    data)."""

    source_key: str
    kind: str
    label: str
    platform: Optional[str] = None
    last_data_date: Optional[str] = None
    cadence: str
    grace_days: int
    default_cadence: str
    default_grace_days: int
    overridden: bool
    due_date: Optional[str] = None
    status: str
    overdue: bool
    days_overdue: Optional[int] = None


class SourceFreshnessResponse(BaseModel):
    as_of: str = Field(..., description="Today (the user's timezone), ISO date")
    overdue_count: int
    cadences: List[str]
    sources: List[SourceFreshnessRow]


class SourceFreshnessOverrideIn(BaseModel):
    cadence: str = Field(..., description="daily, weekdays, weekly, monthly, quarterly or off")
    grace_days: int = Field(..., ge=0, le=90)
