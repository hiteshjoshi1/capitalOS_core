from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


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


class UserPreferencesPatchRequest(BaseModel):
    theme: str | None = None
    accent_color: str | None = None

