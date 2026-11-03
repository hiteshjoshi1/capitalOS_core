from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.auth import decode_access_token

logger = logging.getLogger("capitalos.auth")


@dataclass
class CurrentUser:
    id: int
    username: str
    is_admin: bool = False


def allow_legacy_null_ownership() -> bool:
    raw = os.getenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def account_scope_sql(alias: str = "a") -> str:
    if allow_legacy_null_ownership():
        return f"({alias}.user_id = :current_user_id OR {alias}.user_id IS NULL)"
    return f"{alias}.user_id = :current_user_id"


# AUTH_BYPASS_USER_ID skips login and makes every request (HTTP and WebSocket)
# run as that user, with admin rights. It exists for the backend test suite only,
# so it is honoured only next to AUTH_BYPASS_ALLOW=test; set without it, the API
# refuses to start (#153).
AUTH_BYPASS_ALLOW_VALUE = "test"


class AuthBypassConfigError(RuntimeError):
    """AUTH_BYPASS_USER_ID is set where it must not be."""


def _bypass_allowed() -> bool:
    return os.getenv("AUTH_BYPASS_ALLOW", "").strip().lower() == AUTH_BYPASS_ALLOW_VALUE


def check_auth_bypass_config() -> int | None:
    """Validate the bypass settings at startup. Returns the bypass user id when
    the bypass is active (and logs a loud warning), None when it is off. Raises
    AuthBypassConfigError when AUTH_BYPASS_USER_ID is set without
    AUTH_BYPASS_ALLOW=test or is not an integer."""
    raw = os.getenv("AUTH_BYPASS_USER_ID", "").strip()
    if not raw:
        return None
    if not _bypass_allowed():
        raise AuthBypassConfigError(
            "AUTH_BYPASS_USER_ID is set, which would skip login and run every request as that "
            "user with admin rights. It is for the test suite only: unset it (check .env and "
            "the compose environment), or also set AUTH_BYPASS_ALLOW=test if this really is a test run."
        )
    try:
        user_id = int(raw)
    except ValueError as exc:
        raise AuthBypassConfigError(f"AUTH_BYPASS_USER_ID={raw!r} is not an integer user id.") from exc
    logger.warning(
        "AUTH BYPASS ACTIVE: login is disabled and every request runs as user %s with admin "
        "rights (AUTH_BYPASS_USER_ID + AUTH_BYPASS_ALLOW=test). Never run this way with real data.",
        user_id,
        extra={"event": "auth_bypass_active", "user_id": user_id},
    )
    return user_id


def _bypass_current_user() -> CurrentUser | None:
    bypass = os.getenv("AUTH_BYPASS_USER_ID", "").strip()
    # Without the explicit test flag the bypass is ignored (fail closed: normal login
    # applies); startup has already refused to run with this configuration.
    if not bypass or not _bypass_allowed():
        return None
    try:
        user_id = int(bypass)
    except ValueError as exc:  # pragma: no cover - rejected at startup
        raise HTTPException(status_code=500, detail="Invalid AUTH_BYPASS_USER_ID") from exc
    return CurrentUser(id=user_id, username=f"bypass-{user_id}", is_admin=True)


def _load_current_user(db: Session, user_id: int) -> CurrentUser:
    row = db.execute(
        text(
            """
            SELECT id, username, COALESCE(is_admin, FALSE) AS is_admin, COALESCE(is_active, TRUE) AS is_active
            FROM users
            WHERE id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    ).mappings().one_or_none()
    if row is None or not bool(row["is_active"]):
        raise HTTPException(status_code=401, detail="User not active")

    return CurrentUser(
        id=int(row["id"]),
        username=str(row["username"]),
        is_admin=bool(row["is_admin"]),
    )


def resolve_current_user_from_access_token(db: Session, access_token: str | None) -> CurrentUser:
    bypass_user = _bypass_current_user()
    if bypass_user is not None:
        return bypass_user

    if not access_token:
        raise HTTPException(status_code=401, detail="Missing access token")

    try:
        payload = decode_access_token(access_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    subject = payload.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token subject") from exc

    return _load_current_user(db, user_id)


def require_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    bypass_user = _bypass_current_user()
    if bypass_user is not None:
        return bypass_user

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    return resolve_current_user_from_access_token(db, token)
