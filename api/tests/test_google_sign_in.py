"""Sign in with Google (#358, D-92): the whole flow with Google's endpoints mocked.

ID tokens are real RS256 JWTs signed with a test key, so the signature, issuer, audience, expiry
and nonce checks run for real; only the network calls (token exchange, JWKS) are replaced.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from app.services import google_oauth
from tests.auth_helpers import ensure_user

CLIENT_ID = "test-client.apps.googleusercontent.com"
LOCAL = "http://localhost:5173/api/auth/google/callback"
TAILNET = "https://mac.example.ts.net:8443/api/auth/google/callback"
EMAIL = "owner@example.com"
FLOW_COOKIE = "capitalos_refresh_google"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def google_env(monkeypatch, db_engine):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URL", f"{LOCAL},{TAILNET}")
    monkeypatch.setenv("GOOGLE_ALLOWED_EMAILS", f"{EMAIL.upper()}=owner, other@example.com=nobody")
    monkeypatch.setattr(google_oauth, "signing_key_for", lambda _token: _KEY.public_key())
    ensure_user(db_engine, 7, "owner")


def _id_token(nonce: str, *, key=_KEY, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "azp": CLIENT_ID,
        "sub": "1234567890",
        "email": EMAIL,
        "email_verified": True,
        "nonce": nonce,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


class _FakeTokenEndpoint:
    """Stands in for httpx.post to Google's token endpoint; builds the ID token from the flow."""

    def __init__(self, token_for_nonce, status: int = 200):
        self.token_for_nonce = token_for_nonce
        self.status = status
        self.calls: list[dict] = []
        self.nonce = ""

    def __call__(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data})
        token = self.token_for_nonce(self.nonce)
        status = self.status

        class _Res:
            status_code = status

            def json(self_inner):
                return {"id_token": token, "access_token": "unused"}

        return _Res()


def _start(client, *, host="localhost:5173", next_path="/cash"):
    res = client.get(
        "/auth/google/start", params={"next": next_path}, headers={"host": host}, follow_redirects=False
    )
    assert res.status_code == 302, res.text
    query = parse_qs(urlsplit(res.headers["location"]).query)
    flow_cookie = res.cookies.get(FLOW_COOKIE)
    return res, {k: v[0] for k, v in query.items()}, flow_cookie


def _callback(client, *, state, flow_cookie, code="the-code", host="localhost:5173"):
    client.cookies.clear()
    headers = {"host": host}
    if flow_cookie:
        headers["cookie"] = f"{FLOW_COOKIE}={flow_cookie}"
    return client.get(
        "/auth/google/callback", params={"code": code, "state": state}, headers=headers, follow_redirects=False
    )


def _sessions(db_engine) -> int:
    with db_engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM auth_sessions WHERE user_id = 7")).scalar_one())


def test_methods_reports_google_only_when_configured(anon_client, monkeypatch):
    local = {"host": "localhost:5173"}
    assert anon_client.get("/auth/methods", headers=local).json() == {"password": True, "google": True, "signup": True}
    # At an address Google isn't set up for (a test instance on another port): password only.
    assert anon_client.get("/auth/methods", headers={"host": "mac.example.ts.net:5174"}).json()["google"] is False
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET")
    assert anon_client.get("/auth/methods", headers=local).json()["google"] is False
    assert anon_client.get("/auth/google/start", follow_redirects=False).status_code == 404


def test_happy_path_signs_in_like_a_password_login(anon_client, db_engine, monkeypatch):
    res, query, flow_cookie = _start(anon_client)
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == LOCAL
    assert query["scope"] == "openid email"
    assert query["code_challenge_method"] == "S256"
    assert "SameSite=lax" in res.headers["set-cookie"] and "HttpOnly" in res.headers["set-cookie"]

    fake = _FakeTokenEndpoint(lambda nonce: _id_token(nonce))
    fake.nonce = query["nonce"]
    monkeypatch.setattr(google_oauth.httpx, "post", fake)
    out = _callback(anon_client, state=query["state"], flow_cookie=flow_cookie)
    assert out.status_code == 200, out.text
    assert 'content="0;url=/cash"' in out.text
    set_cookie = out.headers.get("set-cookie", "")
    assert "capitalos_refresh=" in set_cookie and "SameSite=Strict" in set_cookie
    assert _sessions(db_engine) == 1

    # The refresh cookie works exactly like a password login's.
    refresh_value = out.cookies.get("capitalos_refresh")
    anon_client.cookies.clear()
    anon_client.cookies.set("capitalos_refresh", refresh_value)
    session = anon_client.post("/auth/refresh")
    assert session.status_code == 200
    assert session.json()["user"]["username"] == "owner"


