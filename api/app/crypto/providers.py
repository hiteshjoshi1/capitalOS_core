from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from app.crypto.adapters import EvmAlchemyAdapter, NativeBalance, SolanaHeliusAdapter, TokenBalance
from app.crypto.http import json_request

logger = logging.getLogger("capitalos.crypto")


class CryptoHoldingsProvider(Protocol):
    provider_name: str
    supported_chains: set[str]

    def fetch_wallet_holdings(self, address: str, chain: str) -> tuple[NativeBalance, list[TokenBalance]]: ...


@dataclass
class ProviderFailure:
    provider: str
    chain: str
    error: str


_PACE_LOCKS: dict[str, threading.Lock] = {}
_LAST_CALL: dict[str, float] = {}


def _env_provider_key(provider: str) -> str:
    return provider.upper().replace("-", "_")


def _provider_timeout(provider: str) -> int:
    key = _env_provider_key(provider)
    return int(os.getenv(f"CRYPTO_{key}_TIMEOUT_SECONDS", os.getenv("CRYPTO_PROVIDER_TIMEOUT_SECONDS", "10")))


def _pace(provider: str) -> None:
    key = _env_provider_key(provider)
    interval = float(os.getenv(f"CRYPTO_{key}_MIN_INTERVAL_SECONDS", "0"))
    if interval <= 0:
        return
    lock = _PACE_LOCKS.setdefault(provider, threading.Lock())
    with lock:
        now = time.time()
        wait = interval - (now - _LAST_CALL.get(provider, 0.0))
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[provider] = time.time()


def _enabled(provider: str) -> bool:
    key = _env_provider_key(provider)
    raw = os.getenv(f"CRYPTO_{key}_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


class AlchemyHoldingsProvider:
    provider_name = "alchemy"
    supported_chains = set(EvmAlchemyAdapter.supported_chains())

    def fetch_wallet_holdings(self, address: str, chain: str) -> tuple[NativeBalance, list[TokenBalance]]:
        _pace(self.provider_name)
        adapter = EvmAlchemyAdapter(chain, timeout=_provider_timeout(self.provider_name))
        return adapter.get_native_balance(address), adapter.get_token_balances(address)


MORALIS_CHAIN_SLUG = {
    "ethereum": "eth",
    "base": "base",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "mantle": "mantle",
}


class MoralisHoldingsProvider:
    provider_name = "moralis"
    supported_chains = set(MORALIS_CHAIN_SLUG)

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("MORALIS_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("Missing MORALIS_API_KEY")

    def fetch_wallet_holdings(self, address: str, chain: str) -> tuple[NativeBalance, list[TokenBalance]]:
        slug = MORALIS_CHAIN_SLUG.get(chain)
        if not slug:
            raise ValueError(f"Moralis does not support EVM chain: {chain}")
        _pace(self.provider_name)
        timeout = _provider_timeout(self.provider_name)
        headers = {"X-API-Key": self.api_key}
        base_url = os.getenv("MORALIS_BASE_URL", "https://deep-index.moralis.io/api/v2.2").rstrip("/")
        native_payload = json_request(
            "GET",
            f"{base_url}/{address}/balance",
            headers=headers,
            params={"chain": slug},
            timeout=timeout,
        )
        native_raw = str(native_payload.get("balance") or "0")
        native_amount = int(native_raw) if native_raw.isdigit() else 0
        native = NativeBalance(
            symbol=EvmAlchemyAdapter.native_symbol(chain),
            decimals=18,
            raw_amount=str(native_amount),
            normalized_amount=native_amount / 10**18,
            price_source=self.provider_name,
        )

        token_payload = json_request(
            "GET",
            f"{base_url}/{address}/erc20",
            headers=headers,
            params={"chain": slug},
            timeout=timeout,
        )
        tokens: list[TokenBalance] = []
        payload_items = token_payload if isinstance(token_payload, list) else token_payload.get("result", [])
        for item in payload_items:
            contract = item.get("token_address") or item.get("contract_address")
            raw_balance = str(item.get("balance") or "0")
            if not contract or raw_balance in {"", "0"}:
                continue
            decimals = int(item.get("decimals")) if item.get("decimals") not in (None, "") else None
            raw_int = int(raw_balance) if raw_balance.isdigit() else 0
            normalized = raw_int / 10**decimals if decimals is not None else None
            price = item.get("usd_price")
            value = item.get("usd_value") or item.get("portfolio_percentage")
            tokens.append(
                TokenBalance(
                    contract_or_mint=str(contract).lower(),
                    symbol=item.get("symbol"),
                    name=item.get("name"),
                    decimals=decimals,
                    raw_amount=str(raw_int),
                    normalized_amount=normalized,
                    price_usd=float(price) if isinstance(price, (int, float)) else None,
                    value_usd=float(value) if isinstance(value, (int, float)) and item.get("usd_value") is not None else None,
                    price_source=self.provider_name if price is not None or value is not None else None,
                )
            )
        return native, tokens


class HeliusHoldingsProvider:
    provider_name = "helius"
    supported_chains = {"solana"}

    def fetch_wallet_holdings(self, address: str, chain: str) -> tuple[NativeBalance, list[TokenBalance]]:
        if chain != "solana":
            raise ValueError(f"Helius does not support chain: {chain}")
        _pace(self.provider_name)
        adapter = SolanaHeliusAdapter(timeout=_provider_timeout(self.provider_name))
        return adapter.get_native_balance(address), adapter.get_token_balances(address)


def configured_price_provider_order() -> list[str]:
    raw = os.getenv("CRYPTO_PRICE_PROVIDERS", "defillama,coingecko")
    providers = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return [provider for provider in providers if provider in {"defillama", "coingecko"}] or ["defillama", "coingecko"]


def _evm_provider_order() -> list[str]:
    raw = os.getenv("CRYPTO_EVM_HOLDINGS_PROVIDERS", "moralis,alchemy")
    providers = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return [provider for provider in providers if provider in {"moralis", "alchemy"}] or ["alchemy"]


def _evm_provider(provider: str) -> CryptoHoldingsProvider | None:
    if not _enabled(provider):
        return None
    if provider == "moralis":
        if not os.getenv("MORALIS_API_KEY", "").strip():
            return None
        return MoralisHoldingsProvider()
    if provider == "alchemy":
        return AlchemyHoldingsProvider()
    return None


def fetch_wallet_holdings(
    chain_type: str,
    chain: str,
    address: str,
) -> tuple[NativeBalance, list[TokenBalance], str]:
    if chain_type == "solana":
        provider = HeliusHoldingsProvider()
        native, tokens = provider.fetch_wallet_holdings(address, chain)
        return native, tokens, provider.provider_name
    if chain_type != "evm":
        raise ValueError(f"Unsupported chain_type: {chain_type}")

    failures: list[ProviderFailure] = []
    for provider_name in _evm_provider_order():
        provider = _evm_provider(provider_name)
        if provider is None or chain not in provider.supported_chains:
            continue
        try:
            native, tokens = provider.fetch_wallet_holdings(address, chain)
            return native, tokens, provider.provider_name
        except Exception as exc:  # noqa: BLE001
            failures.append(ProviderFailure(provider.provider_name, chain, str(exc)))
            logger.warning(
                "crypto_holdings_provider_failed",
                extra={
                    "provider": provider.provider_name,
                    "chain": chain,
                    "error_class": exc.__class__.__name__,
                    "error": str(exc),
                },
            )
    detail = "; ".join(f"{failure.provider}:{failure.chain}: {failure.error}" for failure in failures)
    raise RuntimeError(f"Crypto holdings providers failed for {chain}: {detail or 'no provider configured'}")
