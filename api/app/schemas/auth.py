from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ChangePasswordResponse(BaseModel):
    status: str = "ok"
    signed_out_sessions: int


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthMethodsResponse(BaseModel):
    """Which ways of signing in are on (#358)."""

    password: bool
    google: bool
    signup: bool


class AuthMeResponse(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    is_admin: bool = False


VALID_THEMES: frozenset[str] = frozenset({"dark", "light"})
VALID_ACCENT_COLORS: frozenset[str] = frozenset({"#0f7a5c", "#2b6ddb", "#8650d9", "#b5842a"})

DEFAULT_THEME = "dark"
DEFAULT_ACCENT_COLOR = "#0f7a5c"


class UserPreferencesResponse(BaseModel):
    theme: str
    accent_color: str
    # #202 (additive). ``timezone`` is the effective home timezone (IANA name):
    # the user's own, or the app's TZ when they have none. ``timezone_source``
    # says which: "user" (chosen or filled from the browser), "app" (an account
    # from before #202, following the app's TZ) or "unset" (not filled yet; the
    # web app fills it from the browser). ``base_currency`` is None until set.
    timezone: str | None = None
    timezone_source: str | None = None
    base_currency: str | None = None


class AuthSessionResponse(AuthTokenResponse):
    """Login/refresh response: the token plus who it belongs to and their preferences.

    ``user`` and ``preferences`` are additive (#146) so a cold page load needs one round
    trip instead of refresh -> /auth/me -> /auth/preferences. Optional so a client never
    has to rely on them; the web app falls back to /auth/me and /auth/preferences.
    """

    user: AuthMeResponse | None = None
    preferences: UserPreferencesResponse | None = None


class UserPreferencesPatchRequest(BaseModel):
    theme: str | None = None
    accent_color: str | None = None
    timezone: str | None = None  # IANA name, e.g. "America/New_York" (#202)
    base_currency: str | None = None  # one of SGD, USD, HKD, INR (#202)