def test_pkce_verifier_matches_the_challenge(anon_client, monkeypatch):
    _res, query, flow_cookie = _start(anon_client)
    fake = _FakeTokenEndpoint(lambda nonce: _id_token(nonce))
    fake.nonce = query["nonce"]
    monkeypatch.setattr(google_oauth.httpx, "post", fake)
    assert _callback(anon_client, state=query["state"], flow_cookie=flow_cookie).status_code == 200
    sent = fake.calls[0]["data"]
    assert fake.calls[0]["url"] == google_oauth.TOKEN_URL
    assert sent["grant_type"] == "authorization_code" and sent["redirect_uri"] == LOCAL
    assert google_oauth.pkce_challenge(sent["code_verifier"]) == query["code_challenge"]
    assert 43 <= len(sent["code_verifier"]) <= 128


def test_bad_state_or_missing_flow_cookie_is_refused(anon_client, db_engine, monkeypatch):
    _res, query, flow_cookie = _start(anon_client)
    fake = _FakeTokenEndpoint(lambda nonce: _id_token(query["nonce"]))
    monkeypatch.setattr(google_oauth.httpx, "post", fake)
    assert _callback(anon_client, state="forged", flow_cookie=flow_cookie).status_code == 400
    assert _callback(anon_client, state=query["state"], flow_cookie=None).status_code == 400
    tampered = flow_cookie[:-4] + ("AAAA" if not flow_cookie.endswith("AAAA") else "BBBB")
    assert _callback(anon_client, state=query["state"], flow_cookie=tampered).status_code == 400
    assert fake.calls == [] and _sessions(db_engine) == 0


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"nonce": "not-the-flow-nonce"},
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"azp": "someone-else.apps.googleusercontent.com"},
        {"iss": "https://evil.example.com"},
        {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
        {"key": _OTHER_KEY},
    ],
    ids=["bad-nonce", "wrong-audience", "wrong-azp", "wrong-issuer", "expired", "bad-signature"],
)
def test_bad_id_tokens_are_refused(anon_client, db_engine, monkeypatch, token_kwargs):
    _res, query, flow_cookie = _start(anon_client)

    def make(nonce):
        kwargs = dict(token_kwargs)
        return _id_token(kwargs.pop("nonce", nonce), **kwargs)

    fake = _FakeTokenEndpoint(make)
    fake.nonce = query["nonce"]
    monkeypatch.setattr(google_oauth.httpx, "post", fake)
    out = _callback(anon_client, state=query["state"], flow_cookie=flow_cookie)
    assert out.status_code == 401, out.text
    assert "capitalos_refresh=" not in out.headers.get("set-cookie", "").replace(f"{FLOW_COOKIE}=", "")
    assert _sessions(db_engine) == 0


def test_unverified_email_is_refused(anon_client, db_engine, monkeypatch):
    _res, query, flow_cookie = _start(anon_client)
    fake = _FakeTokenEndpoint(lambda nonce: _id_token(nonce, email_verified=False))
    fake.nonce = query["nonce"]
    monkeypatch.setattr(google_oauth.httpx, "post", fake)
    assert _callback(anon_client, state=query["state"], flow_cookie=flow_cookie).status_code == 403
    assert _sessions(db_engine) == 0


