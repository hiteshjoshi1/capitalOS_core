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


# --- #361: response models for the crypto GET routes (same JSON as before) ---

from app.schemas.common import IsoDateTime, WalletId  # noqa: E402


class CryptoWalletOut(BaseModel):
    """GET /crypto/wallets: one of the caller's wallets."""

    id: WalletId
    chain_type: str
    chain: str
    address: str
    label: Optional[str] = None
    status: str
    created_at: Optional[IsoDateTime] = None
    verified_at: Optional[IsoDateTime] = None


class TokenVisibilityFields(BaseModel):
    """Spam/unknown-token fields (#342) on each token and holding row."""

    contract_or_mint: Optional[str] = None
    token_key: Optional[str] = None
    unknown_token: bool = False
    visibility_override: Optional[str] = None
    hidden: bool = False
    hidden_reason: Optional[str] = None


class CryptoMonthChange(BaseModel):
    """One token's change since the compare month-end (#408, U9), in the base currency, split
    as Overview's bridge splits it (D-60): abs = price_effect + quantity_effect + fx_effect + unsplit."""

    abs: float
    pct: Optional[float] = None
    price_effect: float = 0.0
    quantity_effect: float = 0.0
    fx_effect: float = 0.0
    unsplit: float = 0.0
    compare_value: float = 0.0
    end_value: float = 0.0
    compare_month: Optional[str] = None
    baseline_missing: bool = False
    # held | new (not held at the compare month-end)
    side: str = "held"
    start_quantity: Optional[float] = None
    end_quantity: Optional[float] = None
    start_price: Optional[float] = None
    end_price: Optional[float] = None
    price_currency: Optional[str] = "USD"
    start_rate: Optional[float] = None
    end_rate: Optional[float] = None


class CryptoHoldingOut(TokenVisibilityFields):
    """A row of /crypto/summary's top_holdings / top5_holdings."""

    symbol: Optional[str] = None
    chain: Optional[str] = None
    amount: float
    value_usd: float
    value_base: float
    asset_class: str
    wallet_id: WalletId
    wallet_label: Optional[str] = None
    wallet_address: Optional[str] = None
    price_usd: Optional[float] = None
    price_change_usd: Optional[float] = None
    price_change_pct: Optional[float] = None
    value_change_base: Optional[float] = None
    value_change_pct: Optional[float] = None
    snapshot_value_base: Optional[float] = None
    snapshot_delta_base: Optional[float] = None
    snapshot_delta_pct: Optional[float] = None
    holdings_as_of: Optional[str] = None
    price_as_of: Optional[str] = None
    holdings_provider: Optional[str] = None
    price_provider: Optional[str] = None
    # #408 (U10, D-112): display tags. A stablecoin (fiat-pegged) and the coin a wrapped
    # token stands for (WBTC -> BTC). Neither changes a total.
    is_stablecoin: bool = False
    wrapped_of: Optional[str] = None
    # #408 (U9): the change vs the compare month-end split as the bridge splits it (D-60):
    # price + quantity + FX + unsplit = abs (= value_change_base). Quantity is a buy, sell,
    # transfer or staking reward, never a gain or loss.
    month_change: Optional[CryptoMonthChange] = None


class CryptoWalletExposureOut(BaseModel):
    wallet_id: WalletId
    label: Optional[str] = None
    address: Optional[str] = None
    chain_type: Optional[str] = None
    chain: Optional[str] = None
    total_usd: float
    total_base: float
    percent: float
    holdings_as_of: Optional[str] = None
    price_as_of: Optional[str] = None
    holdings_provider: Optional[str] = None
    price_provider: Optional[str] = None
    stale_holdings: bool = False
    stale_prices: bool = False


class CryptoChainExposureOut(BaseModel):
    chain: str
    total_usd: float
    total_base: float
    percent: float


class CryptoWalletChainExposureOut(BaseModel):
    wallet_id: WalletId
    chain: str
    total_usd: float
    total_base: float


class CryptoTrendPoint(BaseModel):
    month: str
    value: Optional[float] = None
    is_live: bool


class CryptoCoinBalance(BaseModel):
    balance: float
    value_usd: float
    value_base: float


class CryptoSummaryResponse(FxStatusFields):
    """GET /crypto/summary."""

    month: str
    is_live: bool
    compare_month: str
    as_of: str
    snapshot_day: int
    snapshot_as_of: Optional[str] = None
    total_crypto_usd: float
    total_crypto_base: float
    snapshot_total_base: Optional[float] = None
    snapshot_total_usd: Optional[float] = None
    snapshot_delta_base: Optional[float] = None
    snapshot_delta_pct: Optional[float] = None
    snapshot_missing: bool
    snapshot_missing_reason: Optional[str] = None
    base_currency: str
    eth_exposure_usd: float
    eth_exposure_base: float
    token_exposure_usd: float
    token_exposure_base: float
    token_count: int
    priced_token_count: int
    trend: List[CryptoTrendPoint]
    eth: CryptoCoinBalance
    sol: CryptoCoinBalance
    top5_holdings: List[CryptoHoldingOut]
    hidden_token_count: int
    top_holdings: List[CryptoHoldingOut]
    wallet_exposure: List[CryptoWalletExposureOut]
    chain_exposure: List[CryptoChainExposureOut]
    wallet_chain_exposure: List[CryptoWalletChainExposureOut]
    last_refreshed_at: Optional[str] = None
    holdings_as_of: Optional[str] = None
    price_as_of: Optional[str] = None
    stale_holdings: bool
    stale_prices: bool
    is_stale: bool
    refresh_triggered: bool


class CryptoTokenOut(TokenVisibilityFields):
    """A token row of GET /crypto/tokens: the newest snapshot item per wallet."""

    wallet_id: WalletId
    address: Optional[str] = None
    label: Optional[str] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    chain: Optional[str] = None
    chain_type: Optional[str] = None
    normalized_amount: Optional[float] = None
    price_usd: Optional[float] = None
    value_usd: Optional[float] = None
    price_source: Optional[str] = None


class CryptoTokensResponse(BaseModel):
    total: int
    tokens: List[CryptoTokenOut]
    hidden_count: int


class TokenVisibilityOverride(BaseModel):
    chain: str
    contract_or_mint: str
    visibility: Optional[str] = None


class TokenVisibilityResponse(BaseModel):
    """GET (and PUT) /crypto/token-visibility (#342)."""

    overrides: List[TokenVisibilityOverride]


class CryptoAllowlistOut(BaseModel):
    id: int
    chain: str
    contract_address: str
    symbol: Optional[str] = None
    name: Optional[str] = None
    created_at: Optional[IsoDateTime] = None


class SolanaBlockhashOut(BaseModel):
    blockhash: str


class PriceBackfillRequest(BaseModel):
    date: str
    coins: int


class PriceBackfillPlanOut(BaseModel):
    """GET /crypto/price-backfill-plan (#331)."""

    requests: List[PriceBackfillRequest]
    remaining_requests: int
    items: int
    skipped_unknown_tokens: int
