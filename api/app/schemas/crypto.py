from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from app.schemas.fx import FxStatusFields


class StablecoinHolding(BaseModel):
    """One stablecoin holding: the same values as its row in /crypto/summary's top_holdings."""

    symbol: str
    chain: str
    amount: float
    value_usd: float
    value_base: float
    asset_class: str
    wallet_id: str
    wallet_label: Optional[str] = None
    holdings_as_of: Optional[str] = None
    price_as_of: Optional[str] = None


class StablecoinsResponse(FxStatusFields):
    """GET /crypto/stablecoins (#149): the stablecoin rows of /crypto/summary's
    top_holdings (same month, same anchor, same FX rate) and their total, for the
    Cash page, without the rest of the crypto summary."""

    month: str
    is_live: bool
    as_of: str
    base_currency: str
    # The symbols counted as stablecoins (cash-like), in display order.
    symbols: List[str]
    total_base: float
    holdings: List[StablecoinHolding]
