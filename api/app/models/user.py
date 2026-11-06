from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric, Text, false, func

from .base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(Text, nullable=False, unique=True)
    display_name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserCredential(Base):
    __tablename__ = "user_credentials"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash = Column(Text, nullable=False)
    password_algo = Column(Text, nullable=False)
    password_updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OAuthIdentity(Base):
    __tablename__ = "oauth_identities"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(Text, nullable=False)
    provider_subject = Column(Text, nullable=False)
    email = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme = Column(Text, nullable=False, default="dark")
    accent_color = Column(Text, nullable=False, default="#0f7a5c")
    # #202: home timezone (IANA; NULL = the app's TZ), whether a pre-077 user
    # follows the app's TZ, and the base currency saved on the server.
    timezone = Column(Text, nullable=True)
    timezone_from_app = Column(Boolean, nullable=False, default=False, server_default=false())
    base_currency = Column(Text, nullable=True)
    # #253 (080): Risk page concentration thresholds, percent; NULL = the app's default.
    risk_largest_position_warn_pct = Column(Numeric(5, 2), nullable=True)
    risk_top_n_warn_pct = Column(Numeric(5, 2), nullable=True)
    risk_platform_warn_pct = Column(Numeric(5, 2), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
