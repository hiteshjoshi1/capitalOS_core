from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.schemas.auth import AuthMeResponse, AuthTokenResponse, LoginRequest, SignupRequest
from app.services.auth import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_cookie_name,
    refresh_token_ttl_seconds,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _refresh_grace_seconds() -> int:
    return max(int(os.getenv("AUTH_REFRESH_GRACE_SECONDS", "30")), 0)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    ttl = refresh_token_ttl_seconds()
    secure = os.getenv("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
    response.set_cookie(
        key=refresh_cookie_name(),
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ttl,
        path="/",
    )


def _create_refresh_session(db: Session, *, user_id: int) -> str:
    now = datetime.now(tz=timezone.utc)
    refresh_token = generate_refresh_token()
    db.execute(
        text(
            """
            INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at, revoked_at, revoke_reason, created_at)
            VALUES (:user_id, :refresh_token_hash, :expires_at, NULL, NULL, :created_at)
            """
        ),
        {
            "user_id": user_id,
            "refresh_token_hash": hash_refresh_token(refresh_token),
            "expires_at": now + timedelta(seconds=refresh_token_ttl_seconds()),
            "created_at": now,
        },
    )
    return refresh_token


@router.post("/signup", response_model=AuthMeResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")

    existing = db.execute(
        text("SELECT id FROM users WHERE LOWER(username) = LOWER(:username) LIMIT 1"),
        {"username": username},
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="username already exists")

    user_row = db.execute(
        text(
            """
            INSERT INTO users (username, display_name, is_active, is_admin, created_at, updated_at)
            VALUES (:username, :display_name, TRUE, FALSE, :now, :now)
            RETURNING id, username, display_name, email, is_admin
            """
        ),
        {
            "username": username,
            "display_name": payload.display_name.strip() if payload.display_name else None,
            "now": datetime.now(tz=timezone.utc),
        },
    ).mappings().one()

    db.execute(
        text(
            """
            INSERT INTO user_credentials (user_id, password_hash, password_algo, password_updated_at)
            VALUES (:user_id, :password_hash, 'argon2id', :now)
            """
        ),
        {
            "user_id": int(user_row["id"]),
            "password_hash": hash_password(payload.password),
            "now": datetime.now(tz=timezone.utc),
        },
    )
    db.commit()
    return AuthMeResponse(
        id=int(user_row["id"]),
        username=str(user_row["username"]),
        display_name=user_row["display_name"],
        email=user_row["email"],
        is_admin=bool(user_row["is_admin"]),
    )


@router.post("/login", response_model=AuthTokenResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            """
            SELECT
              u.id,
              u.username,
              u.is_active,
              uc.password_hash
            FROM users u
            JOIN user_credentials uc ON uc.user_id = u.id
            WHERE LOWER(u.username) = LOWER(:username)
            LIMIT 1
            """
        ),
        {"username": payload.username.strip()},
    ).mappings().one_or_none()
    if row is None or not bool(row["is_active"]):
        raise HTTPException(status_code=401, detail="invalid credentials")

    if not verify_password(payload.password, str(row["password_hash"])):
        raise HTTPException(status_code=401, detail="invalid credentials")

    user_id = int(row["id"])
    username = str(row["username"])
    now = datetime.now(tz=timezone.utc)
    access_token, exp = create_access_token(user_id=user_id, username=username)
    refresh_token = _create_refresh_session(db, user_id=user_id)
    db.commit()

    _set_refresh_cookie(response, refresh_token)
    return AuthTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=max(int((exp - now).total_seconds()), 1),
    )


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get(refresh_cookie_name())
    if not refresh_token:
        response.delete_cookie(refresh_cookie_name(), path="/")
        raise HTTPException(status_code=401, detail="refresh token required")

    token_hash = hash_refresh_token(refresh_token)
    now = datetime.now(tz=timezone.utc)
    row = db.execute(
        text(
            """
            SELECT
              s.id AS session_id,
              s.user_id,
              u.username
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.refresh_token_hash = :refresh_token_hash
              AND s.revoked_at IS NULL
              AND s.expires_at > :now
              AND COALESCE(u.is_active, TRUE) = TRUE
            LIMIT 1
            """
        ),
        {"refresh_token_hash": token_hash, "now": now},
    ).mappings().one_or_none()

    if row is None:
        # Token not found as active. Check if it was recently rotated (concurrent refresh grace window).
        grace = _refresh_grace_seconds()
        recovered = False
        if grace > 0:
            grace_cutoff = now - timedelta(seconds=grace)
            revoked_row = db.execute(
                text(
                    """
                    SELECT s.id AS session_id, s.user_id, s.revoke_reason, s.revoked_at, u.username
                    FROM auth_sessions s
                    JOIN users u ON u.id = s.user_id
                    WHERE s.refresh_token_hash = :refresh_token_hash
                      AND s.revoked_at IS NOT NULL
                      AND s.revoke_reason = 'rotation'
                      AND s.revoked_at >= :grace_cutoff
                      AND COALESCE(u.is_active, TRUE) = TRUE
                    LIMIT 1
                    """
                ),
                {"refresh_token_hash": token_hash, "grace_cutoff": grace_cutoff},
            ).mappings().one_or_none()

            if revoked_row is not None:
                # Concurrent refresh: find and rotate the user's current active session.
                user_id = int(revoked_row["user_id"])
                username = str(revoked_row["username"])
                active_session = db.execute(
                    text(
                        """
                        SELECT id AS session_id
                        FROM auth_sessions
                        WHERE user_id = :user_id
                          AND revoked_at IS NULL
                          AND expires_at > :now
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id, "now": now},
                ).mappings().one_or_none()

                if active_session is not None:
                    rotated = db.execute(
                        text(
                            """
                            UPDATE auth_sessions
                            SET revoked_at = :now, revoke_reason = 'rotation'
                            WHERE id = :session_id AND revoked_at IS NULL
                            """
                        ),
                        {"now": now, "session_id": int(active_session["session_id"])},
                    ).rowcount
                    if rotated > 0:
                        next_refresh_token = _create_refresh_session(db, user_id=user_id)
                        access_token, exp = create_access_token(user_id=user_id, username=username)
                        db.commit()
                        _set_refresh_cookie(response, next_refresh_token)
                        recovered = True
                        return AuthTokenResponse(
                            access_token=access_token,
                            token_type="bearer",
                            expires_in=max(int((exp - now).total_seconds()), 1),
                        )

        if not recovered:
            db.execute(
                text(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = :now, revoke_reason = 'security'
                    WHERE refresh_token_hash = :refresh_token_hash
                      AND revoked_at IS NULL
                    """
                ),
                {"now": now, "refresh_token_hash": token_hash},
            )
            db.commit()
            response.delete_cookie(refresh_cookie_name(), path="/")
            raise HTTPException(status_code=401, detail="invalid or expired refresh token")

    revoked = db.execute(
        text(
            """
            UPDATE auth_sessions
            SET revoked_at = :now, revoke_reason = 'rotation'
            WHERE id = :session_id
              AND revoked_at IS NULL
            """
        ),
        {"now": now, "session_id": int(row["session_id"])},
    ).rowcount
    if revoked == 0:
        response.delete_cookie(refresh_cookie_name(), path="/")
        raise HTTPException(status_code=401, detail="invalid refresh token")

    user_id = int(row["user_id"])
    username = str(row["username"])
    next_refresh_token = _create_refresh_session(db, user_id=user_id)
    access_token, exp = create_access_token(user_id=user_id, username=username)
    db.commit()

    _set_refresh_cookie(response, next_refresh_token)
    return AuthTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=max(int((exp - now).total_seconds()), 1),
    )


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get(refresh_cookie_name())
    if refresh_token:
        db.execute(
            text(
                """
                UPDATE auth_sessions
                SET revoked_at = :now, revoke_reason = 'logout'
                WHERE refresh_token_hash = :token_hash
                  AND revoked_at IS NULL
                """
            ),
            {"token_hash": hash_refresh_token(refresh_token), "now": datetime.now(tz=timezone.utc)},
        )
        db.commit()
    response.delete_cookie(refresh_cookie_name(), path="/")
    return {"status": "ok"}


@router.get("/me", response_model=AuthMeResponse)
def me(current_user: CurrentUser = Depends(require_current_user), db: Session = Depends(get_db)):
    row = db.execute(
        text(
            """
            SELECT id, username, display_name, email, COALESCE(is_admin, FALSE) AS is_admin
            FROM users
            WHERE id = :id
            LIMIT 1
            """
        ),
        {"id": current_user.id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return AuthMeResponse(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=row["display_name"],
        email=row["email"],
        is_admin=bool(row["is_admin"]),
    )
