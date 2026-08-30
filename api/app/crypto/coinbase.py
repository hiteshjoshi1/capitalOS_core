from __future__ import annotations

import os
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crypto.ingest import SnapshotResult

ADVANCED_TRADE_ACCOUNTS_PATH = "/api/v3/brokerage/accounts"
DEFAULT_COINBASE_API_BASE = "https://api.coinbase.com"
FIAT_CURRENCIES = {
    "USD",
    "SGD",
    "EUR",
    "GBP",
    "AUD",
    "CAD",
    "CHF",
    "HKD",
    "INR",
    "JPY",
}
USD_STABLECOINS = {"USDC", "USDT", "DAI", "USDS"}


class CoinbaseConfigError(RuntimeError):
    pass


class CoinbaseApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoinbaseConfig:
    key_id: str
    key_secret: str
    api_base: str = DEFAULT_COINBASE_API_BASE


@dataclass(frozen=True)
class CoinbasePosition:
    account_uuid: str
    symbol: str
    name: str
    quantity: Decimal
    price_usd: Decimal | None
    value_usd: Decimal | None


def coinbase_configured() -> bool:
    return bool(_env("COINBASE_KEY_ID") and _env("COINBASE_KEY_SECRET"))


def load_config() -> CoinbaseConfig:
    key_id = _env("COINBASE_KEY_ID")
    key_secret = _env("COINBASE_KEY_SECRET")
    if not key_id or not key_secret:
        raise CoinbaseConfigError("COINBASE_KEY_ID and COINBASE_KEY_SECRET are required.")
    return CoinbaseConfig(
        key_id=key_id,
        key_secret=key_secret.replace("\\n", "\n"),
        api_base=_env("COINBASE_API_BASE") or DEFAULT_COINBASE_API_BASE,
    )


def coinbase_wallet_address(user_id: int) -> str:
    return f"coinbase:{user_id}:default"


def ensure_coinbase_wallet(db: Session, user_id: int) -> str:
    now = datetime.now(tz=timezone.utc)
    address = coinbase_wallet_address(user_id)
    existing = db.execute(
        text(
            """
            SELECT id
            FROM crypto_wallets
            WHERE chain_type = 'exchange' AND chain = 'coinbase' AND address = :address
            """
        ),
        {"address": address},
    ).fetchone()
    if existing:
        db.execute(
            text(
                """
                UPDATE crypto_wallets
                SET user_id = COALESCE(user_id, :user_id),
                    label = COALESCE(label, 'Coinbase'),
                    status = 'active'
                WHERE id = :id
                """
            ),
            {"id": existing[0], "user_id": user_id},
        )
        db.commit()
        return str(existing[0])

    wallet_id = str(uuid.uuid4())
    row = db.execute(
        text(
            """
            INSERT INTO crypto_wallets
              (id, user_id, chain_type, chain, address, label, status, created_at, verified_at)
            VALUES
              (:id, :user_id, 'exchange', 'coinbase', :address, 'Coinbase', 'active', :now, :now)
            RETURNING id
            """
        ),
        {"id": wallet_id, "user_id": user_id, "address": address, "now": now},
    ).fetchone()
    db.commit()
    return str(row[0])


