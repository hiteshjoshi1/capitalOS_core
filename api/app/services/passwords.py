"""Setting a user's password (#72): shared by Settings → Change password and
`make user-set-password` (the way back in when a password is forgotten)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.auth import hash_password, hash_refresh_token

# Same bounds as signup and login (schemas/auth.py).
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256


def password_algo(password_hash: str) -> str:
    return "pbkdf2_sha256" if password_hash.startswith("pbkdf2_sha256$") else "argon2id"


def set_user_password(
    db: Session,
    *,
    user_id: int,
    new_password: str,
    revoke_reason: str,
    keep_refresh_token: str | None = None,
) -> int:
    """Store a new password hash and sign out the user's other sessions.

    The session holding `keep_refresh_token` (the caller's own) stays signed in. Returns the
    number of sessions revoked. Access tokens already issued stay valid until they expire
    (AUTH_ACCESS_TOKEN_TTL_MINUTES). The caller commits.
    """
    if not MIN_PASSWORD_LENGTH <= len(new_password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(f"password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters")
    now = datetime.now(tz=timezone.utc)
    password_hash = hash_password(new_password)
    db.execute(
        text(
            """
            INSERT INTO user_credentials (user_id, password_hash, password_algo, password_updated_at)
            VALUES (:user_id, :password_hash, :password_algo, :now)
            ON CONFLICT (user_id) DO UPDATE SET
              password_hash = excluded.password_hash,
              password_algo = excluded.password_algo,
              password_updated_at = excluded.password_updated_at
            """
        ),
        {
            "user_id": user_id,
            "password_hash": password_hash,
            "password_algo": password_algo(password_hash),
            "now": now,
        },
    )
    params: dict[str, object] = {"user_id": user_id, "now": now, "reason": revoke_reason}
    keep_clause = ""
    if keep_refresh_token:
        keep_clause = "AND refresh_token_hash <> :keep_hash"
        params["keep_hash"] = hash_refresh_token(keep_refresh_token)
    revoked = db.execute(
        text(
            f"""
            UPDATE auth_sessions
            SET revoked_at = :now, revoke_reason = :reason
            WHERE user_id = :user_id
              AND revoked_at IS NULL
              {keep_clause}
            """
        ),
        params,
    )
    return int(revoked.rowcount or 0)
