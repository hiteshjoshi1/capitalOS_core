"""Money in valuation is Decimal (#360, D-106).

Amounts, quantities, prices and FX rates are ``Decimal`` from the database read
(``app.portfolio.canonical_reads`` casts to NUMERIC, never DOUBLE PRECISION) through
every sum and product in ``app.valuation``. They become floats only at the edge:
a router or service that hands a valuation result to the API (or stores it as JSON)
passes it through ``floats()`` first, so the response JSON is the same numbers as
before, without the cent-level drift of adding floats.

``D()`` takes whatever a driver or a caller gives (Postgres NUMERIC is already
Decimal; SQLite in tests gives int/float; FX rates and live prices are floats) and
turns a float into the Decimal of its shortest repr (``Decimal(str(x))``), so 0.1
stays 0.1 and not 0.1000000000000000055511151231257827.
"""
from __future__ import annotations

from decimal import Decimal
from functools import wraps
from typing import Any, Callable, Iterable, TypeVar

ZERO = Decimal(0)
ONE = Decimal(1)

T = TypeVar("T")


def D(value: Any, default: Decimal = ZERO) -> Decimal:
    """``value`` as Decimal; None (and anything not a number) is ``default``."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            return default
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return Decimal(text)
        except Exception:  # noqa: BLE001
            return default
    return default


def D_or_none(value: Any) -> Decimal | None:
    """Like ``D`` but keeps a missing value missing."""
    return None if value is None else D(value)


def dsum(values: Iterable[Any]) -> Decimal:
    """The exact sum of ``values`` (each through ``D``)."""
    total = ZERO
    for value in values:
        total += D(value)
    return total


def floats(value: T) -> T:
    """``value`` with every Decimal (in nested dicts, lists and tuples) as a float:
    the edge where a valuation result leaves for the API or JSON storage."""
    if isinstance(value, Decimal):
        return float(value)  # type: ignore[return-value]
    if isinstance(value, dict):
        return {k: floats(v) for k, v in value.items()}  # type: ignore[return-value]
    if isinstance(value, list):
        return [floats(v) for v in value]  # type: ignore[return-value]
    if isinstance(value, tuple):
        return tuple(floats(v) for v in value)  # type: ignore[return-value]
    return value


def float_edge(fn: Callable[..., T]) -> Callable[..., T]:
    """Decorator for a function whose result leaves valuation: Decimals become floats."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return floats(fn(*args, **kwargs))

    return wrapper
