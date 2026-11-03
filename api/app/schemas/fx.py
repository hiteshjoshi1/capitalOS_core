from __future__ import annotations

from typing import List

from pydantic import BaseModel


class FxStatusFields(BaseModel):
    """Additive FX fields (#139) on responses that show base-currency totals.

    fx_incomplete: some value had no FX rate at all and is left out of the totals
    (never counted 1:1). fx_stale_currencies: converted with a stored rate older
    than the lookback window (providers unreachable for a while)."""

    fx_incomplete: bool = False
    fx_missing_currencies: List[str] = []
    fx_stale_currencies: List[str] = []
