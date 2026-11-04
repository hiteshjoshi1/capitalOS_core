"""FX for valuation (D-30): every valuation module gets its rates here, from
``app.fx`` (stored rates, a missing rate flagged and never 1.0). Tests replace
``app.valuation.fx.get_rates`` to fix the rates of a valuation."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.fx import fx_status, get_rates, get_rates_by_date, rate_date

__all__ = ["fx_status", "get_rates", "get_rates_by_date", "rate_date", "_cashflow_rate_date"]


def _cashflow_rate_date(value: Any) -> date:
    """A transaction's FX date: its UTC date (naive timestamps are UTC)."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        value = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return rate_date(value)


