from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHash, VerifyMismatchError
except ImportError:  # pragma: no cover - exercised only when argon2 is unavailable
    PasswordHasher = None
    InvalidHash = ValueError
    VerifyMismatchError = ValueError


_PH = PasswordHasher() if PasswordHasher is not None else None
_PBKDF2_ITERATIONS = 260_000


def _pbkdf2_hash(password: str, *, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _pbkdf2_verify(password: str, encoded: str) -> bool:
    try:
        _algo, iter_raw, salt_hex, digest_hex = encoded.split("$", 3)
        iterations = int(iter_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(computed, expected)


def hash_password(password: str) -> str:
    if _PH is not None:
        return _PH.hash(password)
    return _pbkdf2_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        return _pbkdf2_verify(password, password_hash)
    if _PH is None:
        return False
    try:
        return _PH.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def _jwt_secret() -> str:
    secret = os.getenv("AUTH_ACCESS_TOKEN_SECRET", "").strip()
    if secret:
        return secret
    return "capitalos-dev-insecure-secret"


def access_token_ttl_seconds() -> int:
    minutes = int(os.getenv("AUTH_ACCESS_TOKEN_TTL_MINUTES", "15"))
    return max(minutes, 1) * 60


def refresh_token_ttl_seconds() -> int:
    days = int(os.getenv("AUTH_REFRESH_TOKEN_TTL_DAYS", "30"))
    return max(days, 1) * 24 * 3600


def refresh_cookie_name() -> str:
    return os.getenv("AUTH_REFRESH_COOKIE_NAME", "capitalos_refresh")


def create_access_token(*, user_id: int, username: str) -> tuple[str, datetime]:
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(seconds=access_token_ttl_seconds())
    token = jwt.encode(
        {
            "sub": str(user_id),
            "username": username,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "type": "access",
        },
        _jwt_secret(),
        algorithm=os.getenv("AUTH_ACCESS_TOKEN_ALG", "HS256"),
    )
    return token, exp


def decode_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[os.getenv("AUTH_ACCESS_TOKEN_ALG", "HS256")],
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Invalid token type")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
