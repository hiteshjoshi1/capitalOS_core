from __future__ import annotations

import base64
from dataclasses import dataclass
import logging
import hashlib

import base58
from eth_account import Account
from eth_account.messages import encode_defunct
from nacl.signing import VerifyKey

logger = logging.getLogger("capitalos.crypto.verify")

@dataclass
class VerificationResult:
    ok: bool
    error: str | None = None
    matched_variant: str | None = None
    decoder: str | None = None
    decoded_len: int | None = None


def _solana_candidates(raw_msg: bytes) -> list[tuple[str, bytes]]:
    prefixed_variants: list[tuple[str, bytes]] = []
    msg_variants: list[tuple[str, bytes]] = []

    msg_variants.append(("raw", raw_msg))
    msg_variants.append(("raw_rstrip_nl", raw_msg.rstrip(b"\n")))
    msg_variants.append(("raw_plus_nl", raw_msg + b"\n"))
    msg_variants.append(("raw_crlf", raw_msg.replace(b"\n", b"\r\n")))
    msg_variants.append(("raw_lf", raw_msg.replace(b"\r\n", b"\n")))
    msg_variants.append(("raw_null_suffix", raw_msg + b"\x00"))
    msg_variants.append(("raw_null_prefix", b"\x00" + raw_msg))
    msg_variants.append(("raw_double_null_suffix", raw_msg + b"\x00\x00"))

    # SIP-0001 standard prefix (capital S)
    prefixed_variants.append(
        ("sip_standard", b"\x18" + b"Solana Signed Message:" + b"\n" + str(len(raw_msg)).encode("utf-8") + raw_msg)
    )
    # Lowercase variant observed in some stacks
    prefixed_variants.append(
        ("sip_lower", b"\x18" + b"solana signed message:" + b"\n" + str(len(raw_msg)).encode("utf-8") + raw_msg)
    )
    # CRLF line endings (seen in some ledger stacks)
    prefixed_variants.append(
        ("sip_crlf", b"\x18" + b"Solana Signed Message:" + b"\r\n" + str(len(raw_msg)).encode("utf-8") + raw_msg)
    )
    prefixed_variants.append(
        ("sip_lower_crlf", b"\x18" + b"solana signed message:" + b"\r\n" + str(len(raw_msg)).encode("utf-8") + raw_msg)
    )
    # Prefix without length (legacy / non-standard)
    prefixed_variants.append(("sip_no_len", b"\x18" + b"Solana Signed Message:" + b"\n" + raw_msg))
    prefixed_variants.append(("sip_no_len_lower", b"\x18" + b"solana signed message:" + b"\n" + raw_msg))
    # Prefix without leading 0x18 (legacy)
    prefixed_variants.append(("sip_no_0x18", b"Solana Signed Message:" + b"\n" + str(len(raw_msg)).encode("utf-8") + raw_msg))
    prefixed_variants.append(("sip_no_0x18_lower", b"solana signed message:" + b"\n" + str(len(raw_msg)).encode("utf-8") + raw_msg))

    # Binary length encodings (some hardware wallets use fixed-width lengths)
    msg_len = len(raw_msg)
    le_u16 = msg_len.to_bytes(2, "little")
    le_u32 = msg_len.to_bytes(4, "little")
    be_u32 = msg_len.to_bytes(4, "big")
    prefixed_variants.append(("sip_len_le16", b"\x18" + b"Solana Signed Message:" + b"\n" + le_u16 + raw_msg))
    prefixed_variants.append(("sip_len_le32", b"\x18" + b"Solana Signed Message:" + b"\n" + le_u32 + raw_msg))
    prefixed_variants.append(("sip_len_be32", b"\x18" + b"Solana Signed Message:" + b"\n" + be_u32 + raw_msg))

    candidates: list[tuple[str, bytes]] = []
    candidates.extend(msg_variants)
    candidates.extend(prefixed_variants)

    # Some wallets (or transports) may sign a hash of the message bytes.
    for label, variant in msg_variants:
        candidates.append((f"{label}_sha256", hashlib.sha256(variant).digest()))
        candidates.append((f"{label}_sha512", hashlib.sha512(variant).digest()))
        candidates.append((f"{label}_sha256_sha256", hashlib.sha256(hashlib.sha256(variant).digest()).digest()))
    for label, variant in prefixed_variants:
        candidates.append((f"{label}_sha256", hashlib.sha256(variant).digest()))
        candidates.append((f"{label}_sha512", hashlib.sha512(variant).digest()))
        candidates.append((f"{label}_sha256_sha256", hashlib.sha256(hashlib.sha256(variant).digest()).digest()))

    return candidates


