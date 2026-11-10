"""Sign in with Google (#358, D-92): OAuth 2.0 authorization code flow with PKCE, state and nonce.

The API does the whole exchange server-side; the browser only follows redirects:

  GET /auth/google/start     -> 302 to Google, with a short-lived signed "flow" cookie that
                                holds state, nonce, the PKCE verifier, the redirect URI and
                                where to go afterwards
  GET /auth/google/callback  -> checks state against that cookie, swaps the code (with the
                                PKCE verifier) for tokens, verifies the ID token (signature via
                                Google's JWKS, issuer, audience, expiry, nonce, email_verified),
                                maps the email to a CapitalOS user and signs them in exactly like
                                a password login (auth_sessions row + refresh cookie)

Everything is configured in `.env`; with any of the settings missing Google sign-in is off and
nothing else changes:
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REDIRECT_URL   one or more (comma-separated) .../api/auth/google/callback URLs;
                              the one whose host (and port, when known) matches the request is used
  GOOGLE_ALLOWED_EMAILS       comma-separated `email=username` pairs; nobody else gets in
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from app.services.auth import _jwt_secret

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

FLOW_TTL_SECONDS = 600
_FLOW_TYPE = "google_oauth_flow"
_HTTP_TIMEOUT_SECONDS = 10.0


class GoogleSignInError(Exception):
    """A sign-in that must stop, with the HTTP status and a message the user can act on."""

    def __init__(self, status: int, message: str, *, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    redirect_urls: tuple[str, ...]
    allowed: dict[str, str]  # lower-cased email -> username


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _valid_redirect(url: str) -> bool:
    parts = urlsplit(url)
    if not parts.hostname or parts.query or parts.fragment:
        return False
    if parts.scheme == "https":
        return True
    # Google allows plain http only for loopback.
    return parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}


def parse_allowed_emails(raw: str) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        email, username = (part.strip() for part in item.split("=", 1))
        if "@" in email and username:
            allowed[email.lower()] = username
    return allowed


def google_config() -> GoogleConfig | None:
    """The Google settings, or None when Google sign-in is off (anything missing or invalid)."""
    client_id = _env("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = _env("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect_urls = tuple(u.strip() for u in _env("GOOGLE_OAUTH_REDIRECT_URL").split(",") if u.strip())
    allowed = parse_allowed_emails(_env("GOOGLE_ALLOWED_EMAILS"))
    if not (client_id and client_secret and redirect_urls and allowed):
        return None
    if not all(_valid_redirect(u) for u in redirect_urls):
        return None
    return GoogleConfig(client_id, client_secret, redirect_urls, allowed)


def _split_authority(authority: str) -> tuple[str, int | None]:
    authority = authority.strip().lower()
    if authority.startswith("["):  # [::1]:5173
        host, _, rest = authority[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port = authority.partition(":")
    return host, int(port) if port.isdigit() else None


def _url_authority(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    default = 443 if parts.scheme == "https" else 80
    return (parts.hostname or "").lower(), parts.port or default


def pick_redirect_url(config: GoogleConfig, request_authority: str) -> str | None:
    """The configured redirect URL for the address the browser used, or None.

    Matched on host and port when the request names a port (so a test instance on :5174 never
    lands on the real app's :8443 callback); on host alone when a proxy dropped the port.
    """
    host, port = _split_authority(request_authority)
    if not host:
        return None
    for url in config.redirect_urls:
        url_host, url_port = _url_authority(url)
        if url_host == host and (port is None or port == url_port):
            return url
    return None


def safe_next_path(raw: str | None, default: str = "/wealth") -> str:
    """Only a path on this site: no scheme, no host, no protocol-relative //, no backslashes."""
    if not raw or not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return default
    if any(ord(ch) < 0x20 for ch in raw):
        return default
    return raw


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def start_flow(config: GoogleConfig, *, redirect_url: str, next_path: str) -> tuple[str, str]:
    """(Google's authorization URL, the signed flow cookie value)."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 chars, within PKCE's 43-128
    now = int(time.time())
    cookie = jwt.encode(
        {
            "type": _FLOW_TYPE,
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "redirect_uri": redirect_url,
            "next": next_path,
            "iat": now,
            "exp": now + FLOW_TTL_SECONDS,
        },
        _jwt_secret(),
        algorithm="HS256",
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": redirect_url,
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZE_URL}?{query}", cookie


def read_flow(cookie: str | None, state: str | None) -> dict[str, Any]:
    if not cookie:
        raise GoogleSignInError(400, "This sign-in has expired or was started in another browser. Try again.", code="expired")
    try:
        flow = jwt.decode(cookie, _jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise GoogleSignInError(400, "This sign-in took too long and expired. Try again.", code="expired") from exc
    except jwt.InvalidTokenError as exc:
        raise GoogleSignInError(400, "This sign-in can't be checked. Try again.", code="state") from exc
    if flow.get("type") != _FLOW_TYPE or not state or not hmac.compare_digest(str(flow.get("state", "")), state):
        raise GoogleSignInError(400, "This sign-in doesn't match the one this browser started. Try again.", code="state")
    return flow


def exchange_code(config: GoogleConfig, *, code: str, redirect_uri: str, verifier: str) -> dict[str, Any]:
    """Swap the authorization code for Google's tokens (the PKCE verifier proves we asked for it)."""
    try:
        res = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise GoogleSignInError(502, "Couldn't reach Google to finish signing in. Try again.", code="exchange") from exc
    if res.status_code != 200:
        raise GoogleSignInError(502, "Google didn't accept this sign-in. Try again.", code="exchange")
    try:
        return dict(res.json())
    except ValueError as exc:
        raise GoogleSignInError(502, "Google sent an answer that can't be read. Try again.", code="exchange") from exc


_jwks_client: jwt.PyJWKClient | None = None


def signing_key_for(id_token: str) -> Any:
    """Google's public key for this token, from its JWKS (cached by PyJWT)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True, timeout=int(_HTTP_TIMEOUT_SECONDS))
    return _jwks_client.get_signing_key_from_jwt(id_token).key


def verify_id_token(config: GoogleConfig, id_token: str, *, nonce: str) -> str:
    """The token's verified email (lower-cased); raises GoogleSignInError otherwise."""
    bad = GoogleSignInError(401, "Google's sign-in token didn't check out. Try again.", code="token")
    try:
        key = signing_key_for(id_token)
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=config.client_id,
            issuer=list(ISSUERS),
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise bad from exc
    azp = claims.get("azp")
    if azp is not None and azp != config.client_id:
        raise bad
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise bad
    email = str(claims.get("email") or "").strip().lower()
    verified = claims.get("email_verified")
    if not email or not (verified is True or str(verified).lower() == "true"):
        raise GoogleSignInError(403, "That Google account's email isn't verified.", code="unverified")
    return email
