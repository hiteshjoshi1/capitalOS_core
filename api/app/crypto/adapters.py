from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Protocol, List

from app.crypto.http import json_request


@dataclass
class TokenBalance:
    contract_or_mint: str | None
    symbol: str | None
    name: str | None
    decimals: int | None
    raw_amount: str
    normalized_amount: float | None
    price_usd: float | None = None
    value_usd: float | None = None
    price_source: str | None = None


@dataclass
class NativeBalance:
    symbol: str
    decimals: int
    raw_amount: str
    normalized_amount: float | None
    price_usd: float | None = None
    value_usd: float | None = None
    price_source: str | None = None


class ChainAdapter(Protocol):
    def get_native_balance(self, address: str) -> NativeBalance: ...
    def get_token_balances(self, address: str) -> List[TokenBalance]: ...
    def get_prices(self, tokens: Iterable[TokenBalance]) -> dict[str, float]: ...


EVM_NATIVE = {
    "ethereum": "ETH",
    "base": "ETH",
    "arbitrum": "ETH",
    "optimism": "ETH",
    "mantle": "MNT",
    "scroll": "ETH",
}

ALCHEMY_CHAIN_SLUG = {
    "ethereum": "eth-mainnet",
    "base": "base-mainnet",
    "arbitrum": "arb-mainnet",
    "optimism": "opt-mainnet",
    "mantle": "mantle-mainnet",
    "scroll": "scroll-mainnet",
}


class EvmAlchemyAdapter:
    def __init__(self, chain: str, api_key: str | None = None, timeout: int = 10):
        self.chain = chain
        self.api_key = api_key or os.getenv("ALCHEMY_API_KEY", "")
        self.timeout = timeout
        slug = ALCHEMY_CHAIN_SLUG.get(chain)
        if not slug:
            raise ValueError(f"Unsupported EVM chain: {chain}")
        if not self.api_key:
            raise ValueError("Missing ALCHEMY_API_KEY")
        self.url = f"https://{slug}.g.alchemy.com/v2/{self.api_key}"

    def _rpc(self, method: str, params: list) -> dict:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data = json_request("POST", self.url, json=payload, timeout=self.timeout)
        if "error" in data:
            raise RuntimeError(data["error"])
        return data["result"]

    def get_native_balance(self, address: str) -> NativeBalance:
        raw = self._rpc("eth_getBalance", [address, "latest"])
        value = int(raw, 16)
        decimals = 18
        normalized = value / (10 ** decimals)
        return NativeBalance(
            symbol=EVM_NATIVE.get(self.chain, "ETH"),
            decimals=decimals,
            raw_amount=str(value),
            normalized_amount=normalized,
        )

    def get_token_balances(self, address: str) -> List[TokenBalance]:
        try:
            result = self._rpc("alchemy_getTokenBalances", [address])
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("capitalos.crypto").warning(
                "alchemy_token_balances_failed",
                extra={"address": address, "error": str(exc)},
            )
            return []
        balances = []
        for item in result.get("tokenBalances", []):
            contract = item.get("contractAddress")
            raw_balance = item.get("tokenBalance")
            if not contract or not raw_balance:
                continue
            if int(raw_balance, 16) == 0:
                continue
            meta = self._rpc("alchemy_getTokenMetadata", [contract])
            decimals = meta.get("decimals")
            symbol = meta.get("symbol")
            name = meta.get("name")
            value_int = int(raw_balance, 16)
            normalized = value_int / (10 ** decimals) if decimals else None
            balances.append(
                TokenBalance(
                    contract_or_mint=contract,
                    symbol=symbol,
                    name=name,
                    decimals=decimals,
                    raw_amount=str(value_int),
                    normalized_amount=normalized,
                )
            )
        return balances

    def get_prices(self, tokens: Iterable[TokenBalance]) -> dict[str, float]:
        return {}


class SolanaHeliusAdapter:
    def __init__(self, api_key: str | None = None, timeout: int = 10):
        self.api_key = api_key or os.getenv("HELIUS_API_KEY", "")
        if not self.api_key:
            raise ValueError("Missing HELIUS_API_KEY")
        self.timeout = timeout
        self._balances_cache: dict[str, dict] = {}

    def _get_balances(self, address: str) -> dict:
        if address in self._balances_cache:
            return self._balances_cache[address]
        url = f"https://api.helius.xyz/v1/wallet/{address}/balances"
        data = json_request(
            "GET",
            url,
            params={"api-key": self.api_key, "showZeroBalance": "false", "showNfts": "false"},
            timeout=self.timeout,
        )
        self._balances_cache[address] = data
        return data

    def get_native_balance(self, address: str) -> NativeBalance:
        data = self._get_balances(address)
        balances = data.get("balances", [])
        native = next((b for b in balances if b.get("symbol") == "SOL"), None)
        if native is None:
            native = next(
                (b for b in balances if b.get("mint") == "So11111111111111111111111111111111111111112"),
                None,
            )
        decimals = int(native.get("decimals", 9)) if native else 9
        balance = float(native.get("balance", 0)) if native else 0.0
        lamports = int(balance * (10 ** decimals))
        decimals = 9
        normalized = balance
        price = native.get("pricePerToken") if native else None
        value_usd = native.get("usdValue") if native else None
        return NativeBalance(
            symbol="SOL",
            decimals=decimals,
            raw_amount=str(lamports),
            normalized_amount=normalized,
            price_usd=price if isinstance(price, (int, float)) else None,
            value_usd=value_usd,
            price_source="helius" if value_usd is not None else None,
        )

    def get_token_balances(self, address: str) -> List[TokenBalance]:
        data = self._get_balances(address)
        balances = []
        for item in data.get("balances", []):
            symbol = item.get("symbol")
            if symbol == "SOL":
                continue
            balance = float(item.get("balance", 0) or 0)
            if balance == 0:
                continue
            decimals = item.get("decimals")
            mint = item.get("mint")
            name = item.get("name")
            normalized = balance
            price = item.get("pricePerToken")
            value_usd = item.get("usdValue")
            raw_amount = None
            if decimals is not None:
                try:
                    raw_amount = int(balance * (10 ** int(decimals)))
                except Exception:
                    raw_amount = None
            balances.append(
                TokenBalance(
                    contract_or_mint=mint,
                    symbol=symbol,
                    name=name,
                    decimals=decimals,
                    raw_amount=str(raw_amount if raw_amount is not None else balance),
                    normalized_amount=normalized,
                    price_usd=price,
                    value_usd=value_usd,
                    price_source="helius" if price or value_usd else None,
                )
            )
        return balances

    def get_prices(self, tokens: Iterable[TokenBalance]) -> dict[str, float]:
        return {}