class CoinbaseClient:
    def __init__(self, config: CoinbaseConfig | None = None) -> None:
        self.config = config or load_config()
        self._price_cache: dict[str, Decimal | None] = {}

    def list_accounts(self) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        cursor: str | None = None
        with httpx.Client(timeout=20) as client:
            while True:
                params: dict[str, Any] = {"limit": 250}
                if cursor:
                    params["cursor"] = cursor
                data = self._get_authenticated_json(
                    client,
                    ADVANCED_TRADE_ACCOUNTS_PATH,
                    params=params,
                )
                page_accounts = data.get("accounts") if isinstance(data, dict) else None
                if not isinstance(page_accounts, list):
                    raise CoinbaseApiError("Coinbase accounts response did not include accounts.")
                accounts.extend(account for account in page_accounts if isinstance(account, dict))
                if not data.get("has_next"):
                    break
                cursor = str(data.get("cursor") or "")
                if not cursor:
                    break
        return accounts

    def price_usd(self, symbol: str) -> Decimal | None:
        normalized = symbol.strip().upper()
        if not normalized:
            return None
        if normalized == "USD" or normalized in USD_STABLECOINS:
            return Decimal("1")
        if normalized in self._price_cache:
            return self._price_cache[normalized]
        path = f"/api/v3/brokerage/market/products/{normalized}-USD"
        url = f"{self.config.api_base.rstrip('/')}{path}"
        try:
            response = httpx.get(url, timeout=10)
            if response.status_code != 200:
                self._price_cache[normalized] = None
                return None
            price = _decimal((response.json() or {}).get("price"))
        except Exception:
            price = None
        self._price_cache[normalized] = price
        return price

    def _get_authenticated_json(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = build_jwt(self.config, "GET", path)
        response = client.get(
            f"{self.config.api_base.rstrip('/')}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code >= 400:
            raise CoinbaseApiError(f"Coinbase API returned {response.status_code}: {response.text[:500]}")
        data = response.json()
        if not isinstance(data, dict):
            raise CoinbaseApiError("Coinbase API response was not an object.")
        return data


def build_jwt(config: CoinbaseConfig, method: str, path: str) -> str:
    private_key_bytes = config.key_secret.encode("utf-8")
    try:
        private_key = serialization.load_pem_private_key(private_key_bytes, password=None)
    except Exception as exc:  # noqa: BLE001
        raise CoinbaseConfigError(
            "COINBASE_KEY_SECRET must be an ECDSA EC private key PEM. "
            "Use escaped newlines (\\n) if storing it on one line in .env."
        ) from exc

    now = int(time.time())
    host = urlparse(config.api_base).netloc or urlparse(DEFAULT_COINBASE_API_BASE).netloc
    uri = f"{method.upper()} {host}{path}"
    return jwt.encode(
        {
            "sub": config.key_id,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": config.key_id, "nonce": secrets.token_hex()},
    )


def fetch_coinbase_snapshot(
    *,
    client: CoinbaseClient | None = None,
    price_lookup: Callable[[str], Decimal | None] | None = None,
) -> SnapshotResult:
    active_client = client or CoinbaseClient()
    accounts = active_client.list_accounts()
    lookup = price_lookup or active_client.price_usd
    positions = parse_coinbase_accounts(accounts, lookup)
    return coinbase_snapshot_from_positions(positions)


def parse_coinbase_accounts(
    accounts: list[dict[str, Any]],
    price_lookup: Callable[[str], Decimal | None],
) -> list[CoinbasePosition]:
    positions: list[CoinbasePosition] = []
    for account in accounts:
        if not account.get("active", True):
            continue
        symbol = str(account.get("currency") or "").strip().upper()
        if not symbol or symbol in FIAT_CURRENCIES:
            continue
        quantity = _account_quantity(account)
        if quantity <= 0:
            continue
        price = price_lookup(symbol)
        value = quantity * price if price is not None else None
        positions.append(
            CoinbasePosition(
                account_uuid=str(account.get("uuid") or symbol),
                symbol=symbol,
                name=str(account.get("name") or f"{symbol} Wallet"),
                quantity=quantity,
                price_usd=price,
                value_usd=value,
            )
        )
    return positions


def coinbase_snapshot_from_positions(positions: list[CoinbasePosition]) -> SnapshotResult:
    total_usd = sum((position.value_usd or Decimal("0")) for position in positions)
    items = [
        {
            "asset_kind": "exchange_spot",
            "contract_or_mint": position.account_uuid,
            "symbol": position.symbol,
            "name": position.name,
            "decimals": None,
            "raw_amount": str(position.quantity),
            "normalized_amount": position.quantity,
            "price_usd": position.price_usd,
            "value_usd": position.value_usd,
            "price_source": "coinbase_public_product" if position.price_usd is not None else None,
            "chain": "coinbase",
        }
        for position in positions
    ]
    return SnapshotResult(
        total_usd=float(total_usd),
        items=items,
        source_versions={
            "balances_provider": "coinbase_advanced_trade",
            "pricing_provider": "coinbase_public_products",
        },
    )


def _account_quantity(account: dict[str, Any]) -> Decimal:
    available = _amount_value(account.get("available_balance"))
    hold = _amount_value(account.get("hold"))
    return available + hold


def _amount_value(raw: Any) -> Decimal:
    if isinstance(raw, dict):
        return _decimal(raw.get("value")) or Decimal("0")
    return _decimal(raw) or Decimal("0")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _env(name: str) -> str:
    return os.getenv(name, "").strip()