@pytest.mark.parametrize("email", ["stranger@example.com", "other@example.com"], ids=["not-listed", "no-such-user"])
def test_email_not_allowed_gets_a_clear_403(anon_client, db_engine, monkeypatch, email):
    _res, query, flow_cookie = _start(anon_client)
    fake = _FakeTokenEndpoint(lambda nonce: _id_token(nonce, email=email))
    fake.nonce = query["nonce"]
    monkeypatch.setattr(google_oauth.httpx, "post", fake)
    out = _callback(anon_client, state=query["state"], flow_cookie=flow_cookie)
    assert out.status_code == 403
    assert f"{email} isn&#x27;t allowed" in out.text or f"{email} isn't allowed" in out.text
    assert _sessions(db_engine) == 0


def test_not_allowed_attempts_are_throttled(anon_client, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES_PER_USER", "2")
    for _ in range(2):
        _res, query, flow_cookie = _start(anon_client)
        fake = _FakeTokenEndpoint(lambda nonce: _id_token(nonce, email="stranger@example.com"))
        fake.nonce = query["nonce"]
        monkeypatch.setattr(google_oauth.httpx, "post", fake)
        _callback(anon_client, state=query["state"], flow_cookie=flow_cookie)
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES_PER_IP", "2")
    _res, query, flow_cookie = _start(anon_client)
    out = _callback(anon_client, state=query["state"], flow_cookie=flow_cookie)
    assert out.status_code == 429 and out.headers.get("retry-after")


def test_google_refusing_the_code_is_a_502(anon_client, db_engine, monkeypatch):
    _res, query, flow_cookie = _start(anon_client)
    monkeypatch.setattr(google_oauth.httpx, "post", _FakeTokenEndpoint(lambda nonce: "", status=400))
    assert _callback(anon_client, state=query["state"], flow_cookie=flow_cookie).status_code == 502
    assert _sessions(db_engine) == 0


def test_cancelled_at_google(anon_client):
    out = anon_client.get("/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert out.status_code == 400 and "cancelled" in out.text


def test_redirect_url_follows_the_address_used(anon_client):
    res, query, _cookie = _start(anon_client, host="mac.example.ts.net:8443")
    assert query["redirect_uri"] == TAILNET
    assert "Secure" in res.headers["set-cookie"]
    # A proxy that dropped the port still matches on the host name.
    _res, query, _cookie = _start(anon_client, host="mac.example.ts.net")
    assert query["redirect_uri"] == TAILNET
    # The same name on another port (a test instance) or another host is refused.
    for host in ("mac.example.ts.net:5174", "evil.example.com"):
        out = anon_client.get("/auth/google/start", headers={"host": host}, follow_redirects=False)
        assert out.status_code == 400 and "location" not in out.headers


def test_x_forwarded_host_is_only_trusted_from_a_proxy(monkeypatch):
    from types import SimpleNamespace

    from app.services.login_throttle import request_authority

    def req(peer):
        return SimpleNamespace(
            client=SimpleNamespace(host=peer),
            headers={"host": "api:8000", "x-forwarded-host": "mac.example.ts.net:8443"},
        )

    assert request_authority(req("172.18.0.5")) == "mac.example.ts.net:8443"
    assert request_authority(req("203.0.113.9")) == "api:8000"


def test_next_path_cannot_leave_the_site(anon_client, monkeypatch):
    for bad in ("https://evil.example.com", "//evil.example.com", "/\\evil.example.com", "javascript:alert(1)"):
        assert google_oauth.safe_next_path(bad) == "/wealth"
    assert google_oauth.safe_next_path("/cash?month=2026-10") == "/cash?month=2026-10"


def test_password_login_can_be_turned_off(anon_client, db_engine, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD_LOGIN", "0")
    assert anon_client.get("/auth/methods").json()["password"] is False
    res = anon_client.post("/auth/login", json={"username": "owner", "password": "whatever-123"})
    assert res.status_code == 403


def test_config_rejects_bad_redirects_and_parses_allowed_emails(monkeypatch):
    assert google_oauth.parse_allowed_emails(" A@B.com = hitesh ,bad, x@y=") == {"a@b.com": "hitesh"}
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URL", "http://mac.example.ts.net/api/auth/google/callback")
    assert google_oauth.google_config() is None  # plain http is only for localhost
