from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.auth import decode_access_token


@dataclass
class CurrentUser:
    id: int
    username: str
    is_admin: bool = False


def allow_legacy_null_ownership() -> bool:
    raw = os.getenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def account_scope_sql(alias: str = "a") -> str:
    if allow_legacy_null_ownership():
        return f"({alias}.user_id = :current_user_id OR {alias}.user_id IS NULL)"
    return f"{alias}.user_id = :current_user_id"


def require_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    bypass = os.getenv("AUTH_BYPASS_USER_ID", "").strip()
    if bypass:
        try:
            user_id = int(bypass)
        except ValueError as exc:  # pragma: no cover - config misuse
            raise HTTPException(status_code=500, detail="Invalid AUTH_BYPASS_USER_ID") from exc
        return CurrentUser(id=user_id, username=f"bypass-{user_id}", is_admin=True)

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    subject = payload.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token subject") from exc

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

