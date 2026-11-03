"""Synthetic FX for tests (#139). Never real rates, never a real provider."""
from __future__ import annotations

from datetime import timedelta

# Synthetic FX (#139): units of each currency per 1 EUR, the shape of ECB data.
# Realistic-looking and deliberately not 1.0, so a test that forgets to convert
# fails. 1 USD = 1.46 / 1.08 = 1.3519 SGD; 1 HKD = 0.1732 SGD; 1 INR = 0.0162 SGD.
SYNTHETIC_FX_PER_EUR = {
    "USD": 1.08,
    "SGD": 1.46,
    "GBP": 0.86,
    "HKD": 8.43,
    "INR": 90.1,
    "JPY": 162.0,
    "CNY": 7.8,
    "AUD": 1.64,
    "CHF": 0.95,
    "CAD": 1.47,
    "MYR": 5.1,
}


def synthetic_fx(quote: str, base: str = "SGD") -> float:
    """Value of 1 `quote` in `base` under the synthetic table."""
    per_eur = {"EUR": 1.0, **SYNTHETIC_FX_PER_EUR}
    return per_eur[base.upper()] / per_eur[quote.upper()]


def synthetic_frankfurter(start, end):
    # Every 7th day back from `end` (and `start`): enough for the 7-day lookback
    # on any date in the range without inserting a row per day.
    days = {start, end}
    day = end
    while day > start:
        days.add(day)
        day -= timedelta(days=7)
    return {d: dict(SYNTHETIC_FX_PER_EUR) for d in days}


# 1 USD in SGD under the synthetic table (~1.3519).
USD_SGD = synthetic_fx("USD")
