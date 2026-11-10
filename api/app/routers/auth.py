from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import html

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.core.clock import default_timezone_name, normalize_timezone_name
from app.db.session import get_db
from app.schemas.auth import (
    AuthMethodsResponse,
    AuthMeResponse,
    AuthSessionResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    DEFAULT_ACCENT_COLOR,
    DEFAULT_THEME,
    LoginRequest,
    SignupRequest,
    UserPreferencesResponse,
    UserPreferencesPatchRequest,
    VALID_ACCENT_COLORS,
    VALID_THEMES,
)
from app.services.auth import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_cookie_name,
    refresh_token_ttl_seconds,
    verify_password,
)
from app.services import google_oauth
from app.services.login_throttle import client_ip, login_throttle, request_authority
from app.services.passwords import set_user_password
from app.services.user_preferences import BASE_CURRENCIES, timezone_source
from app.wealth_rollup_dirty import mark_rollups_dirty

router = APIRouter(prefix="/auth", tags=["auth"])

_dummy_password_hash: str | None = None


def _dummy_hash() -> str:
    """A real hash of a throwaway secret, checked when the username is unknown or inactive,
    so a failed sign-in costs the same either way and doesn't reveal which usernames exist."""
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = hash_password(generate_refresh_token())
    return _dummy_password_hash


def signup_allowed() -> bool:
    """Signup is off unless AUTH_ALLOW_SIGNUP is set to a true value (#152)."""
    return os.getenv("AUTH_ALLOW_SIGNUP", "0").strip().lower() in {"1", "true", "yes", "on"}


def password_login_allowed() -> bool:
    """Password sign-in is on unless AUTH_PASSWORD_LOGIN is set to a false value (#358)."""
    return os.getenv("AUTH_PASSWORD_LOGIN", "1").strip().lower() not in {"0", "false", "no", "off"}


def _refresh_grace_seconds() -> int:
    return max(int(os.getenv("AUTH_REFRESH_GRACE_SECONDS", "30")), 0)