def verify_solana_signature_debug(message: str, signature: str, address: str) -> VerificationResult:
    try:
        signature = signature.strip()
        pubkey = base58.b58decode(address)
        base58_alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        if not signature or any(c not in base58_alphabet for c in signature):
            return VerificationResult(ok=False, error="Signature is not base58")
        sig_bytes = base58.b58decode(signature)
        if len(sig_bytes) != 64:
            return VerificationResult(ok=False, error="Decoded signature length is not 64", decoded_len=len(sig_bytes))
        raw_msg = message.encode("utf-8")
        for label, candidate in _solana_candidates(raw_msg):
            try:
                VerifyKey(pubkey).verify(candidate, sig_bytes)
                return VerificationResult(ok=True, matched_variant=label, decoder="base58", decoded_len=len(sig_bytes))
            except Exception:
                continue
        return VerificationResult(ok=False, error="No candidate matched", decoder="base58", decoded_len=len(sig_bytes))
    except Exception as exc:  # noqa: BLE001
        return VerificationResult(ok=False, error=str(exc))


def verify_solana_signature_bytes_debug(raw_msg: bytes, signature: str, address: str) -> VerificationResult:
    try:
        signature = signature.strip()
        pubkey = base58.b58decode(address)
        base58_alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        if not signature or any(c not in base58_alphabet for c in signature):
            return VerificationResult(ok=False, error="Signature is not base58")
        sig_bytes = base58.b58decode(signature)
        if len(sig_bytes) != 64:
            return VerificationResult(ok=False, error="Decoded signature length is not 64", decoded_len=len(sig_bytes))
        for label, candidate in _solana_candidates(raw_msg):
            try:
                VerifyKey(pubkey).verify(candidate, sig_bytes)
                return VerificationResult(ok=True, matched_variant=label, decoder="base58", decoded_len=len(sig_bytes))
            except Exception:
                continue
        return VerificationResult(ok=False, error="No candidate matched", decoder="base58", decoded_len=len(sig_bytes))
    except Exception as exc:  # noqa: BLE001
        return VerificationResult(ok=False, error=str(exc))


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
        signature = signature.strip()
        pubkey = base58.b58decode(address)
        last_error = None
        last_decoder = None
        last_decoded_len = None
        base58_alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        sig_len = len(signature)
        base58_only = bool(signature) and all(c in base58_alphabet for c in signature)
        msg_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
        raw_msg = message.encode("utf-8")
        candidates = _solana_candidates(raw_msg)

        for decoder in ("base64", "base64url", "base58", "hex", "json"):
            try:
                if decoder == "base64":
                    sig_bytes = base64.b64decode(signature)
                elif decoder == "base64url":
                    sig_bytes = base64.urlsafe_b64decode(signature + "===")
                elif decoder == "base58":
                    if any(c not in base58_alphabet for c in signature):
                        continue
                    sig_bytes = base58.b58decode(signature)
                    logger.info(
                        "solana_sig_decoded decoder=base58 decoded_len=%s hex_prefix=%s",
                        len(sig_bytes),
                        sig_bytes[:8].hex(),
                    )
                elif decoder == "json":
                    if signature.startswith("[") and signature.endswith("]"):
                        import json
                        arr = json.loads(signature)
                        if isinstance(arr, list) and all(isinstance(x, int) for x in arr):
                            sig_bytes = bytes(arr)
                        else:
                            continue
                    else:
                        continue
                else:
                    hex_sig = signature.removeprefix("0x")
                    if len(hex_sig) % 2 != 0:
                        continue
                    if any(c not in "0123456789abcdefABCDEF" for c in hex_sig):
                        continue
                    sig_bytes = bytes.fromhex(hex_sig)
                last_decoded_len = len(sig_bytes)
                if len(sig_bytes) != 64:
                    if decoder == "base58":
                        logger.info(
                            "solana_sig_bad_length decoder=%s sig_len=%s decoded_len=%s msg_hash=%s",
                            decoder,
                            len(signature),
                            len(sig_bytes),
                            msg_hash,
                        )
                    continue
                matched_label = None
                for label, candidate in candidates:
                    try:
                        VerifyKey(pubkey).verify(candidate, sig_bytes)
                        matched_label = label
                        break
                    except Exception:
                        continue
                if matched_label:
                    return VerificationResult(
                        ok=True,
                        matched_variant=matched_label,
                        decoder=decoder,
                        decoded_len=len(sig_bytes),
                    )
                last_error = "Signature was forged or corrupt"
                last_decoder = decoder
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                last_decoder = decoder
                logger.info(
                    "solana_sig_verify_failed",
                    extra={
                        "decoder": decoder,
                        "sig_len": len(signature),
                        "error": str(exc),
                        "msg_hash": msg_hash,
                    },
                )
                continue
        if last_error:
            return VerificationResult(
                ok=False,
                error=(
                    "Signature verification failed "
                    f"(decoder={last_decoder}, decoded_len={last_decoded_len}, error={last_error})"
                ),
                decoder=last_decoder,
                decoded_len=last_decoded_len,
            )
        return VerificationResult(
            ok=False,
            error=(
                "Invalid signature encoding "
                f"(sig_len={sig_len}, base58_only={base58_only})"
            ),
            decoded_len=last_decoded_len,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "solana_sig_exception",
            extra={
                "sig_len": len(signature),
                "error": str(exc),
            },
        )
        return VerificationResult(ok=False, error=str(exc))


def encode_message(message: str) -> str:
    return base64.b64encode(message.encode("utf-8")).decode("utf-8")
