from __future__ import annotations

import base64
from dataclasses import dataclass

import base58
from eth_account import Account
from eth_account.messages import encode_defunct
from nacl.signing import VerifyKey


@dataclass
class VerificationResult:
    ok: bool
    error: str | None = None


def verify_evm_signature(message: str, signature: str, address: str) -> VerificationResult:
    try:
        msg = encode_defunct(text=message)
        recovered = Account.recover_message(msg, signature=signature)
        if recovered.lower() != address.lower():
            return VerificationResult(ok=False, error="Signature does not match address")
        return VerificationResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        return VerificationResult(ok=False, error=str(exc))


def verify_solana_signature(message: str, signature: str, address: str) -> VerificationResult:
    try:
        pubkey = base58.b58decode(address)
        sig_bytes = base58.b58decode(signature)
        VerifyKey(pubkey).verify(message.encode("utf-8"), sig_bytes)
        return VerificationResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        return VerificationResult(ok=False, error=str(exc))


def encode_message(message: str) -> str:
    return base64.b64encode(message.encode("utf-8")).decode("utf-8")