def _cookie_samesite() -> str:
    raw = os.getenv("AUTH_COOKIE_SAMESITE", "strict").strip().lower()
    return {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
    }.get(raw, "Strict")


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    ttl = refresh_token_ttl_seconds()
    secure = os.getenv("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
    samesite = _cookie_samesite()
    response.set_cookie(
        key=refresh_cookie_name(),
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite=samesite,
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


def _load_user(db: Session, user_id: int) -> AuthMeResponse | None:
    row = db.execute(
        text(
            """
            SELECT id, username, display_name, email, COALESCE(is_admin, FALSE) AS is_admin
            FROM users
            WHERE id = :id
            LIMIT 1
            """
        ),
        {"id": user_id},
    ).mappings().one_or_none()
    if row is None:
        return None
    return AuthMeResponse(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=row["display_name"],
        email=row["email"],
        is_admin=bool(row["is_admin"]),
    )


_PREFERENCE_COLUMNS = "theme, accent_color, timezone, timezone_from_app, base_currency"


def _preferences_response(row) -> UserPreferencesResponse:  # noqa: ANN001
    """The API shape of a user_preferences row (None: the defaults)."""
    if row is None:
        return UserPreferencesResponse(
            theme=DEFAULT_THEME,
            accent_color=DEFAULT_ACCENT_COLOR,
            timezone=default_timezone_name(),
            timezone_source=timezone_source(None, False),
            base_currency=None,
        )
    stored_tz = normalize_timezone_name(row["timezone"])
    return UserPreferencesResponse(
        theme=str(row["theme"]),
        accent_color=str(row["accent_color"]),
        timezone=stored_tz or default_timezone_name(),
        timezone_source=timezone_source(stored_tz, bool(row["timezone_from_app"])),
        base_currency=str(row["base_currency"]) if row["base_currency"] else None,
    )


def _preferences_row(db: Session, user_id: int):  # noqa: ANN202
    return db.execute(
        text(f"SELECT {_PREFERENCE_COLUMNS} FROM user_preferences WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).mappings().one_or_none()


def _read_preferences(db: Session, user_id: int) -> UserPreferencesResponse:
    """The user's stored preferences, or the defaults GET /auth/preferences would create."""
    return _preferences_response(_preferences_row(db, user_id))


def _session_response(
    db: Session, *, user_id: int, access_token: str, exp: datetime, now: datetime
) -> AuthSessionResponse:
    # user + preferences ride along with the token so a cold load is one round trip (#146).
    return AuthSessionResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=max(int((exp - now).total_seconds()), 1),
        user=_load_user(db, user_id),
        preferences=_read_preferences(db, user_id),
    )


@router.post("/signup", response_model=AuthMeResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if not signup_allowed():
        raise HTTPException(status_code=403, detail="Signup is disabled")
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


@router.post("/login", response_model=AuthSessionResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if not password_login_allowed():
        raise HTTPException(status_code=403, detail="Password sign-in is turned off; use Sign in with Google")
    username_input = payload.username.strip()
    ip = client_ip(request)
    wait = login_throttle.retry_after(username=username_input, ip=ip)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts; try again later",
            headers={"Retry-After": str(wait)},
        )

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
        {"username": username_input},
    ).mappings().one_or_none()
    known = row is not None and bool(row["is_active"])
    # Always check a password, even for an unknown or inactive user (timing, #152).
    password_hash = str(row["password_hash"]) if known and row is not None else _dummy_hash()
    password_ok = verify_password(payload.password, password_hash)
    if not known or not password_ok or row is None:
        login_throttle.record_failure(username=username_input, ip=ip)
        raise HTTPException(status_code=401, detail="invalid credentials")
    login_throttle.record_success(username=username_input)

    user_id = int(row["id"])
    username = str(row["username"])
    now = datetime.now(tz=timezone.utc)
    access_token, exp = create_access_token(user_id=user_id, username=username)
    refresh_token = _create_refresh_session(db, user_id=user_id)
    db.commit()

    _set_refresh_cookie(response, refresh_token)
    return _session_response(db, user_id=user_id, access_token=access_token, exp=exp, now=now)


@router.post("/refresh", response_model=AuthSessionResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get(refresh_cookie_name())
    if not refresh_token:
        response.delete_cookie(refresh_cookie_name(), path="/")
        raise HTTPException(status_code=401, detail="refresh token required")

    token_hash = hash_refresh_token(refresh_token)
    now = datetime.now(tz=timezone.utc)

    # Claim (revoke-for-rotation) the session in one atomic statement instead of a
    # separate SELECT-then-UPDATE. Two requests racing on the same refresh token — e.g.
    # React 18 StrictMode double-invoking an effect on mount, overlapping refresh timers,
    # or two tabs reloading at once — would otherwise both pass a "is this still active?"
    # SELECT before either commits its revoke, so the loser's later UPDATE affects zero
    # rows and (previously) was treated as an invalid/replayed token and logged the user
    # out. With a single UPDATE ... WHERE revoked_at IS NULL, only one caller can ever
    # claim a given row; every other caller (whether it lost a true race or presented an
    # already-rotated token) falls through to the grace-window recovery below.
    # Plain UPDATE ... RETURNING (no CTE/JOIN) so this runs identically on Postgres and the
    # SQLite engine used in tests — SQLite doesn't support data-modifying CTEs.
    claimed_session = db.execute(
        text(
            """
            UPDATE auth_sessions
            SET revoked_at = :now, revoke_reason = 'rotation'
            WHERE refresh_token_hash = :refresh_token_hash
              AND revoked_at IS NULL
              AND expires_at > :now
            RETURNING id AS session_id, user_id
            """
        ),
        {"refresh_token_hash": token_hash, "now": now},
    ).mappings().one_or_none()

    claimed = None
    if claimed_session is not None:
        user_row = db.execute(
            text("SELECT username, COALESCE(is_active, TRUE) AS is_active FROM users WHERE id = :user_id"),
            {"user_id": int(claimed_session["user_id"])},
        ).mappings().one_or_none()
        if user_row is not None and bool(user_row["is_active"]):
            claimed = {
                "session_id": int(claimed_session["session_id"]),
                "user_id": int(claimed_session["user_id"]),
                "username": str(user_row["username"]),
            }

    if claimed is None:
        # Not claimable: either genuinely invalid/expired, or another concurrent request
        # already won the rotation race for this exact token moments ago. Check the grace
        # window before treating this as a security incident.
        grace = _refresh_grace_seconds()
        if grace > 0:
            grace_cutoff = now - timedelta(seconds=grace)
            revoked_row = db.execute(
                text(
                    """
                    SELECT s.user_id, u.username
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
                # Concurrent refresh: find and rotate the user's current active session so
                # this caller converges on the same session every other racer landed on.
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
                        return _session_response(
                            db, user_id=user_id, access_token=access_token, exp=exp, now=now
                        )

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

    user_id = int(claimed["user_id"])
    username = str(claimed["username"])
    next_refresh_token = _create_refresh_session(db, user_id=user_id)
    access_token, exp = create_access_token(user_id=user_id, username=username)
    db.commit()

    _set_refresh_cookie(response, next_refresh_token)
    return _session_response(db, user_id=user_id, access_token=access_token, exp=exp, now=now)


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


@router.get("/methods", response_model=AuthMethodsResponse)
def auth_methods(request: Request):
    """Which ways of signing in are on (public: the sign-in page asks before anyone is signed in).

    Google counts as on only at an address it's set up for, so a test instance (another port,
    sharing the real app's .env) shows the password form alone.
    """
    config = google_oauth.google_config()
    google = config is not None and google_oauth.pick_redirect_url(config, request_authority(request)) is not None
    return AuthMethodsResponse(password=password_login_allowed(), google=google, signup=signup_allowed())


def _google_flow_cookie_name() -> str:
    # Per instance like the refresh cookie (#65), so a test instance's flow never meets the real app's.
    return f"{refresh_cookie_name()}_google"


_GOOGLE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{refresh}<title>CapitalOS sign-in</title>
<style>body{{font-family:system-ui,sans-serif;max-width:420px;margin:15vh auto;padding:0 16px;line-height:1.5}}
@media (prefers-color-scheme: dark){{body{{background:#111;color:#eee}}a{{color:#7cc4ff}}}}</style></head>
<body><h1 style="font-size:20px">{title}</h1><p>{message}</p><p><a href="{link}">{link_text}</a></p></body></html>"""


def _google_page(status: int, title: str, message: str, *, link: str = "/login", link_text: str = "Back to sign in", go: bool = False) -> HTMLResponse:
    refresh = f'<meta http-equiv="refresh" content="0;url={html.escape(link, quote=True)}">' if go else ""
    body = _GOOGLE_PAGE.format(
        refresh=refresh,
        title=html.escape(title),
        message=html.escape(message),
        link=html.escape(link, quote=True),
        link_text=html.escape(link_text),
    )
    return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _google_error_page(err: google_oauth.GoogleSignInError) -> HTMLResponse:
    return _google_page(err.status, "Couldn't sign in with Google", err.message)


@router.get("/google/start")
def google_start(request: Request, next: str | None = None):  # noqa: A002 - the query parameter's name
    config = google_oauth.google_config()
    if config is None:
        raise HTTPException(status_code=404, detail="Google sign-in isn't set up")
    redirect_url = google_oauth.pick_redirect_url(config, request_authority(request))
    if redirect_url is None:
        return _google_page(
            400,
            "Google sign-in isn't set up for this address",
            "Open CapitalOS at the address set up for Google sign-in (GOOGLE_OAUTH_REDIRECT_URL), or sign in with your password.",
        )
    auth_url, flow_cookie = google_oauth.start_flow(
        config, redirect_url=redirect_url, next_path=google_oauth.safe_next_path(next)
    )
    response = RedirectResponse(auth_url, status_code=302, headers={"Cache-Control": "no-store"})
    # Lax, not Strict: the browser must send it on Google's cross-site redirect back to the callback.
    response.set_cookie(
        key=_google_flow_cookie_name(),
        value=flow_cookie,
        httponly=True,
        secure=redirect_url.startswith("https://"),
        samesite="lax",
        max_age=google_oauth.FLOW_TTL_SECONDS,
        path="/",
    )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    config = google_oauth.google_config()
    if config is None:
        raise HTTPException(status_code=404, detail="Google sign-in isn't set up")
    ip = client_ip(request)
    response: HTMLResponse
    try:
        wait = login_throttle.retry_after(username="google", ip=ip)
        if wait > 0:
            response = _google_page(429, "Too many sign-in attempts", "Too many failed sign-in attempts; try again later.")
            response.headers["Retry-After"] = str(wait)
            return response
        if error:
            raise google_oauth.GoogleSignInError(400, "Google sign-in was cancelled.", code="cancelled")
        flow = google_oauth.read_flow(request.cookies.get(_google_flow_cookie_name()), state)
        if not code:
            raise google_oauth.GoogleSignInError(400, "Google didn't send a sign-in code. Try again.", code="state")
        tokens = google_oauth.exchange_code(
            config, code=code, redirect_uri=str(flow["redirect_uri"]), verifier=str(flow["verifier"])
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise google_oauth.GoogleSignInError(502, "Google didn't send an identity token. Try again.", code="token")
        email = google_oauth.verify_id_token(config, id_token, nonce=str(flow["nonce"]))

        username = config.allowed.get(email)
        row = None
        if username is not None:
            row = db.execute(
                text(
                    """
                    SELECT id, username, COALESCE(is_active, TRUE) AS is_active
                    FROM users WHERE LOWER(username) = LOWER(:username) LIMIT 1
                    """
                ),
                {"username": username},
            ).mappings().one_or_none()
        if row is None or not bool(row["is_active"]):
            login_throttle.record_failure(username=f"google:{email}", ip=ip)
            raise google_oauth.GoogleSignInError(
                403, f"{email} isn't allowed to sign in to this CapitalOS.", code="not_allowed"
            )
    except google_oauth.GoogleSignInError as err:
        if err.code in {"state", "token"}:
            login_throttle.record_failure(username="google", ip=ip)
        response = _google_error_page(err)
        response.delete_cookie(_google_flow_cookie_name(), path="/")
        return response

    login_throttle.record_success(username=f"google:{email}")
    user_id = int(row["id"])
    refresh_token = _create_refresh_session(db, user_id=user_id)
    db.commit()
    # A same-site hop (meta refresh) to the app, so its Strict refresh cookie is sent on the next load.
    next_path = google_oauth.safe_next_path(str(flow.get("next") or ""))
    response = _google_page(200, "Signed in", "Opening CapitalOS…", link=next_path, link_text="Continue", go=True)
    _set_refresh_cookie(response, refresh_token)
    response.delete_cookie(_google_flow_cookie_name(), path="/")
    return response


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    # 400, not 401, for a wrong current password: a 401 means "signed out" to the web app.
    row = db.execute(
        text("SELECT password_hash FROM user_credentials WHERE user_id = :user_id"),
        {"user_id": current_user.id},
    ).mappings().one_or_none()
    if row is None or not verify_password(payload.current_password, str(row["password_hash"])):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")

    signed_out = set_user_password(
        db,
        user_id=current_user.id,
        new_password=payload.new_password,
        revoke_reason="password_change",
        keep_refresh_token=request.cookies.get(refresh_cookie_name()),
    )
    db.commit()
    return ChangePasswordResponse(signed_out_sessions=signed_out)


@router.get("/me", response_model=AuthMeResponse)
def me(current_user: CurrentUser = Depends(require_current_user), db: Session = Depends(get_db)):
    user = _load_user(db, current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@router.get("/preferences", response_model=UserPreferencesResponse)
def get_preferences(
    current_user: CurrentUser = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    row = _preferences_row(db, current_user.id)

    if row is None:
        now = datetime.now(tz=timezone.utc)
        db.execute(
            text(
                """
                INSERT INTO user_preferences (user_id, theme, accent_color, updated_at)
                VALUES (:user_id, :theme, :accent_color, :now)
                """
            ),
            {
                "user_id": current_user.id,
                "theme": DEFAULT_THEME,
                "accent_color": DEFAULT_ACCENT_COLOR,
                "now": now,
            },
        )
        db.commit()
        return _preferences_response(None)

    return _preferences_response(row)


def _earliest_card_transaction_date(db: Session, user_id: int):  # noqa: ANN202
    """Where a timezone change starts to matter for stored History: card
    spending is the one input whose month boundary is a local midnight (#202)."""
    return db.execute(
        text(
            """
            SELECT MIN(t.ts) FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.account_type = 'CREDIT_CARD' AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": user_id},
    ).scalar()


@router.patch("/preferences", response_model=UserPreferencesResponse)
def patch_preferences(
    payload: UserPreferencesPatchRequest,
    current_user: CurrentUser = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    if payload.theme is not None and payload.theme not in VALID_THEMES:
        raise HTTPException(
            status_code=422,
            detail=f"theme must be one of: {', '.join(sorted(VALID_THEMES))}",
        )
    if payload.accent_color is not None and payload.accent_color not in VALID_ACCENT_COLORS:
        raise HTTPException(
            status_code=422,
            detail=f"accent_color must be one of: {', '.join(sorted(VALID_ACCENT_COLORS))}",
        )
    new_timezone = None
    if payload.timezone is not None:
        new_timezone = normalize_timezone_name(payload.timezone)
        if new_timezone is None:
            raise HTTPException(
                status_code=422,
                detail="timezone must be an IANA timezone name, e.g. Asia/Singapore or America/New_York",
            )
    new_base_currency = None
    if payload.base_currency is not None:
        new_base_currency = payload.base_currency.strip().upper()
        if new_base_currency not in BASE_CURRENCIES:
            raise HTTPException(
                status_code=422,
                detail=f"base_currency must be one of: {', '.join(BASE_CURRENCIES)}",
            )

    row = _preferences_row(db, current_user.id)
    now = datetime.now(tz=timezone.utc)
    if row is None:
        db.execute(
            text(
                """
                INSERT INTO user_preferences (user_id, theme, accent_color, updated_at)
                VALUES (:user_id, :theme, :accent_color, :now)
                """
            ),
            {"user_id": current_user.id, "theme": DEFAULT_THEME, "accent_color": DEFAULT_ACCENT_COLOR, "now": now},
        )
        row = _preferences_row(db, current_user.id)
    before = _preferences_response(row)

    updates = {
        "theme": payload.theme if payload.theme is not None else str(row["theme"]),
        "accent_color": payload.accent_color if payload.accent_color is not None else str(row["accent_color"]),
        "base_currency": new_base_currency if new_base_currency is not None else row["base_currency"],
        "timezone": new_timezone if new_timezone is not None else row["timezone"],
        # A timezone the user picks replaces "follow the app's TZ".
        "timezone_from_app": False if new_timezone is not None else bool(row["timezone_from_app"]),
    }
    db.execute(
        text(
            """
            UPDATE user_preferences
            SET theme = :theme, accent_color = :accent_color, base_currency = :base_currency,
                timezone = :timezone, timezone_from_app = :timezone_from_app, updated_at = :now
            WHERE user_id = :user_id
            """
        ),
        {**updates, "user_id": current_user.id, "now": now},
    )
    after = _preferences_response(_preferences_row(db, current_user.id))
    if after.timezone != before.timezone:
        # Months now end at another midnight: stored History rows are recomputed
        # from the first one card spending can move (D-29). Which months are
        # completed is decided on read, in the new timezone.
        earliest = _earliest_card_transaction_date(db, current_user.id)
        if earliest is not None:
            mark_rollups_dirty(db, earliest, user_ids=[current_user.id], reason="timezone_changed")
    db.commit()
    return after
