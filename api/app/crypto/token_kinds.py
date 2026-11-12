"""What kind of token a wallet holding is, for display only (#408, U10, D-112).

- Stablecoins: tokens pegged to a fiat currency. A tag and a filter on the Crypto page; it
  doesn't change any total. The Cash page's stablecoin scope stays crypto.STABLECOIN_SYMBOLS
  (USDC/USDT, #149), which every stablecoin listed here would need a decision to join.
- Wrapped: a token that stands for another chain's coin (WBTC, cbBTC or a "BTC" on Ethereum
  is Bitcoin; WETH is ether). Liquid-staking tokens (stETH, wstETH) are not wrapped: they earn
  staking rewards (#330) and keep their own name.
"""

from __future__ import annotations

from typing import Optional

STABLECOINS = frozenset({"USDC", "USDT", "DAI", "USDS", "PYUSD", "FDUSD", "TUSD", "USDE", "USDP", "GUSD", "EURC", "EURS"})

# Symbol -> the coin it stands for.
WRAPPED = {
    "WBTC": "BTC",
    "CBBTC": "BTC",
    "TBTC": "BTC",
    "BTCB": "BTC",
    "WETH": "ETH",
    "WSOL": "SOL",
    "WBNB": "BNB",
    "WMATIC": "MATIC",
    "WPOL": "POL",
    "WAVAX": "AVAX",
}
# A coin listed as a token on another smart-contract chain is a wrapped copy of it (a "BTC" on
# Ethereum). An exchange balance (Coinbase) is the coin itself, held for the user: not wrapped.
NATIVE_CHAIN = {"BTC": "bitcoin", "SOL": "solana"}
CONTRACT_CHAINS = frozenset(
    {"ethereum", "base", "arbitrum", "optimism", "polygon", "bsc", "avalanche", "linea", "scroll", "zksync", "solana"}
)


def is_stablecoin(symbol: Optional[str]) -> bool:
    return (symbol or "").upper() in STABLECOINS


def wrapped_of(symbol: Optional[str], chain: Optional[str]) -> Optional[str]:
    """The coin a wrapped token stands for, else None."""
    sym = (symbol or "").upper()
    if sym in WRAPPED:
        return WRAPPED[sym]
    native = NATIVE_CHAIN.get(sym)
    on = (chain or "").lower()
    if native and on != native and on in CONTRACT_CHAINS:
        return sym
    return None
